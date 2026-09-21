"""ストレス、家出・帰還、引き渡し費用と経営終了。ルール未導入の営業は変更しない。"""
import copy
import hashlib
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_management.json').read_text())
    fields = {'starting_funds','starting_popularity','stress_per_service_tick','rest_recovery',
              'player_relief','player_stress','runaway_threshold','popularity_loss','missing_days',
              'return_stress','kitten_probability','kitten_cost'}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError('経営ルールの設定が不正です。')
    for value in data.values():
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError('経営ルールの数値が不正です。')
    if (data['starting_funds'] <= 0 or not 0 < data['starting_popularity'] <= 100
            or not 0 < data['runaway_threshold'] <= 100 or data['return_stress'] >= data['runaway_threshold']
            or data['popularity_loss'] <= 0 or data['kitten_probability'] > 1
            or type(data['missing_days']) is not int or data['missing_days'] < 1):
        raise ValueError('経営ルールの範囲が不正です。')
    return copy.deepcopy(data)


def is_over(core):
    return bool(core.management and core.management['game_over'])


def require_running(core):
    if is_over(core):
        raise ValueError('ゲームオーバーです。結果の閲覧・保存のみ行えます。')


def waiting(core):
    return [e for e in core.management['events'].values() if e['status']=='waiting'] if core.management else []


def enable(core, selected=None):
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts or core.management or not core.health_rules:
        raise ValueError('経営ルールは病気ルールが有効な準備中に1回だけ開始できます。')
    selected = rules(selected)
    grant = max(0, selected['starting_funds']-core.funds)
    core.management = dict(rules=selected, started_day=core.day, grant=grant,
                           stress=dict.fromkeys(core.cats,0), popularity=selected['starting_popularity'],
                           events={}, game_over=None)
    core.funds += grant
    core._tick_events = []
    core._emit('management_enabled', grant=grant)
    core._record(dict(kind='enable_management', rules=selected))


def kitten_draw(seed, event_id):
    value = hashlib.sha256(f'missing-kitten:{seed}:{event_id}'.encode()).digest()
    return int.from_bytes(value[:8],'big') / 2**64


def check_end(core):
    data = core.management
    if not data or data['game_over']:
        return
    reason = 'funds' if core.funds <= 0 else 'popularity' if data['popularity'] <= 0 else None
    if reason:
        data['game_over'] = dict(reason=reason, day=core.day)
        core._emit('game_over', reason=reason, day=core.day)


def player_result(core, result):
    if not core.management:
        return
    data = core.management
    change = (-data['rules']['player_relief'] if result['affinity_pending'] > 0 else
              data['rules']['player_stress'] if result['affinity_pending'] < 0 else 0)
    key = result['cat_id']
    data['stress'][key] = max(0, min(100, data['stress'][key]+change))


def close_day(core):
    data = core.management
    if not data:
        return
    rule = data['rules']
    from .cafe_goal import earn
    earn(core)
    # Existing absences progress first; a cat leaving today does not consume a missing day.
    for event in data['events'].values():
        if event['status']=='missing':
            event['remaining'] -= 1
            if event['remaining']==0:
                event['status']='waiting'
                core._emit('missing_return_waiting', event_id=event['id'], cat_id=event['cat_id'])
    from .cafe_adoption import waiting as adoption_waiting
    reserved = {e['cat_id'] for e in adoption_waiting(core)}
    for key in core.cats:
        if core.activity(key) != 'cafe':
            continue
        service = core.cat_service_ticks[key]
        from .cafe_traits import effect
        change = (service*rule['stress_per_service_tick']*effect(core,key,'service_stress') if key in core.working_cats else -rule['rest_recovery'])
        data['stress'][key] = max(0,min(100,data['stress'][key]+change))
        if service == 0 or data['stress'][key] < rule['runaway_threshold'] or key in reserved:
            continue
        from .cafe_activities import ensure
        ensure(core)
        core.activities['cats'][key]='missing'
        core.activities['day_locations'][key]='missing'
        core.working_cats.discard(key)
        event_id=f'missing-{core.day}-{key}'
        draw=kitten_draw(core.seed,event_id)
        data['events'][event_id]=dict(id=event_id,cat_id=key,departed_day=core.day,
            remaining=rule['missing_days'],status='missing',kitten_draw=draw,
            kitten=draw < rule['kitten_probability'],resolved_day=None,cost=0)
        data['popularity']=max(0,data['popularity']-rule['popularity_loss'])
        core._emit('cat_missing',event_id=event_id,cat_id=key,popularity=data['popularity'])
    check_end(core)


def resolve(core, event_id):
    require_running(core)
    data=core.management
    if not data or event_id not in data['events']:
        raise ValueError('帰還イベントを選んでください。')
    event=data['events'][event_id]
    if event['status']=='resolved':
        return
    if event['status']!='waiting' or core.activity(event['cat_id'])!='missing':
        raise ValueError('この猫はまだ帰還していません。')
    cat=core.cats[event['cat_id']]
    cost=data['rules']['kitten_cost'] if event['kitten'] else 0
    event.update(status='resolved',resolved_day=core.day,cost=cost)
    core.activities['cats'][cat.id]='cafe'
    if core.can_set_shifts:
        core.activities['day_locations'][cat.id]='cafe'
    cat.stamina=core.config.max_stamina
    cat.cannot_continue=cat.health_status!='healthy'
    data['stress'][cat.id]=data['rules']['return_stress']
    core.funds -= cost
    core._tick_events=[]
    core._emit('missing_returned',event_id=event_id,cat_id=cat.id,kitten=event['kitten'],cost=cost)
    check_end(core)
    core._record(dict(kind='resolve_missing',event_id=event_id))


def money_adjustment(core):
    if not core.management:
        return 0
    return core.management['grant']-sum(e['cost'] for e in core.management['events'].values())


def validate(core, data):
    fields={'rules','started_day','grant','stress','popularity','events','game_over'}
    if not isinstance(data,dict) or set(data)!=fields:
        raise ValueError('経営状態が不正です。')
    rule=rules(data['rules'])
    if type(data['started_day']) is not int or not 1<=data['started_day']<=core.day:
        raise ValueError('経営ルールの開始日が不正です。')
    if (type(data['grant']) not in (int,float) or not math.isfinite(data['grant'])
            or not 0<=data['grant']<=rule['starting_funds']):
        raise ValueError('開始時資金の記録が不正です。')
    if not isinstance(data['stress'],dict) or set(data['stress'])!=set(core.cats):
        raise ValueError('ストレスの対象猫が不正です。')
    for value in list(data['stress'].values()):
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100:
            raise ValueError('ストレス・人気の値が不正です。')
    if type(data['popularity']) not in (int,float) or not math.isfinite(data['popularity']) or data['popularity']<0:
        raise ValueError('人気の値が不正です。')
    if not isinstance(data['events'],dict):
        raise ValueError('家出イベントが不正です。')
    missing=set()
    for key,e in data['events'].items():
        if not isinstance(e,dict) or set(e)!={'id','cat_id','departed_day','remaining','status','kitten_draw','kitten','resolved_day','cost'}:
            raise ValueError('家出イベントの項目が不正です。')
        if (e['cat_id'] not in core.cats or type(e['departed_day']) is not int
                or not data['started_day']<=e['departed_day']<=core.day
                or key!=e['id'] or key!=f"missing-{e['departed_day']}-{e['cat_id']}"):
            raise ValueError('家出の対象・日付が不正です。')
        elapsed=core.day-e['departed_day']-int(not core.closed)
        if elapsed < 0 or type(e['remaining']) is not int or e['remaining']!=max(0,rule['missing_days']-elapsed):
            raise ValueError('不在日数が不正です。')
        draw=kitten_draw(core.seed,key)
        if e['kitten_draw']!=draw or type(e['kitten']) is not bool or e['kitten']!=(draw<rule['kitten_probability']):
            raise ValueError('帰還時の抽選記録が不正です。')
        if type(e['cost']) not in (int,float) or not math.isfinite(e['cost']) or e['cost']<0:
            raise ValueError('引き渡し費用が不正です。')
        if e['status'] in ('missing','waiting'):
            if (e['resolved_day'] is not None or e['cost']!=0 or (e['remaining']==0)!=(e['status']=='waiting')
                    or e['cat_id'] in missing or core.activity(e['cat_id'])!='missing'):
                raise ValueError('不在状態と帰還イベントが一致しません。')
            missing.add(e['cat_id'])
        elif e['status']=='resolved':
            return_day=e['departed_day']+rule['missing_days']
            if (e['remaining']!=0 or type(e['resolved_day']) is not int
                    or not return_day<=e['resolved_day']<=core.day
                    or e['cost']!=(rule['kitten_cost'] if e['kitten'] else 0)):
                raise ValueError('帰還の確定記録が不正です。')
        else:
            raise ValueError('帰還イベントの状態が不正です。')
    if missing!={key for key in core.cats if core.activity(key)=='missing'}:
        raise ValueError('行方不明の猫とイベントが一致しません。')
    expected=max(0,rule['starting_popularity']-len(data['events'])*rule['popularity_loss'])
    if core.goal is None and data['popularity']!=expected:
        raise ValueError('人気と家出の記録が一致しません。')
    reason='funds' if core.funds<=0 else 'popularity' if data['popularity']<=0 else None
    end=data['game_over']
    if reason is None and end is not None:
        raise ValueError('終了条件が成立していません。')
    if reason is not None and (not isinstance(end,dict) or set(end)!={'reason','day'}
                              or end['reason']!=reason or type(end['day']) is not int or end['day']!=core.day):
        raise ValueError('終了判定が不正です。')
    return copy.deepcopy(data)
