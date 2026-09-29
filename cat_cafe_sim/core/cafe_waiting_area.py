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
    return core.config.queue_capacity+(core.waiting_area['rules']['queue_bonus'] if purchased(core) else 0)


def max_wait_ticks(core):
    return core.config.max_wait_ticks+(core.waiting_area['rules']['wait_bonus'] if purchased(core) else 0)


def daily_cost(core):
    return core.waiting_area['rules']['daily_cost'] if purchased(core) else 0


def expenses(core,day=None):
    row=purchased(core)
    return row['cost'] if row and (day is None or row['day']==day) else 0


def prepare(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','purchase'}:raise ValueError('待合スペースの記録が不正です。')
    selected=rules(data['rules']);row=data['purchase']
    if row is not None and (not isinstance(row,dict) or set(row)!={'day','cost'} or type(row['day']) is not int
                            or not 1<=row['day']<=core.day or row['cost']!=selected['cost']):
        raise ValueError('待合スペースの購入記録が不正です。')
    return dict(rules=selected,purchase=copy.deepcopy(row))


def validate(core,data):
    data=prepare(core,data);core.waiting_area=data
    from .cafe_expansion import first_popularity_cleared
    if purchased(core) and not first_popularity_cleared(core):raise ValueError('待合スペースの解放条件を満たしていません。')
    for day in core.day_results:
        if day['summary'].get('waiting_area_expenses',0)!=expenses(core,day['day']):
            raise ValueError('待合スペース費用と日次結果が一致しません。')
    return data
