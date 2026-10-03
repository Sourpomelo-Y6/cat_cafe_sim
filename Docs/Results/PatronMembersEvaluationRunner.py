"""3人の有力者を通常操作で検証し、派遣候補と最終保存の整合性を記録する。"""
import argparse
import copy
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from cat_cafe_sim.autoplay_evaluation import collect
from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core import cafe_activities, cafe_patron_members
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


def run(task):
    seed, output = task
    conditions = starting_conditions('patron')
    with tempfile.TemporaryDirectory(prefix='patron-seeds-') as directory:
        session = create_game(directory, copy.deepcopy(conditions), seed=seed)
        core = session.core
        audit = []
        original_dispatch = session.dispatch

        def dispatch(cat_id, rules=None):
            core = session.core
            # 通常の操作を委譲する直前に、同じ読み取り専用判定を記録する。
            if rules['id'] in cafe_patron_members.IDS:
                candidates = []
                for candidate_id, cat in core.cats.items():
                    candidates.append(dict(
                        cat_id=candidate_id,
                        name=session.profiles[candidate_id]['name'],
                        terms=cafe_patron_members.terms(core, candidate_id, rules['id']),
                        blocked_reason=cafe_activities.dispatch_reason(core, candidate_id, rules),
                        fatigue=cat.fatigue, health=cat.health_status,
                        features=copy.deepcopy(core.cat_features[candidate_id]),
                        growth=copy.deepcopy(core.growth['cats'][candidate_id]),
                    ))
                audit.append(dict(day=core.day, destination_id=rules['id'],
                                  cat_id=cat_id, candidates=candidates))
            return original_dispatch(cat_id, rules)

        session.dispatch = dispatch
        player = AutoPlayer(session, objective='patron', mode='clear',
                            max_days=90, emit=lambda line: None)
        result = player.run()
        # 交流結果の保存等でセッションがコアを復元し直す場合がある。
        core = session.core
        # 準備中の帰還で達成する場合、未閉店日の収支も最終資金に含まれる。
        projection = copy.copy(core)
        preparation = core.summary() if not core.closed else None
        if preparation is not None:
            projection.funds = preparation['opening_funds']
        metrics = collect(projection, result)['metrics']
        if preparation is not None:
            metrics['income'] += preparation['total_income']
            metrics['expenses'] += preparation['total_expenses']
            for key in metrics['expense_breakdown']:
                metrics['expense_breakdown'][key] += preparation.get(key, 0)
            metrics['final_funds'] = core.funds
            metrics['uncompleted_day_finance'] = preparation
        if abs(metrics['starting_funds']+metrics['income']-metrics['expenses']-core.funds) > 1e-8:
            raise ValueError('閉店済み日と未閉店日の収支が一致しません。')
        if metrics['days'] != result.days:
            raise ValueError('完了日数と集計した日数が一致しません。')
        save_game(session, session.checkpoint_path)
        loaded, _ = load_game(session.checkpoint_path)
        if loaded.core.snapshot() != core.snapshot():
            raise ValueError('最終状態の保存再開が一致しません。')
        row = dict(seed=seed, reason=result.reason, completed_days=result.days,
                   operations=result.operations, metrics=metrics, cat_count=len(core.cats),
                   goal=core.patron, growth=core.growth['cats'],
                   events=list(copy.deepcopy(core.activities['events']).values()),
                   dispatch_audit=audit, save_resume_verified=True)
        (Path(output)/f'{seed}.json').write_text(
            json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(seed=seed, reason=result.reason, days=result.days,
                              funds=core.funds, illnesses=metrics['illnesses'],
                              visits=len(row['events'])), ensure_ascii=False), flush=True)
        return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, nargs='+', default=list(range(10)))
    parser.add_argument('--output', default='reports/patron-members-seeds')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if any(seed < 0 for seed in args.seeds) or args.workers < 1:
        parser.error('シードは0以上、並列数は1以上を指定してください。')
    if len(set(args.seeds)) != len(args.seeds):
        parser.error('同じシードを重複指定しないでください。')
    Path(args.output).mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, [(seed, args.output) for seed in args.seeds]))


if __name__ == '__main__':
    main()
