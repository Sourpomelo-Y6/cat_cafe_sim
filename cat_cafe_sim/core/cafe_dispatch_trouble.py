"""山あいの宿だけで発生する派遣中の家出。抽選条件は出発時に固定する。"""
import copy
import hashlib
import json
import math
from pathlib import Path

DESTINATION_ID = 'mountain_lodge_visit'


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_dispatch_trouble.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'destination', 'base_probability', 'stress_probability', 'missing_days', 'search_cost', 'return_stress'}:
        raise ValueError('派遣トラブルの設定が不正です。')
    from .cafe_activities import destination
    selected = destination(data['destination'])
    if selected['id'] != DESTINATION_ID or selected['days'] < 2:
        raise ValueError('派遣トラブルは山あいの宿専用です。')
    if (type(data['missing_days']) is not int or data['missing_days'] < 1
            or any(type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] < 0
                   for key in ('base_probability', 'stress_probability', 'search_cost', 'return_stress'))
            or data['base_probability'] + data['stress_probability'] > 1 or data['return_stress'] > 100):
        raise ValueError('派遣トラブルの確率・費用・日数が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.dispatch_trouble is not None
            or core.management is None or not core.shift_rules or not core.health_rules):
        raise ValueError('山あいの宿は経営ルールが有効な新規ゲームの準備時に導入してください。')
    core.dispatch_trouble = rules(selected)
    core._tick_events = []
    core._emit('dispatch_trouble_initialized')
    core._record(dict(kind='initialize_dispatch_trouble', rules=copy.deepcopy(core.dispatch_trouble)))


def draw(seed, event_id):
    value = hashlib.sha256(f'dispatch-trouble:{seed}:{event_id}'.encode()).digest()
    return int.from_bytes(value[:8], 'big') / 2**64


def probability(core, cat_id):
    selected = core.dispatch_trouble
    return selected['base_probability'] + selected['stress_probability'] * core.management['stress'][cat_id] / 100


def for_departure(core, cat_id, destination):
    if destination['id'] != DESTINATION_ID:
        return None
    if core.dispatch_trouble is None or destination != core.dispatch_trouble['destination'] or core.management is None:
        raise ValueError('この営業には山あいの宿の派遣設定がありません。')
    return dict(rules=copy.deepcopy(core.dispatch_trouble), stress=core.management['stress'][cat_id],
                probability=probability(core, cat_id), draw=draw(core.seed, f'dispatch-{core.day}-{cat_id}'))


def attach(core, event, data):
    if event['destination']['id'] != DESTINATION_ID:
        if data is not None:
            raise ValueError('この派遣先に家出トラブルは追加できません。')
        return
    expected = for_departure(core, event['cat_id'], event['destination'])
    if data != expected or event.get('encounter') or event.get('introduction') or event.get('item_reward'):
        raise ValueError('山あいの宿の抽選条件・報酬が不正です。')
    event['trouble'] = dict(copy.deepcopy(data), status='scheduled', missing_day=None,
                           choice=None, choice_day=None, cost=0)


def pending(event):
    return event.get('trouble', {}).get('status') == 'waiting'


def waiting(core):
    return [event for event in (core.activities or {}).get('events', {}).values() if pending(event)]


def interrupted(event):
    return event.get('trouble', {}).get('missing_day') is not None


def missing_ids(core):
    return {event['cat_id'] for event in (core.activities or {}).get('events', {}).values()
            if interrupted(event) and event['status'] in ('missing', 'waiting')}


def expenses(core, day=None):
    return sum(event['trouble']['cost'] for event in (core.activities or {}).get('events', {}).values()
               if 'trouble' in event and (day is None or event['trouble']['choice_day'] == day))


def close_day(core, event):
    data = event.get('trouble')
    if data is None:
        return False
    if event['status'] == 'missing':
        if core.day > data['missing_day']:
            event['remaining'] -= 1
            if event['remaining'] == 0:
                event.update(status='waiting', occurred_day=core.day)
                core._emit('activity_event_waiting', event_id=event['id'], cat_id=event['cat_id'])
        return True
    if data['status'] != 'scheduled':
        return False
    if data['draw'] >= data['probability']:
        data['status'] = 'not_triggered'
        return False
    data.update(status='waiting', missing_day=core.day)
    event.update(status='missing', remaining=data['rules']['missing_days'])
    core.activities['cats'][event['cat_id']] = 'missing'
    core.activities['day_locations'][event['cat_id']] = 'missing'
    core._emit('dispatch_trouble_waiting', event_id=event['id'], cat_id=event['cat_id'])
    return True


def resolve(core, event_id, choice):
    core.require_running()
    event = (core.activities or {}).get('events', {}).get(event_id)
    if not event or 'trouble' not in event or choice not in ('search', 'wait'):
        raise ValueError('派遣トラブルと対応を確認してください。')
    data = event['trouble']
    if data['status'] == 'resolved':
        if data['choice'] != choice:
            raise ValueError('回答済みの派遣トラブルは変更できません。')
        return
    if not pending(event) or event['status'] != 'missing' or not (core.closed or core.can_set_shifts):
        raise ValueError('回答待ちの派遣トラブルではありません。')
    cost = data['rules']['search_cost'] if choice == 'search' else 0
    if core.funds <= cost:
        raise ValueError('捜索後に資金が残る必要があります。費用なしの帰還待ちを選べます。')
    data.update(status='resolved', choice=choice, choice_day=core.day, cost=cost)
    core.funds -= cost
    if choice == 'search':
        event.update(status='waiting', remaining=0, occurred_day=core.day)
    core._tick_events = []
    core._emit('dispatch_trouble_resolved', event_id=event_id, cat_id=event['cat_id'], choice=choice, cost=cost)
    core._record(dict(kind='resolve_dispatch_trouble', event_id=event_id, choice=choice))


def validate_event(core, event):
    data = event.get('trouble')
    if data is None:
        if 'trouble' in event or event['destination']['id'] == DESTINATION_ID:
            raise ValueError('山あいの宿の抽選記録がありません。')
        return False
    if (not isinstance(data, dict) or set(data) != {'rules', 'stress', 'probability', 'draw', 'status', 'missing_day', 'choice', 'choice_day', 'cost'}
            or core.dispatch_trouble is None or data['rules'] != core.dispatch_trouble
            or event['destination'] != rules(data['rules'])['destination']
            or type(data['cost']) not in (int, float) or not math.isfinite(data['cost']) or data['cost'] < 0
            or any(key in event for key in ('encounter', 'introduction', 'item_reward'))):
        raise ValueError('派遣トラブルの対象・設定が不正です。')
    selected = data['rules']
    if (type(data['stress']) not in (int, float) or not math.isfinite(data['stress']) or not 0 <= data['stress'] <= 100
            or type(data['probability']) not in (int, float)
            or data['probability'] != selected['base_probability'] + selected['stress_probability'] * data['stress'] / 100
            or type(data['draw']) not in (int, float) or data['draw'] != draw(core.seed, event['id'])):
        raise ValueError('派遣トラブルの抽選記録が不正です。')
    elapsed = core.day - event['started_day'] + int(core.closed)
    if data['status'] in ('scheduled', 'not_triggered'):
        if (any(data[key] is not None for key in ('missing_day', 'choice', 'choice_day')) or data['cost'] != 0
                or (data['status'] == 'scheduled' and elapsed != 0)
                or (data['status'] == 'not_triggered' and (elapsed < 1 or data['draw'] < data['probability']))):
            raise ValueError('未発生の派遣トラブル記録が不正です。')
        return False
    if (data['status'] not in ('waiting', 'resolved') or type(data['missing_day']) is not int
            or data['missing_day'] != event['started_day'] or elapsed < 1 or data['draw'] >= data['probability']):
        raise ValueError('家出トラブルの発生日が不正です。')
    if data['status'] == 'waiting':
        if (elapsed != 1 or event['status'] != 'missing' or any(data[key] is not None for key in ('choice', 'choice_day')) or data['cost'] != 0):
            raise ValueError('トラブルへの回答前に日程が進んでいます。')
    elif (data['choice'] not in ('search', 'wait') or type(data['choice_day']) is not int
            or not event['started_day'] <= data['choice_day'] <= min(core.day, event['started_day'] + 1)
            or type(data['cost']) not in (int, float)
            or data['cost'] != (selected['search_cost'] if data['choice'] == 'search' else 0)):
        raise ValueError('トラブルへの回答・費用が不正です。')
    due = data['choice_day'] if data['choice'] == 'search' else data['missing_day'] + selected['missing_days']
    remaining = 0 if data['choice'] == 'search' else max(0, selected['missing_days'] - (elapsed - 1))
    if event['remaining'] != remaining:
        raise ValueError('トラブル後の帰還日数が不正です。')
    if event['status'] == 'missing':
        if remaining == 0 or any(event[key] is not None for key in ('occurred_day', 'resolved_day', 'choice')):
            raise ValueError('行方不明の派遣記録が不正です。')
    elif event['status'] in ('waiting', 'resolved'):
        if remaining != 0 or type(event['occurred_day']) is not int or event['occurred_day'] != due:
            raise ValueError('トラブル後の帰還記録が不正です。')
        if event['status'] == 'waiting' and (event['resolved_day'] is not None or event['choice'] is not None):
            raise ValueError('未確認の帰還記録が不正です。')
        if event['status'] == 'resolved' and (type(event['resolved_day']) is not int or not due <= event['resolved_day'] <= core.day or event['choice'] != 'receive'):
            raise ValueError('確定した帰還記録が不正です。')
    else:
        raise ValueError('トラブル後の活動状態が不正です。')
    return True


def validate(core):
    if core.dispatch_trouble is not None:
        core.dispatch_trouble = rules(core.dispatch_trouble)
        if core.management is None or not core.shift_rules or not core.health_rules:
            raise ValueError('派遣トラブルには経営・出勤・健康ルールが必要です。')
