"""接客終了時の譲渡申し出と、選択結果を一度だけ適用する処理。"""
import copy
import math

THRESHOLD = 80


def enabled(core):
    return bool(core.adoption and core.adoption['enabled'])


def waiting(core):
    return [e for e in core.adoption['events'].values() if e['status'] == 'waiting'] if core.adoption else []


def configure(core, value):
    if type(value) is not bool:
        raise ValueError('譲渡イベントはON/OFFで指定してください。')
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts:
        raise ValueError('譲渡イベントの設定は営業準備中に変更してください。')
    if core.adoption is None:
        core.adoption = dict(enabled=value, events={})
    else:
        core.adoption['enabled'] = value
    core._tick_events = []
    core._emit('adoption_configured', enabled=value)
    core._record(dict(kind='configure_adoption', enabled=value))


def consider(core, result):
    if not enabled(core) or core.activity(result['cat_id']) != 'cafe':
        return
    from .cafe_player import state
    cat_id = result['cat_id']
    guest_affinity = result['affinity_after']
    player_affinity = state(core)['affinity'][cat_id]
    event_id = f'adoption-{core.day}-{cat_id}'
    if guest_affinity < THRESHOLD or guest_affinity <= player_affinity or event_id in core.adoption['events']:
        return
    event = dict(id=event_id, cat_id=cat_id, customer_id=result['customer_id'],
                 source=result['session_id'], day=core.day, tick=core.tick,
                 guest_affinity=guest_affinity, player_affinity=player_affinity,
                 threshold=THRESHOLD, status='waiting', choice=None,
                 resolved_day=None, resolved_tick=None)
    core.adoption['events'][event_id] = event
    core._emit('adoption_offered', event_id=event_id, cat_id=cat_id, customer_id=result['customer_id'])


def resolve(core, event_id, choice):
    core.require_running()
    if (not core.adoption or event_id not in core.adoption['events']
            or choice not in ('accept','decline')):
        raise ValueError('譲渡の申し出と選択肢を確認してください。')
    event = core.adoption['events'][event_id]
    if event['status'] == 'resolved':
        if event['choice'] != choice:
            raise ValueError('解決済みの申し出の選択は変更できません。')
        return
    cat_id = event['cat_id']
    from .cafe_player import active
    if (core.activity(cat_id) != 'cafe' or active(core)
            or any(i.cat_id == cat_id for i in getattr(core, 'interactions', {}).values())
            or (core.active and core.active.cat_id == cat_id)):
        raise ValueError('この猫の譲渡は現在確定できません。')
    if choice == 'accept':
        from .cafe_activities import ensure
        ensure(core)
        core.activities['cats'][cat_id] = 'adopted'
        core.activities['day_locations'][cat_id] = 'adopted'
        core.working_cats.discard(cat_id)
    event.update(status='resolved', choice=choice, resolved_day=core.day, resolved_tick=core.tick)
    core._tick_events = []
    core._emit('adoption_resolved', event_id=event_id, cat_id=cat_id,
               customer_id=event['customer_id'], choice=choice)
    core._record(dict(kind='resolve_adoption', event_id=event_id, choice=choice))


def validate(core, data):
    from .cafe_checkpoint import outcome_result
    if (not isinstance(data, dict) or set(data) != {'enabled','events'}
            or type(data['enabled']) is not bool or not isinstance(data['events'], dict)):
        raise ValueError('譲渡イベントの設定が不正です。')
    adopted = set()
    fields = {'id','cat_id','customer_id','source','day','tick','guest_affinity','player_affinity',
              'threshold','status','choice','resolved_day','resolved_tick'}
    for key, event in data['events'].items():
        if not isinstance(event, dict) or set(event) != fields:
            raise ValueError('譲渡イベントの記録が不正です。')
        if (event['cat_id'] not in core.cats or event['source'] not in core.outcomes
                or type(event['day']) is not int or not 1 <= event['day'] <= core.day
                or type(event['tick']) is not int or not 0 <= event['tick'] < core.config.opening_ticks
                or event['id'] != key or key != f"adoption-{event['day']}-{event['cat_id']}"):
            raise ValueError('譲渡の対象・発生時点が不正です。')
        result = outcome_result(core.outcomes[event['source']])
        if (result['cat_id'] != event['cat_id'] or result['customer_id'] != event['customer_id']
                or result['affinity_after'] != event['guest_affinity']):
            raise ValueError('譲渡の申し出と接客成果が一致しません。')
        for field in ('guest_affinity','player_affinity','threshold'):
            value = event[field]
            if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError('譲渡判定の好感度が不正です。')
        if event['threshold'] != THRESHOLD or event['guest_affinity'] < event['threshold'] or event['guest_affinity'] <= event['player_affinity']:
            raise ValueError('譲渡の発生条件が不正です。')
        cat_id = event['cat_id']
        if event['day'] == core.day and event['tick'] > core.tick:
            raise ValueError('譲渡の発生時点が未来です。')
        if event['status'] == 'waiting':
            if (event['choice'] is not None or event['resolved_day'] is not None or event['resolved_tick'] is not None
                    or not data['enabled'] or event['day'] != core.day or core.activity(cat_id) != 'cafe'):
                raise ValueError('未解決の譲渡イベントが不正です。')
        elif event['status'] == 'resolved':
            if (event['choice'] not in ('accept','decline')
                    or type(event['resolved_day']) is not int or event['resolved_day'] != event['day']
                    or type(event['resolved_tick']) is not int
                    or not event['tick'] <= event['resolved_tick'] <= core.config.opening_ticks
                    or (event['day'] == core.day and event['resolved_tick'] > core.tick)):
                raise ValueError('譲渡イベントの解決時点が不正です。')
            if event['choice'] == 'accept':
                if (cat_id in adopted or core.activity(cat_id) != 'adopted'
                        or core.activities['day_locations'][cat_id] != 'adopted'):
                    raise ValueError('譲渡済みの活動状態が不正です。')
                adopted.add(cat_id)
        else:
            raise ValueError('譲渡イベントの状態が不正です。')
    if adopted != {key for key in core.cats if core.activity(key) == 'adopted'}:
        raise ValueError('譲渡記録と猫の活動状態が一致しません。')
    return copy.deepcopy(data)
