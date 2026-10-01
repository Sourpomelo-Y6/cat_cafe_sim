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


SCENARIOS = {
    'basic': ('basic', ()),
    'clear': ('clear', ()),
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


def evaluation_conditions(goal_preset, customer_preset='standard'):
    if goal_preset not in GOAL_PRESETS:
        raise ValueError('人気目標の評価条件を確認してください。')
    conditions = starting_conditions()
    if customer_preset not in ('standard', 'legacy'):
        raise ValueError('来店人数の評価条件を確認してください。')
    if customer_preset == 'legacy':
        conditions['weekdays'].pop('popular_customer_count', None)
    stages = GOAL_PRESETS[goal_preset]
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


def evaluate(*, max_days=60, scenarios=None, goal_preset='standard', customer_preset='standard', emit=print):
    selected = list(SCENARIOS) if scenarios is None else list(scenarios)
    if not selected or any(name not in SCENARIOS for name in selected):
        raise ValueError('比較条件を確認してください。')
    conditions = evaluation_conditions(goal_preset, customer_preset)
    encoded = json.dumps(conditions, ensure_ascii=False, sort_keys=True).encode()
    output = dict(format_version=1, evaluated_at=datetime.now(timezone.utc).isoformat(), seed=0,
                  goal_preset=goal_preset,
                  customer_preset=customer_preset,
                  max_days=max_days, conditions=conditions, conditions_sha256=hashlib.sha256(encoded).hexdigest(), runs={})
    with tempfile.TemporaryDirectory(prefix='cat-cafe-balance-') as directory:
        for name in selected:
            mode, excluded = SCENARIOS[name]
            emit(f'比較開始: {name}')
            session = create_game(Path(directory)/name, copy.deepcopy(conditions))
            # 比較専用プロセスで購入可否だけを制限。係数・ゲーム状態は変更しない。
            # 休養・割り当て・イベントなどは同じ通常操作を実行する。
            with ExitStack() as stack:
                for target in excluded:
                    stack.enter_context(patch('cat_cafe_sim.core.'+target, return_value='評価条件により購入を見送り'))
                result = AutoPlayer(session, mode=mode, max_days=max_days).run()
            output['runs'][name] = dict(mode=mode, excluded_purchase_checks=list(excluded), **collect(session.core, result))
            emit(f'比較終了: {name} / {result.reason} / {result.days}日 / 人気{session.core.management["popularity"]:g}')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description='自動プレイ2方針と設備を外した条件を比較します。')
    parser.add_argument('--days', type=int, default=60)
    parser.add_argument('--goal-preset', choices=GOAL_PRESETS, default='standard',
                        help='評価専用の人気目標と期限。通常ゲームの設定は変更しません。')
    parser.add_argument('--scenarios', nargs='+', choices=SCENARIOS,
                        help='比較する方針・設備除外条件（省略時は全5条件）')
    parser.add_argument('--customer-preset', choices=('standard', 'legacy'), default='standard',
                        help='評価専用の来店設定。legacyは人気達成後の通常客増加を外します。')
    parser.add_argument('--output', type=Path, default=Path('reports/autoplay_balance.json'))
    args = parser.parse_args(argv)
    if args.days<1:
        parser.error('日数は1以上で指定してください。')
    result = evaluate(max_days=args.days, scenarios=args.scenarios, goal_preset=args.goal_preset,
                      customer_preset=args.customer_preset,
                      emit=lambda line: print(line, flush=True))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'集計結果: {args.output}')


if __name__=='__main__':
    main()
