"""新規ゲーム用の固定曜日来店。保存した曜日設定を全日程で使う。"""
import copy
import json
from pathlib import Path

DAYS = ('月', '火', '水', '木', '金', '土', '日')


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_weekdays.json').read_text())
    if not isinstance(data, dict) or set(data) != {'start_weekday', 'patterns'}:
        raise ValueError('来店曜日の設定が不正です。')
    if type(data['start_weekday']) is not int or not 0 <= data['start_weekday'] < 7:
        raise ValueError('開始曜日が不正です。')
    patterns = data['patterns']
    if not isinstance(patterns, list) or not patterns:
        raise ValueError('来店曜日を設定してください。')
    for days in patterns:
        if (not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d < 7 for d in days)
                or len(set(days)) != len(days)):
            raise ValueError('来店曜日が重複しているか不正です。')
    return copy.deepcopy(data)


def day_label(core, day=None):
    day = core.day if day is None else day
    if core.weekdays is None:
        return f'{day}日目'
    return f"{day}日目（{DAYS[(core.weekdays['start_weekday'] + day - 1) % 7]}）"


def customer_days(core, index):
    if core.weekdays is None:
        return tuple(range(7))
    patterns = core.weekdays['patterns']
    return patterns[index % len(patterns)]


def schedule(core, day=None):
    day = core.day if day is None else day
    weekday = (core.weekdays['start_weekday'] + day - 1) % 7 if core.weekdays else None
    return {f'guest-{i+1}': tick for i, tick in enumerate(core.config.arrival_ticks)
            if weekday is None or weekday in customer_days(core, i)}


def initialize(core, selected=None):
    core.require_events_resolved()
    if not core.compact or core.day != 1 or not core.can_set_shifts or core.weekdays is not None:
        raise ValueError('曜日来店は新規ゲームの準備中に一度だけ設定できます。')
    core.weekdays = rules(selected)
    core._tick_events = []
    core._emit('weekdays_initialized')
    core._record(dict(kind='initialize_weekdays', rules=copy.deepcopy(core.weekdays)))


def validate(core, data):
    core.weekdays = rules(data)
    previous = set()
    for row in core.day_results:
        expected = [] if row.get('day_type') == 'day_off' else sorted(schedule(core, row['day']))
        if row.get('customer_visits') != expected or row['summary']['arrivals'] != len(expected):
            raise ValueError('来店曜日と過去の来店実績が一致しません。')
        previous.update(expected)
    if previous != core.returning_customers:
        raise ValueError('再来店記録と曜日来店の実績が一致しません。')
    planned = schedule(core)
    day_off = core.closed and any(e['kind'] == 'day_off' and e.get('day') == core.day for e in core.events)
    expected_current = set() if day_off else {key for key, tick in planned.items() if tick < core.tick}
    if set(core.visits) != expected_current:
        raise ValueError('本日の来店人数と曜日予定が一致しません。')
    if any(key not in planned or visit.arrival_tick != planned[key] or visit.arrival_tick >= core.tick
           for key, visit in core.visits.items()):
        raise ValueError('本日の来店記録と曜日予定が一致しません。')
    return core.weekdays
