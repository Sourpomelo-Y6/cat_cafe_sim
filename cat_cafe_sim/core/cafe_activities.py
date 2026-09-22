"""健康とは独立した活動状態と、派遣帰還イベントの確定記録。"""
import copy
import json
import math
from pathlib import Path

ACTIVITY_LABELS = {'cafe':'在店', 'dispatched':'派遣中', 'missing':'行方不明', 'adopted':'譲渡済み'}


def destination(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_dispatch.json').read_text())
    if not isinstance(data, dict) or set(data) not in ({'id','name','days','reward','max_fatigue'}, {'id','name','days','reward','max_fatigue','required_trait','required_trait_name'}):
        raise ValueError('派遣先の設定が不正です。')
    if any(not isinstance(data[k], str) or not data[k].strip() for k in ('id','name')):
        raise ValueError('派遣先の名前が不正です。')
    if type(data['days']) is not int or data['days'] < 1:
        raise ValueError('派遣日数が不正です。')
    if any(type(data[k]) not in (int,float) or not math.isfinite(data[k]) or data[k] < 0 for k in ('reward','max_fatigue')):
        raise ValueError('派遣先の条件・報酬が不正です。')
    if 'required_trait' in data and any(not isinstance(data[k], str) or not data[k].strip() for k in ('required_trait', 'required_trait_name')):
        raise ValueError('派遣に必要な特性が不正です。')
    return copy.deepcopy(data)


def destinations():
    extra = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_dispatch_destinations.json').read_text(encoding='utf-8'))
    if not isinstance(extra, list):
        raise ValueError('派遣先一覧が不正です。')
    rows = [destination()] + [destination(row) for row in extra]
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('派遣先IDが重複しています。')
    return rows


def dispatch_reason(core, cat_id, rules):
    """表示と出発処理で共用する参加条件。状態は変更しない。"""
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts or waiting_events(core) or not core.shift_rules or not core.health_rules:
        return '出勤・病気ルールが有効な営業準備中に出発できます。'
    if cat_id not in core.cats:
        return '参加している猫を選んでください。'
    from .cafe_patron import DESTINATION_ID
    if rules['id'] == DESTINATION_ID and (not core.patron or rules != core.patron['rules']['destination']):
        return '先に有力者目標を開始してください。派遣条件は開始時の設定を使います。'
    cat = core.cats[cat_id]
    if activity(core, cat_id) != 'cafe':
        return '在店していません。'
    if cat.health_status != 'healthy':
        return '健康な猫が対象です。'
    if cat.cannot_continue or cat.stamina <= 0:
        return '接客を担当できる体力・状態が必要です。'
    if cat.fatigue > rules['max_fatigue']:
        return f"疲労{rules['max_fatigue']:g}以下が必要です。"
    from .cafe_traits import trait
    if 'required_trait' in rules and (trait(core, cat_id) or {}).get('id') != rules['required_trait']:
        return f"特性「{rules['required_trait_name']}」が必要です。"
    available = [c for c in core.cats.values() if activity(core,c.id)=='cafe' and c.health_status=='healthy' and not c.cannot_continue and c.stamina>0]
    if len(available) <= len(getattr(core,'seats',{core.seat.id:core.seat})):
        return '店内の席数を超える担当可能な猫が必要です。'
    if core.activities and f'dispatch-{core.day}-{cat_id}' in core.activities['events']:
        return 'この猫は本日すでに派遣されています。'
    return ''


def activity(core, cat_id):
    return core.activities['cats'][cat_id] if core.activities else 'cafe'


def waiting_events(core):
    from .cafe_adoption import waiting
    from .cafe_management import waiting as returns
    from .cafe_dispatch_encounters import waiting as choices
    return choices(core) + ([event for event in core.activities['events'].values() if event['status'] == 'waiting'] if core.activities else []) + waiting(core) + returns(core)


def reward(core, event):
    from .cafe_traits import dispatch_terms
    from .cafe_dispatch_encounters import reward_delta
    return max(0,dispatch_terms(core,event['cat_id'],event['destination']['reward'])['reward']+reward_delta(event))


def income(core):
    return sum(reward(core,e) for e in core.activities['events'].values() if e['status']=='resolved') if core.activities else 0


def ensure(core):
    if core.activities is None:
        core.activities = dict(cats=dict.fromkeys(core.cats,'cafe'), events={}, day_locations=dict.fromkeys(core.cats,'cafe'))


def dispatch(core, cat_id, rules=None, *, encounter=None, item_reward=None):
    rules = destination(rules)
    reason = dispatch_reason(core, cat_id, rules)
    if reason:
        raise ValueError(reason)
    event_id = f'dispatch-{core.day}-{cat_id}'
    from .cafe_traits import dispatch_terms
    dispatch_terms(core,cat_id,rules['reward'])
    event = dict(id=event_id, kind='dispatch_return',cat_id=cat_id,
        destination=rules, started_day=core.day, remaining=rules['days'], status='travelling', occurred_day=None, resolved_day=None, choice=None)
    from .cafe_dispatch_encounters import attach
    attach(event, encounter)
    if item_reward is not None:
        from .cafe_items import definition
        event['item_reward'] = definition(item_reward)
    ensure(core)
    core.activities['cats'][cat_id] = 'dispatched'
    core.activities['day_locations'][cat_id] = 'dispatched'
    core.working_cats.discard(cat_id)
    core.activities['events'][event_id] = event
    core._tick_events=[]
    core._emit('dispatch_started', event_id=event_id, cat_id=cat_id, destination=rules['name'])
    core._record(dict(kind='dispatch',cat_id=cat_id,rules=rules, **({'encounter':copy.deepcopy(event['encounter']['rules'])} if encounter is not None else {}),
                      **({'item_reward':copy.deepcopy(event['item_reward'])} if item_reward is not None else {})))


def close_day(core):
    if not core.activities:return
    for event in core.activities['events'].values():
        if event['status'] != 'travelling':continue
        event['remaining'] -= 1
        from .cafe_dispatch_encounters import close_day as encounter_close
        encounter_close(core,event)
        if event['remaining'] == 0:
            event.update(status='waiting', occurred_day=core.day)
            core._emit('activity_event_waiting',event_id=event['id'],cat_id=event['cat_id'])


def resolve(core, event_id, choice):
    core.require_running()
    if not core.activities or event_id not in core.activities['events'] or choice != 'receive':
        raise ValueError('イベントと選択肢を確認してください。')
    event=core.activities['events'][event_id]
    if event['status']=='resolved':return
    if event['status']!='waiting':raise ValueError('この派遣はまだ帰還していません。')
    from .cafe_traits import dispatch_terms
    terms=dispatch_terms(core,event['cat_id'],event['destination']['reward'])
    received=reward(core,event)
    if not math.isfinite(core.funds+received):
        raise ValueError('派遣報酬と所持金の合計が大きすぎます。')
    event.update(status='resolved',resolved_day=core.day,choice=choice)
    core.activities['cats'][event['cat_id']]='cafe'
    if core.can_set_shifts:
        core.activities['day_locations'][event['cat_id']]='cafe'
    core.funds += received
    if core.management:
        key=event['cat_id']
        core.management['stress'][key]=min(100,core.management['stress'][key]+terms['stress'])
    core._tick_events=[]
    core._emit('activity_event_resolved',event_id=event_id,cat_id=event['cat_id'],reward=received,
               **({'stress_gain':terms['stress']} if terms['stress'] else {}),
               **({'item_reward':copy.deepcopy(event['item_reward'])} if 'item_reward' in event else {}))
    from .cafe_patron import receive
    receive(core, event)
    core._record(dict(kind='resolve_activity',event_id=event_id,choice=choice))


def validate(core, data):
    if not isinstance(data,dict) or set(data)!={'cats','events','day_locations'}:
        raise ValueError('活動状態が不正です。')
    for key in ('cats','day_locations'):
        if set(data[key])!=set(core.cats) or any(v not in ACTIVITY_LABELS for v in data[key].values()):
            raise ValueError('猫の活動状態が不正です。')
    busy=set()
    for key,e in data['events'].items():
        if set(e)-{'encounter','item_reward'}!={'id','kind','cat_id','destination','started_day','remaining','status','occurred_day','resolved_day','choice'}:
            raise ValueError('イベントの記録が不正です。')
        if 'item_reward' in e:
            from .cafe_items import definition
            definition(e['item_reward'])
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
        from .cafe_dispatch_encounters import validate as validate_encounter
        validate_encounter(core,e)
        if e['status']!='resolved':
            if e['cat_id'] in busy or data['cats'][e['cat_id']]!='dispatched':raise ValueError('派遣が重複しています。')
            busy.add(e['cat_id'])
    if busy!={key for key,value in data['cats'].items() if value=='dispatched'}:raise ValueError('派遣状態とイベントが一致しません。')
    if any(data['cats'][key]!='cafe' for key in core.working_cats):raise ValueError('不在の猫に出勤予定があります。')
    return copy.deepcopy(data)
