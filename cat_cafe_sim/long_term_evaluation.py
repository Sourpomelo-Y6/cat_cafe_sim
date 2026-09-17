"""通常営業の長期比較。プレイヤーの保存先を使わず、試行ごとの一時領域で測定する。"""
import argparse
import csv
import json
import platform
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .cafe_interaction import CafeInteractionSession
from .core.cafe_health import HealthRules
from .core.cafe_shifts import ShiftRules, fatigue_rest_schedule
from .core.config import Config
from .core.human_cat_relationship import RelationshipConfig
from .core.multi_seat_cafe import MultiSeatCafeCore
from .storage.cafe_saves import save_game, load_game
from .storage.playtest_cats import add_playtest_cats
from .storage.relationships import RelationshipStore
from .cafe_history import comparison_rows

BASELINE_POLICIES = ('all_work', 'rotating_rest', 'fatigue_closure')
FATIGUE_POLICIES = ('fatigue_rest_one', 'fatigue_rest_two', 'fatigue_assignment')
POLICIES = BASELINE_POLICIES + FATIGUE_POLICIES


def choose_schedule(core, policy):
    if policy not in POLICIES:
        raise ValueError('unknown evaluation policy')
    roster = sorted(core.cats)
    healthy = [key for key in roster if core.cats[key].health_status == 'healthy']
    if not healthy:
        return None
    if policy == 'fatigue_closure' and max(core.cats[key].fatigue for key in healthy) >= core.health_rules.safe_fatigue:
        return None
    if policy == 'rotating_rest':
        off = roster[(core.day - 1) % len(roster)]
        healthy = [key for key in healthy if key != off]
    if policy in ('fatigue_rest_one', 'fatigue_rest_two'):
        count = 1 if policy == 'fatigue_rest_one' else 2
        healthy = fatigue_rest_schedule(core.cats, count)
    return healthy or None


def choose_fatigue_cat(session):
    """朝の疲労と当日の接客量から閉店時疲労を見積もり、低い猫を優先する。"""
    core = session.core
    return min(session.available_cats(), key=lambda cat: (
        min(core.shift_rules.max_fatigue,
            cat.fatigue + core.cat_service_ticks[cat.id] * core.shift_rules.fatigue_per_service_tick),
        -cat.stamina, cat.id))


def evaluation_step(session, policy):
    if policy == 'fatigue_assignment':
        while session.free_seats and session.core.queue and session.available_cats():
            cat = choose_fatigue_cat(session)
            session.start(session.core.queue[0], cat.id, session.free_seats[0])
        return session.automatic_step(auto_assign=False)
    return session.automatic_step()


def evaluate(policy, seed, days, output, progress=None):
    if days < 1:
        raise ValueError('days must be positive')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows, samples = [], []
    with tempfile.TemporaryDirectory(prefix='cat-cafe-evaluation-') as temporary:
        store = RelationshipStore(Path(temporary) / 'relationships.json')
        add_playtest_cats(store)
        core = MultiSeatCafeCore(Config.load(), seed=seed, cat_ids=[row['cat_id'] for row in store.list_cats()], compact=True)
        core.set_shifts(list(core.cats), asdict(ShiftRules.load()))
        core.enable_health(asdict(HealthRules.load()))
        session = CafeInteractionSession(core=core, store=store, interaction_config=RelationshipConfig.load())
        manifest = dict(policy=policy, seed=seed, days=days, config=core.config.to_dict(),
                        shifts=asdict(core.shift_rules), health=asdict(core.health_rules),
                        interaction=session.interaction_config.to_dict(), cats=store.list_cats(),
                        automatic_policy=session.policy.version,
                        measurement='continuous unsaved simulation; checkpoints measured through a separate session')
        started = time.perf_counter()
        simulation_seconds = 0
        for day in range(1, days + 1):
            day_started = time.perf_counter()
            sick_days = sum(cat.health_status == 'sick' for cat in core.cats.values())
            schedule = choose_schedule(core, policy)
            if schedule is None:
                session.day_off()
            else:
                session.set_shifts(schedule)
                while not core.closed:
                    evaluation_step(session, policy)
                session.next_day()
            elapsed = time.perf_counter() - day_started
            simulation_seconds += elapsed
            result = core.day_results[-1]
            summary = result['summary']
            row = dict(day=day, day_off=result.get('day_type') == 'day_off',
                       revenue=summary['revenue'], bonus=summary['interaction_bonus'],
                       arrivals=summary['arrivals'], interactions=summary['completed_interactions'],
                       service_ticks=summary['service_ticks'],
                       illnesses=sum(cat['health']['outcome'] == 'sick' for cat in result['cats'].values()),
                       recovery_cat_days=sick_days,
                       mean_fatigue=sum(cat['fatigue_after'] for cat in result['cats'].values()) / len(core.cats),
                       max_fatigue=max(cat['fatigue_after'] for cat in result['cats'].values()),
                       affinity_delta=sum(item['change'] for item in result['affinity_changes']),
                       simulation_seconds=elapsed)
            rows.append(row)
            if day in {1, 25, 50, days}:
                checkpoint = Path(temporary) / 'checkpoint.json'
                probe = CafeInteractionSession(core=core, store=store, interaction_config=session.interaction_config)
                probe.persisted = set(session.persisted)
                t = time.perf_counter()
                save_game(probe, checkpoint, auto_assign=True)
                save_seconds = time.perf_counter() - t
                t = time.perf_counter()
                restored, automatic = load_game(checkpoint)
                load_seconds = time.perf_counter() - t
                if (not automatic or restored.core.snapshot() != core.snapshot()
                        or comparison_rows(restored.core) != comparison_rows(core)):
                    raise AssertionError('checkpoint changed the evaluation state')
                samples.append(dict(day=day, save_bytes=checkpoint.stat().st_size,
                                    relationship_bytes=store.path.stat().st_size,
                                    save_seconds=save_seconds, load_seconds=load_seconds))
            if progress and (day % 10 == 0 or day == days):
                progress(dict(policy=policy, seed=seed, day=day, elapsed_seconds=round(time.perf_counter()-started, 2)))
        metrics = {key:sum(row[key] for row in rows) for key in
                   ('revenue','bonus','arrivals','interactions','service_ticks','illnesses','recovery_cat_days','affinity_delta')}
        metrics.update(open_days=sum(not row['day_off'] for row in rows),
                       closed_days=sum(row['day_off'] for row in rows),
                       mean_fatigue=sum(row['mean_fatigue'] for row in rows)/days,
                       peak_fatigue=max(row['max_fatigue'] for row in rows),
                       simulation_seconds=simulation_seconds,
                       total_seconds=time.perf_counter()-started,
                       final_funds=core.funds)
        if core.funds != core.config.initial_funds + metrics['revenue'] or session.pending:
            raise AssertionError('invalid final settlement')
        report = dict(manifest=manifest, metrics=metrics, samples=samples, daily=rows)
        stem = f'{policy}-seed-{seed}'
        (output / f'{stem}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        with (output / f'{stem}.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=100)
    parser.add_argument('--seeds', type=int, nargs='+', default=[0,1,2])
    parser.add_argument('--policies', nargs='+', choices=POLICIES, default=list(BASELINE_POLICIES))
    parser.add_argument('--output', type=Path, default=Path('reports/long_term'))
    args = parser.parse_args()
    if args.days < 1:parser.error('--days must be positive')
    summary = dict(python=sys.version, platform=platform.platform(), runs=[])
    for policy in args.policies:
        for seed in args.seeds:
            report = evaluate(policy, seed, args.days, args.output,
                              progress=lambda value:print(json.dumps(value), flush=True))
            summary['runs'].append(dict(policy=policy, seed=seed, metrics=report['metrics'], samples=report['samples']))
            (args.output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
