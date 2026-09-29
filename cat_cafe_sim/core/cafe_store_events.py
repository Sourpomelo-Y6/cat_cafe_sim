"""営業前に確定し、その日の来店・費用・所持品へ反映する店舗イベント。"""
import copy
import hashlib
import json
import math
from pathlib import Path

TYPES=('festival','rain','supplies','trouble')
SUPPORT_FIELDS={'support_full_cost','support_full_popularity','support_small_cost','support_small_popularity'}
LABELS={'festival':'地域のお祭り','rain':'雨の日','supplies':'支援物資','trouble':'設備トラブル','support':'保護団体からの支援依頼'}
CHOICE_LABELS={'repair':'修理','patch':'応急処置','close':'休業','full':'支援','small':'少額支援','decline':'見送り'}


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_store_events.json').read_text())
    legacy=isinstance(data,dict) and set(data)=={'probability','festival_customer_tick','trouble_cost','supply'}
    base={'probability','festival_customer_tick','trouble_cost','supply'}
    if (not isinstance(data,dict) or set(data) not in (base,base|{'trouble_seat_loss'},base|{'trouble_seat_loss'}|SUPPORT_FIELDS)
            or type(data['probability']) not in (int,float) or not math.isfinite(data['probability']) or not 0<=data['probability']<=1
            or type(data['festival_customer_tick']) is not int or data['festival_customer_tick']<0
            or type(data['trouble_cost']) not in (int,float) or not math.isfinite(data['trouble_cost']) or data['trouble_cost']<=0
            or (not legacy and (type(data['trouble_seat_loss']) is not int or data['trouble_seat_loss']<1))
            or (SUPPORT_FIELDS<=set(data) and any(type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0 for key in SUPPORT_FIELDS))):
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


def event_types(selected):
    return TYPES+(('support',) if SUPPORT_FIELDS<=set(selected) else ())


def present(core):
    data=core.store_events
    if data is None or any(row['day']==core.day for row in data['days']):return
    value=draw(core.seed,core.day,'occur');kind=None
    if value<data['rules']['probability']:
        choices=event_types(data['rules']);kind=choices[int(draw(core.seed,core.day,'type')*len(choices))]
    row=dict(day=core.day,type=kind,draw=value)
    if kind=='trouble' and 'trouble_seat_loss' in data['rules']:
        row.update(status='waiting',choice=None)
    elif kind=='support':
        row.update(status='waiting',choice=None,cost=0,popularity=0)
    data['days'].append(row)
    core._emit('store_event_presented',event_type=kind,label=LABELS.get(kind,'イベントなし'))


def row(core,day=None):
    day=core.day if day is None else day
    return next((r for r in (core.store_events or {}).get('days',[]) if r['day']==day),None)


def label(event):
    base=LABELS.get(event['type'],'イベントなし')
    return base+(f"（{CHOICE_LABELS[event['choice']]}）" if event.get('choice') else '')


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
    return (core.store_events['rules']['trouble_cost'] if event and event['type']=='trouble'
            and ('status' not in event or event['choice']=='repair') else 0)


def waiting(core):
    event=row(core)
    return event if event and event['type'] in ('trouble','support') and event.get('status')=='waiting' else None


def resolve(core,choice):
    core.require_running();event=waiting(core)
    allowed=('repair','patch') if event and event['type']=='trouble' else ('full','small','decline')
    if event is None or choice not in allowed or not core.can_set_shifts:
        raise ValueError('店舗イベントの対応と営業状態を確認してください。')
    cost=popularity=0
    if event['type']=='support' and choice!='decline':
        prefix='support_full' if choice=='full' else 'support_small'
        cost=core.store_events['rules'][prefix+'_cost'];popularity=core.store_events['rules'][prefix+'_popularity']
        core.funds-=cost
        from .cafe_management import check_end
        check_end(core)
    event.update(status='resolved',choice=choice,**({'cost':cost,'popularity':popularity} if event['type']=='support' else {}))
    core._tick_events=[];core._emit('store_event_resolved',event_type=event['type'],choice=choice,cost=cost,popularity=popularity)
    core._record(dict(kind='resolve_store_event',choice=choice))


def close_for_day(core):
    event=waiting(core)
    if event is None or event['type']!='trouble':return False
    event.update(status='resolved',choice='close')
    return True


def disabled_seats(core,day=None):
    event=row(core,day)
    if not event or event.get('choice')!='patch' or not hasattr(core,'seats'):return set()
    count=core.store_events['rules']['trouble_seat_loss']
    return set(list(core.seats)[-count:])


def item_rewards(core):
    if core.store_events is None:return {}
    return {f"store-event-{r['day']}":dict(item=copy.deepcopy(core.store_events['rules']['supply']),available_day=r['day'])
            for r in core.store_events['days'] if r['type']=='supplies'}


def expenses(core,day=None):
    return sum(r.get('cost',0) for r in (core.store_events or {}).get('days',[]) if day is None or r['day']==day)


def popularity_bonus(core,day=None):
    return sum(r.get('popularity',0) for r in (core.store_events or {}).get('days',[]) if day is None or r['day']==day)


def validate(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','days'} or not isinstance(data['days'],list):raise ValueError('店舗イベント記録が不正です。')
    selected=rules(data['rules']);expected=list(range(1,core.day+1))
    if [r.get('day') for r in data['days']]!=expected:raise ValueError('店舗イベントの日付が不正です。')
    for r in data['days']:
        value=draw(core.seed,r['day'],'occur');kind=None
        choices=event_types(selected)
        if value<selected['probability']:kind=choices[int(draw(core.seed,r['day'],'type')*len(choices))]
        fields={'day','type','draw'}
        if kind=='trouble' and 'trouble_seat_loss' in selected:
            fields|={'status','choice'}
            if r.get('status') not in ('waiting','resolved') or (r.get('status')=='waiting')!=(r.get('choice') is None) or r.get('choice') not in (None,'repair','patch','close'):
                raise ValueError('設備トラブルの対応記録が不正です。')
            if r.get('status')=='waiting' and (r['day']!=core.day or not core.can_set_shifts):raise ValueError('設備トラブルへの回答が保留されたままです。')
        elif kind=='support':
            fields|={'status','choice','cost','popularity'}
            choice=r.get('choice');expected=(0,0)
            if choice in ('full','small'):
                prefix='support_full' if choice=='full' else 'support_small';expected=(selected[prefix+'_cost'],selected[prefix+'_popularity'])
            if (r.get('status') not in ('waiting','resolved') or (r.get('status')=='waiting')!=(choice is None)
                    or choice not in (None,'full','small','decline') or (r.get('cost'),r.get('popularity'))!=expected
                    or (r.get('status')=='waiting' and (r['day']!=core.day or not core.can_set_shifts))):
                raise ValueError('支援依頼の回答記録が不正です。')
        if set(r)!=fields or r['type']!=kind or r['draw']!=value:raise ValueError('店舗イベントの抽選記録が不正です。')
    core.store_events=copy.deepcopy(data);return core.store_events
