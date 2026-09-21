"""有力者への派遣で満足度を積み上げる、期限なしの独立目標。"""
import copy
import json
import math
from pathlib import Path

DESTINATION_ID = 'patron_visit'


def rules(data=None):
    from .cafe_activities import destination
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_patron.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'name', 'target', 'gain', 'destination'}:
        raise ValueError('有力者の目標設定が不正です。')
    if not isinstance(data['name'], str) or not data['name'].strip():
        raise ValueError('有力者の名前が不正です。')
    for key in ('target', 'gain'):
        if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('満足度の設定が不正です。')
    selected = destination(data['destination'])
    if selected['id'] != DESTINATION_ID:
        raise ValueError('有力者の派遣先IDが不正です。')
    return copy.deepcopy(data)


def pending(core):
    from .cafe_management import is_over
    data = core.patron
    return bool(data and data['status'] == 'cleared' and not data['continued'] and not is_over(core))


def enable(core, selected=None):
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts or not core.management or core.patron:
        raise ValueError('経営ルールが有効な準備中に一度だけ有力者目標を開始できます。')
    selected = rules(selected)
    core.patron = dict(rules=selected, started_day=core.day, satisfaction=0, status='active', resolved_day=None, continued=False)
    core._tick_events = []
    core._emit('patron_enabled')
    core._record(dict(kind='enable_patron', rules=selected))


def receive(core, event):
    data = core.patron
    if not data or event['destination']['id'] != DESTINATION_ID:
        return
    before = data['satisfaction']
    data['satisfaction'] = min(data['rules']['target'], before + data['rules']['gain'])
    core._emit('patron_satisfaction', gain=data['satisfaction'] - before, satisfaction=data['satisfaction'])
    from .cafe_management import is_over
    if data['status'] == 'active' and data['satisfaction'] >= data['rules']['target'] and not is_over(core):
        data.update(status='cleared', resolved_day=core.day)
        core._emit('patron_cleared')


def continue_game(core):
    from .cafe_activities import waiting_events
    core.require_running()
    if not pending(core):
        raise ValueError('確認待ちの有力者目標の結果はありません。')
    if waiting_events(core):
        raise ValueError('先に帰還・譲渡イベントを確認してください。')
    core.patron['continued'] = True
    core._tick_events = []
    core._emit('patron_continued')
    core._record(dict(kind='continue_patron'))


def validate(core, data):
    if not isinstance(data, dict) or set(data) != {'rules', 'started_day', 'satisfaction', 'status', 'resolved_day', 'continued'}:
        raise ValueError('有力者目標の状態が不正です。')
    selected = rules(data['rules'])
    if not core.management or type(data['started_day']) is not int or not core.management['started_day'] <= data['started_day'] <= core.day:
        raise ValueError('有力者目標の開始日が不正です。')
    if type(data['continued']) is not bool or data['status'] not in ('active', 'cleared'):
        raise ValueError('有力者目標の結果が不正です。')
    if type(data['satisfaction']) not in (int, float) or not math.isfinite(data['satisfaction']):
        raise ValueError('満足度が不正です。')
    events = [e for e in (core.activities or {}).get('events', {}).values() if e['destination']['id'] == DESTINATION_ID]
    for event in events:
        if event['started_day'] < data['started_day'] or event['destination'] != selected['destination']:
            raise ValueError('有力者目標と派遣記録が一致しません。')
    received = sorted((e for e in events if e['status'] == 'resolved'), key=lambda e: e['resolved_day'])
    satisfaction = 0
    resolved = None
    for event in received:
        satisfaction = min(selected['target'], satisfaction + selected['gain'])
        if resolved is None and satisfaction >= selected['target']:
            resolved = event['resolved_day']
    if (data['satisfaction'] != satisfaction or data['status'] != ('cleared' if resolved is not None else 'active')
            or data['resolved_day'] != resolved or (resolved is not None and type(data['resolved_day']) is not int)
            or (resolved is None and data['continued'])):
        raise ValueError('満足度・達成日と帰還履歴が一致しません。')
    if resolved is not None and not data['continued'] and (core.day != resolved or not (core.closed or core.can_set_shifts)):
        raise ValueError('有力者目標の結果確認前に営業が進んでいます。')
    return copy.deepcopy(data)


def progress(core):
    data = core.patron
    if not data:
        return '有力者目標：未導入'
    label = 'クリア（継続中）' if data['continued'] else 'クリア・結果確認待ち' if data['status'] == 'cleared' else '挑戦中'
    return f"{data['rules']['name']}：満足度 {data['satisfaction']:g} / {data['rules']['target']:g} · {label}"
