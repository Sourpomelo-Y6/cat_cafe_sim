"""営業前に確定し、その日の来店・費用・所持品へ反映する店舗イベント。"""
import copy
import hashlib
import json
import math
from pathlib import Path

TYPES=('festival','rain','supplies','trouble')
LABELS={'festival':'地域のお祭り','rain':'雨の日','supplies':'支援物資','trouble':'設備トラブル'}


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_store_events.json').read_text())
    if (not isinstance(data,dict) or set(data)!={'probability','festival_customer_tick','trouble_cost','supply'}
            or type(data['probability']) not in (int,float) or not math.isfinite(data['probability']) or not 0<=data['probability']<=1
            or type(data['festival_customer_tick']) is not int or data['festival_customer_tick']<0
            or type(data['trouble_cost']) not in (int,float) or not math.isfinite(data['trouble_cost']) or data['trouble_cost']<=0):
        raise ValueError('店舗イベントの設定が不正です。')
    from .cafe_items import definition
    definition(data['supply']);return copy.deepcopy(data)


def initialize(core,selected=None):
    core.require_events_resolved()
    if not core.compact or core.day!=1 or not core.can_set_shifts or core.store_events is not None or core.weekdays is None or core.operating_cost is None:
        raise ValueError('店舗イベントは新規ゲームの準備中に設定してください。')
    core.store_events=dict(rules=rules(selected),days=[]);core._tick_events=[];present(core)
    core._record(dict(kind='initialize_store_events',rules=core.store_events['rules']))


def draw(seed,day,label):
    raw=hashlib.sha256(f'store-event:{seed}:{day}:{label}'.encode()).digest()
    return int.from_bytes(raw[:8],'big')/2**64


def present(core):
    data=core.store_events
    if data is None or any(row['day']==core.day for row in data['days']):return
    value=draw(core.seed,core.day,'occur');kind=None
    if value<data['rules']['probability']:
        kind=TYPES[int(draw(core.seed,core.day,'type')*len(TYPES))]
    row=dict(day=core.day,type=kind,draw=value);data['days'].append(row)
    core._emit('store_event_presented',event_type=kind,label=LABELS.get(kind,'イベントなし'))


def row(core,day=None):
    day=core.day if day is None else day
    return next((r for r in (core.store_events or {}).get('days',[]) if r['day']==day),None)


def modify_schedule(core,planned,day):
    event=row(core,day)
    if not event:return planned
    result=dict(planned)
    if event['type']=='festival':result[f'event-guest-{day}']=core.store_events['rules']['festival_customer_tick']
    elif event['type']=='rain':
        normal=[key for key in result if key.startswith('guest-')]
        if normal:result.pop(max(normal,key=lambda key:int(key.split('-')[1])))
    return result


def extra_cost(core,day=None):
    event=row(core,day)
    return core.store_events['rules']['trouble_cost'] if event and event['type']=='trouble' else 0


def item_rewards(core):
    if core.store_events is None:return {}
    return {f"store-event-{r['day']}":dict(item=copy.deepcopy(core.store_events['rules']['supply']),available_day=r['day'])
            for r in core.store_events['days'] if r['type']=='supplies'}


def validate(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','days'} or not isinstance(data['days'],list):raise ValueError('店舗イベント記録が不正です。')
    selected=rules(data['rules']);expected=list(range(1,core.day+1))
    if [r.get('day') for r in data['days']]!=expected:raise ValueError('店舗イベントの日付が不正です。')
    for r in data['days']:
        value=draw(core.seed,r['day'],'occur');kind=None
        if value<selected['probability']:kind=TYPES[int(draw(core.seed,r['day'],'type')*len(TYPES))]
        if set(r)!={'day','type','draw'} or r['type']!=kind or r['draw']!=value:raise ValueError('店舗イベントの抽選記録が不正です。')
    core.store_events=copy.deepcopy(data);return core.store_events
