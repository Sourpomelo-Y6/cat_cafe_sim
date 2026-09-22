"""営業資金で2席から3席へ拡張する。一度だけ購入できる。"""
import copy
import json
import math
from pathlib import Path
from .models import Seat


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_expansion.json').read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or set(data) != {'cost'} or type(data['cost']) not in (int, float)
            or not math.isfinite(data['cost']) or data['cost'] <= 0):
        raise ValueError('増設費用が不正です。')
    return copy.deepcopy(data)


def reason(core, selected):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts:
        return '席の増設は営業準備中に行ってください。'
    if core.expansion is not None:
        return '3席への増設は購入済みです。'
    if not hasattr(core, 'seats') or set(core.seats) != {'seat-1', 'seat-2'}:
        return '初回の増設は2席の営業が対象です。'
    if core.funds <= selected['cost']:
        return '増設後に資金が残る必要があります。'
    return ''


def purchase(core, selected=None):
    selected = rules(selected)
    problem = reason(core, selected)
    if problem:
        raise ValueError(problem)
    core.funds -= selected['cost']
    core.seats['seat-3'] = Seat(id='seat-3')
    core.expansion = dict(day=core.day, cost=selected['cost'])
    core._tick_events = []
    core._emit('seats_expanded', cost=selected['cost'], seat_count=3)
    core._record(dict(kind='expand_seats', rules=selected))


def expenses(core, day=None):
    data = core.expansion
    return data['cost'] if data and (day is None or data['day'] == day) else 0


def validate(core, data, seat_count):
    if not isinstance(data, dict) or set(data) != {'day', 'cost'}:
        raise ValueError('増設記録が不正です。')
    rules(dict(cost=data['cost']))
    if type(data['day']) is not int or not 1 <= data['day'] <= core.day or seat_count != 3:
        raise ValueError('増設日・席数が不正です。')
    for result in core.day_results:
        summary = result['summary']
        expected_seats = 3 if result['day'] >= data['day'] else 2
        expected_cost = data['cost'] if result['day'] == data['day'] else 0
        if summary.get('seat_count') != expected_seats or summary.get('expansion_expenses', 0) != expected_cost:
            raise ValueError('営業履歴と増設記録が一致しません。')
    return copy.deepcopy(data)
