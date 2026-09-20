"""健康とは独立した活動状態と、派遣帰還イベントの確定記録。"""
import copy
import json
import math
from pathlib import Path

ACTIVITY_LABELS = {'cafe':'在店', 'dispatched':'派遣中', 'missing':'行方不明', 'adopted':'譲渡済み'}


def destination(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_dispatch.json').read_text())
    if not isinstance(data, dict) or set(data) != {'id','name','days','reward','max_fatigue'}:
        raise ValueError('派遣先の設定が不正です。')
    if any(not isinstance(data[k], str) or not data[k].strip() for k in ('id','name')):
        raise ValueError('派遣先の名前が不正です。')
    if type(data['days']) is not int or data['days'] < 1:
        raise ValueError('派遣日数が不正です。')
    if any(type(data[k]) not in (int,float) or not math.isfinite(data[k]) or data[k] < 0 for k in ('reward','max_fatigue')):
        raise ValueError('派遣先の条件・報酬が不正です。')
    return copy.deepcopy(data)


def activity(core, cat_id):
    return core.activities['cats'][cat_id] if core.activities else 'cafe'


def waiting_events(core):
    return [event for event in core.activities['events'].values() if event['status'] == 'waiting'] if core.activities else []


def income(core):
    return sum(e['destination']['reward'] for e in core.activities['events'].values() if e['status']=='resolved') if core.activities else 0


def dispatch(core, cat_id, rules=None):
    core.require_events_resolved()
    rules = destination(rules)
    if not core.compact or not core.can_set_shifts or waiting_events(core) or not core.shift_rules or not core.health_rules:
        raise ValueError('派遣は出勤・病気ルールが有効な営業準備中に選んでください。')
    if cat_id not in core.cats:
        raise ValueError('参加している猫を選んでください。')
    cat = core.cats[cat_id]
    if activity(core,cat_id) != 'cafe' or cat.health_status != 'healthy' or cat.cannot_continue or cat.stamina <= 0 or cat.fatigue > rules['max_fatigue']:
        raise ValueError('この猫は派遣先の条件を満たしていません。')
    available = [c for c in core.cats.values() if activity(core,c.id)=='cafe' and c.health_status=='healthy' and not c.cannot_continue and c.stamina>0]
    if len(available) <= len(getattr(core,'seats',{core.seat.id:core.seat})):
        raise ValueError('席数を超える担当可能な猫がいる場合に派遣できます。')
    event_id = f'dispatch-{core.day}-{cat_id}'
    if core.activities and event_id in core.activities['events']:
        raise ValueError('この猫は本日すでに派遣されています。')
    if core.activities is None:
        core.activities = dict(cats=dict.fromkeys(core.cats,'cafe'), events={}, day_locations=dict.fromkeys(core.cats,'cafe'))
    core.activities['cats'][cat_id] = 'dispatched'
    core.activities['day_locations'][cat_id] = 'dispatched'
    core.working_cats.discard(cat_id)
    core.activities['events'][event_id] = dict(id=event_id, kind='dispatch_return',cat_id=cat_id,
        destination=rules, started_day=core.day, remaining=rules['days'], status='travelling', occurred_day=None, resolved_day=None, choice=None)
    core._tick_events=[]
    core._emit('dispatch_started', event_id=event_id, cat_id=cat_id, destination=rules['name'])
    core._record(dict(kind='dispatch',cat_id=cat_id,rules=rules))


def close_day(core):
    if not core.activities:return
    for event in core.activities['events'].values():
        if event['status'] != 'travelling':continue
        event['remaining'] -= 1
        if event['remaining'] == 0:
            event.update(status='waiting', occurred_day=core.day)
            core._emit('activity_event_waiting',event_id=event['id'],cat_id=event['cat_id'])


def resolve(core, event_id, choice):
    if not core.activities or event_id not in core.activities['events'] or choice != 'receive':
        raise ValueError('イベントと選択肢を確認してください。')
    event=core.activities['events'][event_id]
    if event['status']=='resolved':return
    if event['status']!='waiting':raise ValueError('この派遣はまだ帰還していません。')
    event.update(status='resolved',resolved_day=core.day,choice=choice)
    core.activities['cats'][event['cat_id']]='cafe'
    if core.can_set_shifts:
        core.activities['day_locations'][event['cat_id']]='cafe'
    core.funds += event['destination']['reward']
    core._tick_events=[]
    core._emit('activity_event_resolved',event_id=event_id,cat_id=event['cat_id'],reward=event['destination']['reward'])
    core._record(dict(kind='resolve_activity',event_id=event_id,choice=choice))


def validate(core, data):
    if not isinstance(data,dict) or set(data)!={'cats','events','day_locations'}:
        raise ValueError('活動状態が不正です。')
    for key in ('cats','day_locations'):
        if set(data[key])!=set(core.cats) or any(v not in ACTIVITY_LABELS for v in data[key].values()):
            raise ValueError('猫の活動状態が不正です。')
    busy=set()
    for key,e in data['events'].items():
        if set(e)!={'id','kind','cat_id','destination','started_day','remaining','status','occurred_day','resolved_day','choice'}:
            raise ValueError('イベントの記録が不正です。')
        rule=destination(e['destination'])
        if e['cat_id'] not in core.cats or e['kind']!='dispatch_return' or e['id']!=key or key!=f"dispatch-{e['started_day']}-{e['cat_id']}":
            raise ValueError('イベントの対象が不正です。')
        if type(e['started_day']) is not int or not 1<=e['started_day']<=core.day or type(e['remaining']) is not int or not 0<=e['remaining']<=rule['days']:
            raise ValueError('イベントの日数が不正です。')
        completed_days=core.day-e['started_day']+int(core.closed)
        if e['remaining']!=max(0,rule['days']-completed_days):raise ValueError('派遣の残日数が不正です。')
        if e['status']=='travelling':
            if e['remaining']==0 or any(e[k] is not None for k in ('occurred_day','resolved_day','choice')):raise ValueError('進行中イベントが不正です。')
        elif e['status'] in ('waiting','resolved'):
            if e['remaining']!=0 or type(e['occurred_day']) is not int or e['occurred_day']!=e['started_day']+rule['days']-1:raise ValueError('帰還イベントが不正です。')
            if e['status']=='waiting' and (e['resolved_day'] is not None or e['choice'] is not None):raise ValueError('未解決イベントが不正です。')
            if e['status']=='resolved' and (type(e['resolved_day']) is not int or not e['occurred_day']<=e['resolved_day']<=core.day or e['choice']!='receive'):raise ValueError('解決済みイベントが不正です。')
        else:raise ValueError('未知のイベント状態です。')
        if e['status']!='resolved':
            if e['cat_id'] in busy or data['cats'][e['cat_id']]!='dispatched':raise ValueError('派遣が重複しています。')
            busy.add(e['cat_id'])
    if busy!={key for key,value in data['cats'].items() if value=='dispatched'}:raise ValueError('派遣状態とイベントが一致しません。')
    if any(data['cats'][key]!='cafe' for key in core.working_cats):raise ValueError('不在の猫に出勤予定があります。')
    return copy.deepcopy(data)
