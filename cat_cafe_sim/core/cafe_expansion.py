"""営業資金で2席から3席、条件達成後に4席へ段階的に拡張する。"""
import copy
import json
import math
from pathlib import Path
from .models import Seat

EXTRA_CUSTOMER_ID = 'expanded-guest'


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_expansion.json').read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or set(data) not in ({'cost'}, {'cost', 'four_seat_cost'})
            or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in data.values())):
        raise ValueError('増設費用が不正です。')
    return copy.deepcopy(data)


def purchases(core):
    data = core.expansion
    if data is None:
        return []
    if 'purchases' in data:
        return data['purchases']
    return [dict(day=data['day'], cost=data['cost'], seats=3)]


def first_popularity_cleared(core):
    data = core.goal
    if not data or data.get('tracking_only'):
        return False
    first = (data.get('history') or [data])[0]
    return first['status'] == 'cleared'


def next_step(core, selected=None):
    selected = rules(selected)
    count = len(core.seats) if hasattr(core, 'seats') else 1
    if count == 2:
        return dict(from_seats=2, to_seats=3, cost=selected['cost'])
    if count == 3 and 'four_seat_cost' in selected:
        return dict(from_seats=3, to_seats=4, cost=selected['four_seat_cost'])
    return None


def reason(core, selected):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts:
        return '席の増設は営業準備中に行ってください。'
    if not hasattr(core, 'seats'):
        return '初回の増設は2席の営業が対象です。'
    step = next_step(core, selected)
    if step is None:
        return '現在追加できる席はありません。'
    if step['to_seats'] == 4 and not first_popularity_cleared(core):
        return '3席への増設は購入済みです。4席への増設は人気目標の第1段階達成後に解放されます。'
    expected = {f'seat-{i}' for i in range(1, step['from_seats']+1)}
    if set(core.seats) != expected or len(purchases(core)) != step['from_seats']-2:
        return '現在の席数と増設履歴が一致しません。'
    if core.funds <= step['cost']:
        return '増設後に資金が残る必要があります。'
    return ''


def purchase(core, selected=None):
    selected = rules(selected)
    problem = reason(core, selected)
    if problem:
        raise ValueError(problem)
    step = next_step(core, selected)
    core.funds -= step['cost']
    core.seats[f"seat-{step['to_seats']}"] = Seat(id=f"seat-{step['to_seats']}")
    rows = copy.deepcopy(purchases(core))
    rows.append(dict(day=core.day, cost=step['cost'], seats=step['to_seats']))
    core.expansion = dict(purchases=rows)
    core._tick_events = []
    core._emit('seats_expanded', cost=step['cost'], seat_count=step['to_seats'])
    core._record(dict(kind='expand_seats', rules=selected))


def expenses(core, day=None):
    return sum(row['cost'] for row in purchases(core) if day is None or row['day'] == day)


def four_seat_purchase(core):
    return next((row for row in purchases(core) if row['seats'] == 4), None)


def extra_schedule(core, day):
    row = four_seat_purchase(core)
    return {EXTRA_CUSTOMER_ID: 0} if row and day > row['day'] else {}


def validate(core, data, seat_count):
    legacy = isinstance(data, dict) and set(data) == {'day', 'cost'}
    if legacy:
        rows = [dict(day=data['day'], cost=data['cost'], seats=3)]
    elif (not isinstance(data, dict) or set(data) != {'purchases'}
          or not isinstance(data['purchases'], list) or not data['purchases']):
        raise ValueError('増設記録が不正です。')
    else:
        rows = data['purchases']
    if len(rows) not in (1, 2) or seat_count != len(rows)+2:
        raise ValueError('増設日・席数が不正です。')
    previous_day = 1
    for index, row in enumerate(rows, 3):
        fields = {'day','cost','seats'}
        if (not isinstance(row, dict) or set(row) != fields or row['seats'] != index
                or type(row['day']) is not int or not previous_day <= row['day'] <= core.day):
            raise ValueError('増設日・席数が不正です。')
        rules(dict(cost=row['cost']))
        previous_day = row['day']
    if len(rows) == 2 and not first_popularity_cleared(core):
        raise ValueError('4席への増設条件を満たしていません。')
    for result in core.day_results:
        day = result['day']
        summary = result['summary']
        expected_seats = 2 + sum(row['day'] <= day for row in rows)
        expected_cost = sum(row['cost'] for row in rows if row['day'] == day)
        if summary.get('seat_count') != expected_seats or summary.get('expansion_expenses', 0) != expected_cost:
            raise ValueError('営業履歴と増設記録が一致しません。')
    return copy.deepcopy(data)
