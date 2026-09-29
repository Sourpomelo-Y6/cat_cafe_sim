"""席数と独立した在籍猫の上限と、一度だけ購入する飼育スペース。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_housing.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'initial_capacity', 'capacity_bonus', 'cost', 'daily_cost'}
            or type(data['initial_capacity']) is not int or data['initial_capacity'] < 6
            or type(data['capacity_bonus']) is not int or data['capacity_bonus'] < 1
            or any(type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] <= 0
                   for key in ('cost', 'daily_cost'))):
        raise ValueError('飼育スペースの設定が不正です。')
    return copy.deepcopy(data)


def count(core):
    from .cafe_activities import activity
    return sum(activity(core, key) != 'adopted' for key in core.cats)


def capacity(core):
    data = core.housing
    if data is None:
        return None
    return data['rules']['initial_capacity'] + (data['rules']['capacity_bonus'] if data['purchase'] else 0)


def status(core):
    limit = capacity(core)
    return (f'在籍 {count(core)}匹 / 上限なし（従来ルール）' if limit is None else
            f'在籍 {count(core)}匹 / 上限 {limit}匹 / 空き {max(0, limit-count(core))}匹')


def admission_reason(core):
    limit = capacity(core)
    if limit is None or count(core) < limit:
        return ''
    message = '飼育スペースが満員です。受け入れには空き枠が必要です。'
    if not core.housing['purchase']:
        message += '準備中に飼育スペースを拡張できます。'
    return message


def initialize(core, selected=None):
    core.require_events_resolved()
    selected = rules(selected)
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.housing is not None
            or core.operating_cost is None or count(core) > selected['initial_capacity']):
        raise ValueError('飼育スペースは店舗運営費が有効な新規ゲームの準備中に設定してください。')
    core.housing = dict(rules=selected, purchase=None)
    core._tick_events = []
    core._record(dict(kind='initialize_housing', rules=selected))


def reason(core):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if core.housing is None:
        return 'この営業は上限なしの従来ルールです。飼育スペースの購入は不要です。'
    if not core.compact or not core.can_set_shifts:
        return '飼育スペースの拡張は営業準備中に行ってください。'
    if core.housing['purchase']:
        return '飼育スペースは拡張済みです。'
    if core.funds <= core.housing['rules']['cost']:
        return '購入後に資金が残る必要があります。'
    return ''


def purchase(core):
    problem = reason(core)
    if problem:
        raise ValueError(problem)
    cost = core.housing['rules']['cost']
    core.funds -= cost
    core.housing['purchase'] = dict(day=core.day, cost=cost)
    core._tick_events = []
    core._emit('housing_purchased', cost=cost, capacity=capacity(core), daily_cost=daily_cost(core))
    core._record(dict(kind='purchase_housing'))


def daily_cost(core, day=None):
    data = core.housing
    row = data['purchase'] if data else None
    return data['rules']['daily_cost'] if row and (day is None or row['day'] <= day) else 0


def expenses(core, day=None):
    row = core.housing['purchase'] if core.housing else None
    return row['cost'] if row and (day is None or row['day'] == day) else 0


def prepare(core, data):
    if not isinstance(data, dict) or set(data) != {'rules', 'purchase'}:
        raise ValueError('飼育スペースの記録が不正です。')
    selected = rules(data['rules'])
    row = data['purchase']
    if row is not None and (not isinstance(row, dict) or set(row) != {'day', 'cost'}
                            or type(row['day']) is not int or not 1 <= row['day'] <= core.day
                            or type(row['cost']) not in (int, float) or row['cost'] != selected['cost']):
        raise ValueError('飼育スペースの購入記録が不正です。')
    return dict(rules=selected, purchase=copy.deepcopy(row))


def validate(core, data):
    core.housing = prepare(core, data)
    if core.operating_cost is None or count(core) > capacity(core):
        raise ValueError('飼育スペースの上限・運営費が在籍状態と一致しません。')
    for result in core.day_results:
        if result['summary'].get('housing_expenses', 0) != expenses(core, result['day']):
            raise ValueError('飼育スペース費用と日次結果が一致しません。')
        row = core.housing['purchase']
        limit = core.housing['rules']['initial_capacity']
        if row and row['day'] <= result['day']:
            limit += core.housing['rules']['capacity_bonus']
        if sum(cat.get('activity', 'cafe') != 'adopted' for cat in result['cats'].values()) > limit:
            raise ValueError('過去の在籍数が飼育スペースの上限を超えています。')
    return core.housing
