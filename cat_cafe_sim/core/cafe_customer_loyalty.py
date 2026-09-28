"""良い接客の蓄積による店への常連度と、週1回の追加来店。"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_customer_loyalty.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'gain', 'threshold'}):
        raise ValueError('常連度の設定が不正です。')
    for value in data.values():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('常連度の設定が不正です。')
    if data['gain'] > data['threshold']:
        raise ValueError('常連度の上昇量は必要値以下にしてください。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.customer_loyalty is not None
            or core.weekdays is None or core.customer_preferences is None):
        raise ValueError('常連度は新規ゲームの準備中に設定してください。')
    core.customer_loyalty = dict(rules=rules(selected), customers={})
    core._tick_events = []
    core._record(dict(kind='initialize_customer_loyalty', rules=copy.deepcopy(core.customer_loyalty['rules'])))


def apply(core, result):
    data = core.customer_loyalty
    if data is None or result['affinity_delta'] <= 0:
        return
    key = result['customer_id']
    row = data['customers'].setdefault(key, dict(score=0, regular_day=None))
    before = row['score']
    row['score'] = min(data['rules']['threshold'], before + data['rules']['gain'])
    became = row['regular_day'] is None and row['score'] >= data['rules']['threshold']
    if became:
        row['regular_day'] = core.day
    core._emit('customer_loyalty_gained', customer_id=key, before=before, after=row['score'], became_regular=became)


def row(core, customer_id):
    data = core.customer_loyalty
    return copy.deepcopy(data['customers'].get(customer_id, dict(score=0, regular_day=None))) if data else None


def extra_weekday(core, customer_id):
    found = re.fullmatch(r'guest-([1-9][0-9]*)', customer_id)
    if found and core.weekdays is not None:
        from .cafe_weekdays import customer_days
        normal = set(customer_days(core, int(found[1])-1))
        available = [day for day in range(7) if day not in normal]
        if available:
            return available[0]
    digest = hashlib.sha256(customer_id.encode()).digest()
    return int.from_bytes(digest[:2], 'big') % 7


def extra_schedule(core, day):
    data = core.customer_loyalty
    if data is None or core.weekdays is None:
        return {}
    weekday = (core.weekdays['start_weekday'] + day - 1) % 7
    return {key: 0 for key, value in data['customers'].items()
            if value['regular_day'] is not None and day > value['regular_day']
            and extra_weekday(core, key) == weekday}


def prepare(core, data):
    if not isinstance(data, dict) or set(data) != {'rules', 'customers'} or not isinstance(data['customers'], dict):
        raise ValueError('常連度の記録が不正です。')
    selected = rules(data['rules'])
    for key, value in data['customers'].items():
        if (not isinstance(key, str) or not key or not isinstance(value, dict)
                or set(value) != {'score', 'regular_day'}
                or type(value['score']) not in (int, float) or not math.isfinite(value['score'])
                or not 0 <= value['score'] <= selected['threshold']
                or (value['regular_day'] is not None and
                    (type(value['regular_day']) is not int or not 1 <= value['regular_day'] <= core.day))
                or (value['regular_day'] is None) != (value['score'] < selected['threshold'])):
            raise ValueError('常連度の記録が不正です。')
    return copy.deepcopy(data)


def validate(core, data):
    data = prepare(core, data)
    selected = data['rules']
    from .cafe_checkpoint import outcome_result
    expected = {}
    outcomes = [outcome_result(value) for value in core.outcomes.values()]
    offset = 0
    days = [(result['day'], result['summary']['completed_interactions']) for result in core.day_results]
    days.append((core.day, len(outcomes)-offset-sum(count for _, count in days)))
    for day, count in days:
        for result in outcomes[offset:offset+count]:
            if result['affinity_delta'] <= 0:
                continue
            row = expected.setdefault(result['customer_id'], dict(score=0, regular_day=None))
            row['score'] = min(selected['threshold'], row['score'] + selected['gain'])
            if row['regular_day'] is None and row['score'] >= selected['threshold']:
                row['regular_day'] = day
        offset += count
    if data['customers'] != expected:
        raise ValueError('常連度と接客成果が一致しません。')
    return data
