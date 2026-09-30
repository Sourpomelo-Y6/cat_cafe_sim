"""席数と独立した在籍猫の上限と、2段階まで拡張する飼育スペース。"""
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


def capacity(core, day=None):
    data = core.housing
    if data is None:
        return None
    limit=data['rules']['initial_capacity']
    if data['purchase'] and (day is None or data['purchase']['day']<=day):
        limit+=data['rules']['capacity_bonus']
        upgraded=data.get('upgrade')
        if upgraded and (day is None or upgraded['day']<=day):limit+=upgraded['rules']['capacity_bonus']
    return limit


def status(core):
    limit = capacity(core)
    return (f'在籍 {count(core)}匹 / 上限なし（従来ルール）' if limit is None else
            f'在籍 {count(core)}匹 / 上限 {limit}匹 / 空き {max(0, limit-count(core))}匹')


def admission_reason(core):
    limit = capacity(core)
    if limit is None or count(core) < limit:
        return ''
    message = '飼育スペースが満員です。受け入れには空き枠が必要です。'
    if not core.housing.get('upgrade'):
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
        # 紹介への回答は拡張後に行える。他の確認待ちは引き続き止める。
        core.require_events_resolved(ignore_intake=True, ignore_introductions=True,
                                     ignore_regular_introduction=True)
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


def upgrade_rules(data=None):
    if data is None:
        data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_housing_upgrade.json').read_text())
    if (not isinstance(data,dict) or set(data)!={'capacity_bonus','cost','daily_cost'}
            or type(data['capacity_bonus']) is not int or data['capacity_bonus']<1
            or any(type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0
                   for key in ('cost','daily_cost'))):
        raise ValueError('飼育スペースの追加拡張設定が不正です。')
    return copy.deepcopy(data)


def upgrade_reason(core, selected):
    try:
        core.require_events_resolved(ignore_intake=True,ignore_introductions=True,ignore_regular_introduction=True)
    except ValueError as exc:return str(exc)
    if core.housing is None:return 'この営業は上限なしの従来ルールです。飼育スペースの拡張は不要です。'
    if not core.compact or not core.can_set_shifts:return '飼育スペースの追加拡張は営業準備中に行ってください。'
    if not core.housing['purchase']:return '先に飼育スペースを初回拡張してください。'
    if 'upgrade' in core.housing:return '飼育スペースは2段階目まで拡張済みです。'
    if selected['daily_cost']<=core.housing['rules']['daily_cost']:return '追加拡張後の維持費は現在より大きい必要があります。'
    if core.funds<=selected['cost']:return '追加拡張後に資金が残る必要があります。'
    return ''


def upgrade(core, selected=None):
    selected=upgrade_rules(selected)
    problem=upgrade_reason(core,selected)
    if problem:raise ValueError(problem)
    core.funds-=selected['cost']
    core.housing['upgrade']=dict(day=core.day,rules=selected)
    core._tick_events=[]
    core._emit('housing_upgraded',cost=selected['cost'],capacity=capacity(core),daily_cost=daily_cost(core))
    core._record(dict(kind='upgrade_housing',rules=selected))


def daily_cost(core, day=None):
    data = core.housing
    row = data['purchase'] if data else None
    if not row or (day is not None and day<row['day']):return 0
    upgraded=data.get('upgrade')
    return upgraded['rules']['daily_cost'] if upgraded and (day is None or day>=upgraded['day']) else data['rules']['daily_cost']


def expenses(core, day=None):
    row = core.housing['purchase'] if core.housing else None
    cost=row['cost'] if row and (day is None or row['day']==day) else 0
    upgraded=(core.housing or {}).get('upgrade')
    if upgraded and (day is None or upgraded['day']==day):cost+=upgraded['rules']['cost']
    return cost


def prepare(core, data):
    if not isinstance(data, dict) or set(data) not in ({'rules','purchase'},{'rules','purchase','upgrade'}):
        raise ValueError('飼育スペースの記録が不正です。')
    selected = rules(data['rules'])
    row = data['purchase']
    if row is not None and (not isinstance(row, dict) or set(row) != {'day', 'cost'}
                            or type(row['day']) is not int or not 1 <= row['day'] <= core.day
                            or type(row['cost']) not in (int, float) or row['cost'] != selected['cost']):
        raise ValueError('飼育スペースの購入記録が不正です。')
    result=dict(rules=selected,purchase=copy.deepcopy(row))
    if 'upgrade' in data:
        upgraded=data['upgrade']
        if (row is None or not isinstance(upgraded,dict) or set(upgraded)!={'day','rules'}
                or type(upgraded['day']) is not int or not row['day']<=upgraded['day']<=core.day):
            raise ValueError('飼育スペースの追加拡張記録が不正です。')
        upgraded_rules=upgrade_rules(upgraded['rules'])
        if upgraded_rules['daily_cost']<=selected['daily_cost']:
            raise ValueError('飼育スペースの追加維持費が不正です。')
        result['upgrade']=dict(day=upgraded['day'],rules=upgraded_rules)
    return result


def validate(core, data):
    core.housing = prepare(core, data)
    if core.operating_cost is None or count(core) > capacity(core):
        raise ValueError('飼育スペースの上限・運営費が在籍状態と一致しません。')
    for result in core.day_results:
        if result['summary'].get('housing_expenses', 0) != expenses(core, result['day']):
            raise ValueError('飼育スペース費用と日次結果が一致しません。')
        limit=capacity(core,result['day'])
        if sum(cat.get('activity', 'cafe') != 'adopted' for cat in result['cats'].values()) > limit:
            raise ValueError('過去の在籍数が飼育スペースの上限を超えています。')
    return core.housing
