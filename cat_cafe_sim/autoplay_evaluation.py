"""通常設定の自動プレイ比較。既存セーブを使わず一時ゲームを集計する。"""
import argparse
import copy
import hashlib
import json
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from unittest.mock import patch

from .cafe_autoplay import AutoPlayer
from .cafe_new_game import create_game, starting_conditions
from .core.cafe_finance import values, EXPENSE_KEYS
from .autoplay_objective_metrics import collect_session, completed_window, summarize_objective
from .storage.cafe_saves import save_game, load_game


OBJECTIVES = ('popularity', 'bond', 'patron')


SCENARIOS = {
    'basic': ('basic', ()),
    'clear': ('clear', ()),
    'fast': ('fast', ()),
    'clear_no_expansion': ('clear', ('cafe_expansion.reason',)),
    'clear_no_rest': ('clear', ('cafe_equipment.reason', 'cafe_equipment.upgrade_reason', 'cafe_equipment.soundproof_reason')),
    'clear_no_seat_equipment': ('clear', ('cafe_seat_equipment.reason',)),
}

# 評価専用。通常の新規開始設定や既存セーブには適用しない。
GOAL_PRESETS = {
    'standard': None,
    'legacy': ((150, 10), (225, 10), (300, 10)),
    'medium': ((200, 15), (350, 15), (500, 20)),
    'long': ((250, 20), (450, 20), (650, 25)),
}


def evaluation_conditions(goal_preset, customer_preset='standard', objective='popularity'):
    if goal_preset not in GOAL_PRESETS:
        raise ValueError('人気目標の評価条件を確認してください。')
    if objective not in OBJECTIVES:
        raise ValueError('評価する目標を確認してください。')
    conditions = starting_conditions(objective)
    if customer_preset not in ('standard', 'legacy'):
        raise ValueError('来店人数の評価条件を確認してください。')
    if customer_preset == 'legacy':
        conditions['weekdays'].pop('popular_customer_count', None)
        conditions['weekdays'].pop('second_popular_customer_count', None)
    stages = GOAL_PRESETS[goal_preset]
    if objective != 'popularity' and goal_preset != 'standard':
        raise ValueError('人気以外の評価は標準目標を指定してください。')
    if stages is not None:
        goal = conditions['goal']
        goal.update(target=stages[0][0], days=stages[0][1], cap=stages[-1][0],
                    stages=[dict(target=target, days=days) for target, days in stages[1:]])
    return conditions


def service_metrics(rows, opening_ticks):
    seat_ticks = sum(row['summary']['seat_count']*opening_ticks for row in rows
                     if row.get('day_type') != 'day_off')
    occupied = sum(row['summary']['service_ticks'] for row in rows)
    return dict(arrivals=sum(row['summary']['arrivals'] for row in rows),
                available_seat_ticks=seat_ticks, occupied_seat_ticks=occupied,
                empty_seat_ticks=seat_ticks-occupied,
                seat_utilization=occupied/seat_ticks if seat_ticks else 0,
                queue_full_departures=sum(customer['reason']=='queue_full' for row in rows
                                         for customer in row.get('customer_outcomes', [])),
                wait_timeouts=sum(customer['reason']=='wait_timeout' for row in rows
                                  for customer in row.get('customer_outcomes', [])),
                understaffed_days=sum(sum(cat.get('shift')=='work' for cat in row['cats'].values())
                                     < row['summary']['seat_count'] for row in rows))


def collect(core, result):
    rows = copy.deepcopy(core.day_results)
    if core.closed:
        rows.append(core.day_result())
    cats = [cat for row in rows for cat in row['cats'].values()]
    expenses = {key: sum(row['summary'].get(key, 0) for row in rows) for key in EXPENSE_KEYS}
    stage_rules = [core.goal['rules']]+core.goal['rules'].get('stages', [])
    stages = []
    for index, row in enumerate([*core.goal.get('history', []), core.goal]):
        started = row.get('stage_started_day', row['started_day'])
        deadline = started+stage_rules[index]['days']-1
        stages.append(dict(stage=index+1, target=stage_rules[index]['target'], status=row['status'],
                           started_day=started, deadline=deadline, resolved_day=row['resolved_day'],
                           spare_days=deadline-row['resolved_day'] if row['resolved_day'] else None))
    income = sum(values(row['summary'])['total_income'] for row in rows)
    expenditure = sum(expenses.values())
    starting = rows[0]['summary']['opening_funds'] if rows else core.funds
    if abs(starting+income-expenditure-core.funds)>1e-8:
        raise ValueError('集計した収支と最終資金が一致しません。')
    metrics = dict(days=len(rows), day_offs=sum(row.get('day_type')=='day_off' for row in rows),
        starting_funds=starting, income=income, expenses=expenditure, final_funds=core.funds,
        final_popularity=core.management['popularity'],
        healthy_rest_cat_days=sum(cat.get('shift')=='rest' and cat.get('activity', 'cafe')=='cafe'
                                 and cat['health']['before']=='healthy' for cat in cats),
        sick_cat_days=sum(cat['health']['before']=='sick' for cat in cats),
        illnesses=sum(cat['health']['outcome']=='sick' for cat in cats),
        runaways=len(core.management['events']), cat_days=len(cats),
        mean_fatigue=mean(cat['fatigue_after'] for cat in cats) if cats else 0,
        mean_stress=mean(cat['stress'] for cat in cats) if cats else 0,
        max_fatigue=max((cat['fatigue_after'] for cat in cats), default=0),
        max_stress=max((cat['stress'] for cat in cats), default=0),
        equipment_cost=expenses['equipment_expenses']+expenses['seat_equipment_expenses']+expenses['expansion_expenses'],
        seats=len(core.seats), expense_breakdown=expenses)
    metrics.update(service_metrics(rows, core.config.opening_ticks))
    return dict(reason=result.reason, message=result.message, metrics=metrics, stages=stages, daily=rows)


def evaluate(*, max_days=60, scenarios=None, goal_preset='standard', customer_preset='standard',
             objective='popularity', seed=0, emit=print):
    if type(seed) is not int or seed < 0:
        raise ValueError('シードは0以上の整数を指定してください。')
    selected = list(SCENARIOS) if scenarios is None else list(scenarios)
    if not selected or any(name not in SCENARIOS for name in selected):
        raise ValueError('比較条件を確認してください。')
    if type(max_days) is not int or max_days < 1:
        raise ValueError('日数は1以上の整数を指定してください。')
    conditions = evaluation_conditions(goal_preset, customer_preset, objective)
    encoded = json.dumps(conditions, ensure_ascii=False, sort_keys=True).encode()
    output = dict(format_version=1, evaluated_at=datetime.now(timezone.utc).isoformat(), seed=seed,
                  goal_preset=goal_preset, objective=objective,
                  customer_preset=customer_preset,
                  max_days=max_days, conditions=conditions, conditions_sha256=hashlib.sha256(encoded).hexdigest(), runs={})
    window_sources = {}
    with tempfile.TemporaryDirectory(prefix='cat-cafe-balance-') as directory:
        for name in selected:
            mode, excluded = SCENARIOS[name]
            emit(f'比較開始: {objective} / seed={seed} / {name}')
            session = create_game(Path(directory)/name, copy.deepcopy(conditions), seed=seed)
            # 比較専用プロセスで購入可否だけを制限。係数・ゲーム状態は変更しない。
            # 休養・割り当て・イベントなどは同じ通常操作を実行する。
            with ExitStack() as stack:
                for target in excluded:
                    stack.enter_context(patch('cat_cafe_sim.core.'+target, return_value='評価条件により購入を見送り'))
                result = AutoPlayer(session, objective=objective, mode=mode, max_days=max_days).run()
            collected = collect_session(session, result, objective)
            save_game(session, session.checkpoint_path)
            loaded, _ = load_game(session.checkpoint_path)
            if loaded.core.snapshot() != session.core.snapshot():
                raise ValueError('最終状態の保存再開が一致しません。')
            output['runs'][name] = dict(mode=mode, excluded_purchase_checks=list(excluded),
                                       save_resume_verified=True, **collected)
            if name in ('clear', 'fast'):
                window_sources[name] = (session.core, result)
            emit(f'比較終了: {objective} / seed={seed} / {name} / {result.reason}'
                 f' / 閉店済み{result.days}日 / 現在{session.core.day}日目')
    if 'clear' in selected and 'fast' in selected:
        days = min(output['runs'][name]['metrics']['days'] for name in ('clear', 'fast'))
        for name in ('clear', 'fast'):
            output['runs'][name]['common_window_metrics'] = completed_window(*window_sources[name], days) if days else None
    return output


def distribution(values):
    """達成なしは0日とせず、空の分布として扱う。"""
    return dict(count=len(values), mean=mean(values) if values else None,
                min=min(values) if values else None, max=max(values) if values else None)


def summarize(reports):
    """同じ初期条件のシード別結果を集計。未達成を達成日数に混ぜない。"""
    names = list(reports[0]['runs'])
    summary = {}
    for name in names:
        runs = [report['runs'][name] for report in reports]
        completed = [run for run in runs if run['reason'] == 'completed']
        reasons = {reason: sum(run['reason'] == reason for run in runs)
                   for reason in sorted({run['reason'] for run in runs})}
        stages = []
        for index in (range(1, 4) if reports[0].get('objective', 'popularity') == 'popularity' else ()):
            cleared = [stage for run in runs for stage in run['stages']
                       if stage['stage'] == index and stage['status'] == 'cleared']
            expired = sum(stage['stage'] == index and stage['status'] == 'expired'
                          for run in runs for stage in run['stages'])
            stages.append(dict(stage=index, cleared=len(cleared), expired=expired,
                               achievement_rate=len(cleared)/len(runs),
                               resolved_days=distribution([row['resolved_day'] for row in cleared]),
                               spare_days=distribution([row['spare_days'] for row in cleared])))
        metric_names = ('days', 'illnesses', 'runaways', 'sick_cat_days', 'wait_timeouts',
                        'queue_full_departures', 'equipment_cost', 'income', 'expenses',
                        'final_funds', 'seats', 'mean_fatigue', 'mean_stress', 'seat_utilization')
        metrics = {key: distribution([run['metrics'][key] for run in runs]) for key in metric_names}
        arrivals = sum(run['metrics']['arrivals'] for run in runs)
        cat_days = sum(run['metrics']['cat_days'] for run in runs)
        summary[name] = dict(trials=len(runs), completed=len(completed),
                             completion_rate=len(completed)/len(runs), stop_reasons=reasons,
                             completion_days=distribution([run['metrics']['days'] for run in completed]),
                             completion_calendar_days=distribution([
                                 run['objective_result']['resolved_day'] for run in completed
                                 if run.get('objective_result', {}).get('resolved_day') is not None]),
                             stages=stages, metrics=metrics,
                             wait_timeout_rate=sum(run['metrics']['wait_timeouts'] for run in runs)/arrivals if arrivals else None,
                             sick_cat_day_rate=sum(run['metrics']['sick_cat_days'] for run in runs)/cat_days if cat_days else None)
        summary[name]['objective_metrics'] = summarize_objective(runs)
        capacity = sum(run['metrics']['available_seat_ticks'] for run in runs)
        summary[name]['seat_utilization'] = (sum(run['metrics']['occupied_seat_ticks'] for run in runs)
                                             / capacity if capacity else None)
    paired = None
    if 'clear' in names and 'fast' in names:
        both = [report for report in reports
                if all(report['runs'][name]['reason'] == 'completed' for name in ('clear', 'fast'))]
        deltas = [r['runs']['fast']['metrics']['days']-r['runs']['clear']['metrics']['days'] for r in both]
        paired = dict(both_completed=len(both), fast_earlier=sum(d < 0 for d in deltas),
                      same_day=sum(d == 0 for d in deltas), clear_earlier=sum(d > 0 for d in deltas),
                      fast_minus_clear_days=distribution(deltas),
                      only_clear_completed=sum(r['runs']['clear']['reason'] == 'completed' and
                                               r['runs']['fast']['reason'] != 'completed' for r in reports),
                      only_fast_completed=sum(r['runs']['fast']['reason'] == 'completed' and
                                              r['runs']['clear']['reason'] != 'completed' for r in reports))
        windows = [r for r in reports if all(r['runs'][name].get('common_window_metrics')
                                            for name in ('clear', 'fast'))]
        paired['common_window'] = dict(
            trials=len(windows), days=distribution([r['runs']['clear']['common_window_metrics']['days'] for r in windows]),
            fast_minus_clear={key: distribution([
                r['runs']['fast']['common_window_metrics'][key]-r['runs']['clear']['common_window_metrics'][key]
                for r in windows]) for key in ('income', 'final_funds', 'illnesses', 'runaways',
                                               'mean_fatigue', 'mean_stress', 'seat_utilization', 'wait_timeouts')})
        paired['fast_minus_clear_calendar_days'] = distribution([
            r['runs']['fast']['objective_result']['resolved_day']-r['runs']['clear']['objective_result']['resolved_day']
            for r in both if all(r['runs'][name].get('objective_result', {}).get('resolved_day') is not None
                                 for name in ('clear', 'fast'))])
    return dict(by_scenario=summary, paired=paired)


def combine_reports(reports):
    """単一シードの詳細結果を、日次データを省いた比較資料にまとめる。"""
    if not reports or len({r['seed'] for r in reports}) != len(reports):
        raise ValueError('異なるシードの結果を1件以上指定してください。')
    first = reports[0]
    if any(r.get('objective', 'popularity') != first.get('objective', 'popularity') for r in reports):
        raise ValueError('同じ目標の結果を指定してください。')
    keys = ('conditions_sha256', 'max_days', 'goal_preset', 'customer_preset')
    if any(any(r[key] != first[key] for key in keys) or
           list(r['runs']) != list(first['runs']) for r in reports):
        raise ValueError('同じ初期設定・方針・日数上限の結果を指定してください。')
    output = {key: copy.deepcopy(first[key]) for key in (*keys, 'conditions')}
    output.update(format_version=2, objective=first.get('objective', 'popularity'), evaluated_at=datetime.now(timezone.utc).isoformat(),
                  seeds=[r['seed'] for r in reports], detail_level='metrics_and_stages',
                  evaluations=[dict(seed=r['seed'], evaluated_at=r['evaluated_at'],
                                    runs={name: {key: copy.deepcopy(value) for key, value in run.items() if key != 'daily'}
                                          for name, run in r['runs'].items()}) for r in reports],
                  summary=summarize(reports))
    return output


def evaluate_seeds(seeds, **kwargs):
    seeds = list(seeds)
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('重複のない0以上の整数シードを1件以上指定してください。')
    return combine_reports([evaluate(seed=seed, **kwargs) for seed in seeds])


def evaluate_objectives(objectives, seeds, **kwargs):
    objectives, seeds = list(objectives), list(seeds)
    if not objectives or len(set(objectives)) != len(objectives) or any(o not in OBJECTIVES for o in objectives):
        raise ValueError('重複のない評価目標を指定してください。')
    # 全目標の条件を実行前に検証する。
    for objective in objectives:
        evaluation_conditions(kwargs.get('goal_preset', 'standard'),
                              kwargs.get('customer_preset', 'standard'), objective)
    return dict(format_version=3, evaluated_at=datetime.now(timezone.utc).isoformat(),
                objectives=objectives, seeds=seeds,
                by_objective={objective: evaluate_seeds(seeds, objective=objective, **kwargs)
                              for objective in objectives})


def main(argv=None):
    parser = argparse.ArgumentParser(description='人気・好感度・有力者の自動プレイ方針を比較します。')
    objectives = parser.add_mutually_exclusive_group()
    objectives.add_argument('--objective', choices=OBJECTIVES, default='popularity')
    objectives.add_argument('--objectives', choices=OBJECTIVES, nargs='+', help='複数目標を同じシードで個別評価')
    parser.add_argument('--days', type=int, default=60)
    seeds = parser.add_mutually_exclusive_group()
    seeds.add_argument('--seed', type=int, default=0, help='単一シードの詳細評価（既定0）')
    seeds.add_argument('--seeds', type=int, nargs='+', help='複数シードの集計評価。例: --seeds 0 1 2')
    parser.add_argument('--goal-preset', choices=GOAL_PRESETS, default='standard',
                        help='評価専用の人気目標と期限。通常ゲームの設定は変更しません。')
    parser.add_argument('--scenarios', nargs='+', choices=SCENARIOS,
                        help='比較する方針・設備除外条件（省略時は全6条件）')
    parser.add_argument('--customer-preset', choices=('standard', 'legacy'), default='standard',
                        help='評価専用の来店設定。legacyは人気達成後の通常客増加を外します。')
    parser.add_argument('--output', type=Path, default=Path('reports/autoplay_balance.json'))
    args = parser.parse_args(argv)
    if args.days<1:
        parser.error('日数は1以上で指定してください。')
    if args.seed < 0 or (args.seeds is not None and
                         (any(seed < 0 for seed in args.seeds) or len(set(args.seeds)) != len(args.seeds))):
        parser.error('シードは重複のない0以上の整数で指定してください。')
    options = dict(max_days=args.days, scenarios=args.scenarios, goal_preset=args.goal_preset,
                   customer_preset=args.customer_preset, emit=lambda line: print(line, flush=True))
    selected = args.objectives or [args.objective]
    try:
        for objective in selected:
            evaluation_conditions(args.goal_preset, args.customer_preset, objective)
        if args.objectives is not None:
            result = evaluate_objectives(selected, args.seeds if args.seeds is not None else [args.seed], **options)
        else:
            result = (evaluate_seeds(args.seeds, objective=args.objective, **options) if args.seeds is not None
                      else evaluate(seed=args.seed, objective=args.objective, **options))
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'集計結果: {args.output}')


if __name__=='__main__':
    main()
