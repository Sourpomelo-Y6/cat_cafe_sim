"""派遣帰還で紹介された猫を準備中に迎える。出発時の候補を固定する。"""
import copy
import json
from pathlib import Path

from .cafe_recruitment import validate_candidates
from .human_cat_relationship import identity


def rules(data=None):
    if data is None:
        from .cafe_traits import definitions
        from .human_cat_types import load_presets
        row = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_dispatch_introduction.json').read_text())
        data = dict(destination=row['destination'], candidate=dict(name=row['name'], cost=row['cost'],
                    personality=load_presets()[row['preset']].to_dict(), trait=definitions()[row['trait']],
                    features=row['features']))
    if not isinstance(data, dict) or set(data) != {'destination', 'candidate'}:
        raise ValueError('派遣先の猫紹介設定が不正です。')
    if data['destination'] != 'shopping_street_event':
        raise ValueError('初回の猫紹介は商店街の交流会が対象です。')
    validate_candidates({'introduced-cat': data['candidate']})
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.dispatch_introduction is not None
            or not core.shift_rules or not core.health_rules):
        raise ValueError('派遣先の猫紹介は新規ゲームの準備中に設定してください。')
    core.dispatch_introduction = rules(selected)
    core._tick_events = []
    core._record(dict(kind='initialize_dispatch_introduction', rules=copy.deepcopy(core.dispatch_introduction)))


def introductions(core):
    return [event for event in (core.activities or {}).get('events', {}).values() if 'introduction' in event]


def reserved_ids(core):
    return {event['introduction']['cat_id'] for event in introductions(core)}


def for_departure(core, destination, used_ids):
    selected = core.dispatch_introduction
    if selected is None or selected['destination'] != destination['id']:
        return None
    used = set(used_ids) | reserved_ids(core)
    index = 1
    while f'dispatch-rescue-{index}' in used:
        index += 1
    candidate = copy.deepcopy(selected['candidate'])
    candidate['name'] += f'（派遣紹介{len(introductions(core)) + 1}）'
    return dict(cat_id=f'dispatch-rescue-{index}', candidate=candidate)


def attach(core, event, data):
    if data is None:
        return
    if not isinstance(data, dict) or set(data) != {'cat_id', 'candidate'} or core.dispatch_introduction is None:
        raise ValueError('派遣先の猫紹介候補が不正です。')
    identity(data['cat_id'])
    validate_candidates({data['cat_id']: data['candidate']})
    selected = core.dispatch_introduction
    expected = copy.deepcopy(selected['candidate'])
    expected['name'] += f'（派遣紹介{len(introductions(core)) + 1}）'
    used = set(core.cats) | reserved_ids(core) | set((core.recruitment or {}).get('candidates', {})) | set((core.pet_shop or {}).get('candidates', {}))
    if core.intake_request:
        used.add(core.intake_request['rules']['cat_id'])
    if (event['destination']['id'] != selected['destination'] or data['candidate'] != expected
            or data['cat_id'] in used):
        raise ValueError('派遣先・紹介候補・猫IDが既存状態と一致しません。')
    event['introduction'] = dict(copy.deepcopy(data), status='scheduled', presented_day=None, resolved_day=None)


def waiting(core):
    return [event for event in introductions(core) if event['introduction']['status'] == 'waiting']


def present(core):
    from .cafe_management import is_over
    if not core.can_set_shifts or is_over(core):
        return
    for event in introductions(core):
        data = event['introduction']
        if event['status'] == 'resolved' and data['status'] == 'scheduled':
            data.update(status='waiting', presented_day=core.day)
            core._emit('dispatch_introduction_waiting', event_id=event['id'], name=data['candidate']['name'])


def response_reason(core, event_id):
    try:
        # A daily intake request may coexist; each can be answered independently.
        core.require_events_resolved(ignore_intake=True, ignore_introductions=True)
    except ValueError as exc:
        return str(exc)
    event = (core.activities or {}).get('events', {}).get(event_id)
    if (not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules
            or not event or event.get('introduction', {}).get('status') != 'waiting'):
        return '回答待ちの猫紹介を営業準備中に確認してください。'
    return ''


def admission_reason(core, event_id):
    problem = response_reason(core, event_id)
    if problem:
        return problem
    from .cafe_housing import admission_reason as housing_reason
    problem = housing_reason(core)
    if problem:
        return problem
    if core.funds <= core.activities['events'][event_id]['introduction']['candidate']['cost']:
        return '受け入れ後に資金が残る必要があります。'
    return ''


def resolve(core, event_id, choice):
    core.require_running()
    event = (core.activities or {}).get('events', {}).get(event_id)
    if not event or 'introduction' not in event or choice not in ('accept', 'decline'):
        raise ValueError('猫紹介と迎える／見送るの選択を確認してください。')
    data = event['introduction']
    status = 'accepted' if choice == 'accept' else 'declined'
    if data['status'] in ('accepted', 'declined'):
        if data['status'] != status:
            raise ValueError('回答済みの猫紹介は変更できません。')
        return
    problem = admission_reason(core, event_id) if choice == 'accept' else response_reason(core, event_id)
    if problem:
        raise ValueError(problem)
    if choice == 'accept':
        from .cafe_recruitment import join_cat
        join_cat(core, data['cat_id'], data['candidate'])
    data.update(status=status, resolved_day=core.day)
    core._tick_events = []
    core._emit('dispatch_introduction_resolved', event_id=event_id, choice=choice, cat_id=data['cat_id'],
               name=data['candidate']['name'], cost=data['candidate']['cost'] if choice == 'accept' else 0)
    core._record(dict(kind='resolve_dispatch_introduction', event_id=event_id, choice=choice))


def accepted(core):
    return {event['introduction']['cat_id']: event['introduction']['candidate']
            for event in introductions(core) if event['introduction']['status'] == 'accepted'}


def expenses(core, day=None):
    return sum(event['introduction']['candidate']['cost'] for event in introductions(core)
               if event['introduction']['status'] == 'accepted'
               and (day is None or event['introduction']['resolved_day'] == day))


def prepare(core, data, events, day, used_ids):
    selected = rules(data)
    used = set(used_ids)
    joined = {}
    ordinal = 0
    for event in events.values():
        if 'introduction' not in event:
            continue
        ordinal += 1
        row = event['introduction']
        if not isinstance(row, dict) or set(row) != {'cat_id', 'candidate', 'status', 'presented_day', 'resolved_day'}:
            raise ValueError('派遣先の猫紹介記録が不正です。')
        identity(row['cat_id'])
        validate_candidates({row['cat_id']: row['candidate']})
        expected = copy.deepcopy(selected['candidate'])
        expected['name'] += f'（派遣紹介{ordinal}）'
        if (row['cat_id'] in used or row['candidate'] != expected
                or event['destination']['id'] != selected['destination']):
            raise ValueError('派遣先の猫紹介候補・IDが不正です。')
        used.add(row['cat_id'])
        if row['status'] == 'scheduled':
            if row['presented_day'] is not None or row['resolved_day'] is not None:
                raise ValueError('未提示の猫紹介記録が不正です。')
            continue
        if (event['status'] != 'resolved' or type(event['resolved_day']) is not int
                or type(row['presented_day']) is not int
                or not event['resolved_day'] <= row['presented_day'] <= min(day, event['resolved_day'] + 1)):
            raise ValueError('猫紹介の提示日が不正です。')
        if row['status'] == 'waiting':
            if row['presented_day'] != day or row['resolved_day'] is not None:
                raise ValueError('猫紹介への回答前に日付が進んでいます。')
        elif row['status'] in ('accepted', 'declined'):
            if type(row['resolved_day']) is not int or row['resolved_day'] != row['presented_day']:
                raise ValueError('猫紹介への回答日が不正です。')
            if row['status'] == 'accepted':
                joined[row['cat_id']] = row['candidate']
        else:
            raise ValueError('猫紹介の状態が不正です。')
    return selected, joined


def validate(core):
    if core.dispatch_introduction is not None and (not core.shift_rules or not core.health_rules):
        raise ValueError('派遣先の猫紹介には出勤・健康ルールが必要です。')
    for event in introductions(core):
        data = event['introduction']
        if data['status'] == 'scheduled' and event['status'] == 'resolved':
            if not core.closed or event['resolved_day'] != core.day:
                raise ValueError('帰還後の猫紹介が提示されていません。')
        if data['status'] == 'waiting' and not core.can_set_shifts:
            raise ValueError('猫紹介への回答前に営業が進んでいます。')
        if data['status'] == 'accepted':
            key, candidate = data['cat_id'], data['candidate']
            if ((core.traits or {}).get(key) != candidate.get('trait')
                    or (core.cat_features or {}).get(key) != candidate.get('features')):
                raise ValueError('派遣紹介で加入した猫の特徴・特性が一致しません。')
