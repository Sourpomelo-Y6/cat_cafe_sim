"""人気第1段階で解放する待合スペース強化。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_waiting_area.json').read_text())
    if not isinstance(data,dict) or set(data)!={'cost','queue_bonus','wait_bonus','daily_cost'}:
        raise ValueError('待合スペースの設定が不正です。')
    if (type(data['queue_bonus']) is not int or data['queue_bonus']<1 or type(data['wait_bonus']) is not int or data['wait_bonus']<1
            or any(type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0 for key in ('cost','daily_cost'))):
        raise ValueError('待合スペースの設定が不正です。')
    return copy.deepcopy(data)


def initialize(core,selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.waiting_area is not None
            or core.management is None or core.operating_cost is None):
        raise ValueError('待合スペースは新規ゲームの準備中に設定してください。')
    core.waiting_area=dict(rules=rules(selected),purchase=None)
    core._tick_events=[];core._record(dict(kind='initialize_waiting_area',rules=core.waiting_area['rules']))


def purchased(core):
    return (getattr(core,'waiting_area',None) or {}).get('purchase')


def upgrade_rules(data=None):
    if data is None:
        data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_waiting_area_upgrade.json').read_text())
    return rules(data)


def upgrade_reason(core,selected):
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if not purchased(core):return '先に待合スペースを購入してください。'
    if not core.compact or not core.can_set_shifts:return '待合スペースの2段階目の強化は営業準備中に行ってください。'
    if 'upgrade' in core.waiting_area:return '待合スペースは2段階目まで強化済みです。'
    from .cafe_expansion import second_popularity_cleared
    if not second_popularity_cleared(core):return '待合スペースの2段階目は人気第2段階達成後に解放されます。'
    original=core.waiting_area['rules']
    if any(selected[key]<=original[key] for key in ('queue_bonus','wait_bonus')):
        return '強化後の待機上限・待機猶予は現在より大きい必要があります。'
    if core.funds<=selected['cost']:return '強化後に資金が残る必要があります。'
    return ''


def upgrade(core,selected=None):
    selected=upgrade_rules(selected);problem=upgrade_reason(core,selected)
    if problem:raise ValueError(problem)
    core.funds-=selected['cost']
    core.waiting_area['upgrade']=dict(day=core.day,rules=selected)
    core._tick_events=[];core._emit('waiting_area_upgraded',cost=selected['cost'],
        queue_capacity=queue_capacity(core),max_wait_ticks=max_wait_ticks(core),daily_cost=daily_cost(core))
    core._record(dict(kind='upgrade_waiting_area',rules=selected))


def effective_rules(core,day=None):
    if not purchased(core) or (day is not None and day<purchased(core)['day']):return None
    upgraded=core.waiting_area.get('upgrade')
    return upgraded['rules'] if upgraded and (day is None or day>=upgraded['day']) else core.waiting_area['rules']


def reason(core):
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if core.waiting_area is None:return 'この営業では待合スペース強化を利用できません。'
    if not core.compact or not core.can_set_shifts:return '待合スペースの強化は営業準備中に行ってください。'
    if purchased(core):return '待合スペースは強化済みです。'
    from .cafe_expansion import first_popularity_cleared
    if not first_popularity_cleared(core):return '待合スペースは人気目標の第1段階達成後に解放されます。'
    if core.funds<=core.waiting_area['rules']['cost']:return '購入後に資金が残る必要があります。'
    return ''


def purchase(core):
    problem=reason(core)
    if problem:raise ValueError(problem)
    cost=core.waiting_area['rules']['cost'];core.funds-=cost
    core.waiting_area['purchase']=dict(day=core.day,cost=cost)
    core._tick_events=[];core._emit('waiting_area_purchased',cost=cost,
        queue_capacity=queue_capacity(core),max_wait_ticks=max_wait_ticks(core),daily_cost=core.waiting_area['rules']['daily_cost'])
    core._record(dict(kind='purchase_waiting_area'))


def queue_capacity(core):
    selected=effective_rules(core)
    return core.config.queue_capacity+(selected['queue_bonus'] if selected else 0)


def max_wait_ticks(core):
    selected=effective_rules(core)
    return core.config.max_wait_ticks+(selected['wait_bonus'] if selected else 0)


def daily_cost(core,day=None):
    selected=effective_rules(core,day)
    return selected['daily_cost'] if selected else 0


def expenses(core,day=None):
    row=purchased(core)
    cost=row['cost'] if row and (day is None or row['day']==day) else 0
    upgraded=(core.waiting_area or {}).get('upgrade')
    if upgraded and (day is None or day==upgraded['day']):cost+=upgraded['rules']['cost']
    return cost


def prepare(core,data):
    if not isinstance(data,dict) or set(data) not in ({'rules','purchase'},{'rules','purchase','upgrade'}):raise ValueError('待合スペースの記録が不正です。')
    selected=rules(data['rules']);row=data['purchase']
    if row is not None and (not isinstance(row,dict) or set(row)!={'day','cost'} or type(row['day']) is not int
                            or not 1<=row['day']<=core.day or row['cost']!=selected['cost']):
        raise ValueError('待合スペースの購入記録が不正です。')
    result=dict(rules=selected,purchase=copy.deepcopy(row))
    if 'upgrade' in data:
        upgraded=data['upgrade']
        if (row is None or not isinstance(upgraded,dict) or set(upgraded)!={'day','rules'}
                or type(upgraded['day']) is not int or not row['day']<=upgraded['day']<=core.day):
            raise ValueError('待合スペースの2段階目の強化記録が不正です。')
        upgraded_rules=upgrade_rules(upgraded['rules'])
        if any(upgraded_rules[key]<=selected[key] for key in ('queue_bonus','wait_bonus')):
            raise ValueError('待合スペースの強化で待機上限・待機猶予が増えていません。')
        result['upgrade']=dict(day=upgraded['day'],rules=upgraded_rules)
    return result


def validate(core,data):
    data=prepare(core,data);core.waiting_area=data
    from .cafe_expansion import first_popularity_cleared
    if purchased(core) and not first_popularity_cleared(core):raise ValueError('待合スペースの解放条件を満たしていません。')
    if 'upgrade' in data:
        from .cafe_expansion import second_popularity_cleared
        if not second_popularity_cleared(core):raise ValueError('待合スペースの2段階目の解放条件を満たしていません。')
        attempts=core.goal.get('history',[])+[core.goal]
        if data['upgrade']['day']<=attempts[1]['resolved_day']:
            raise ValueError('人気第2段階達成前に待合スペースが強化されています。')
    for day in core.day_results:
        if day['summary'].get('waiting_area_expenses',0)!=expenses(core,day['day']):
            raise ValueError('待合スペース費用と日次結果が一致しません。')
    return data
