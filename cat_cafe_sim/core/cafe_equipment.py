"""休養スペースの購入・設置と、在店休養時の疲労回復補助。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_rest_space.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'cost', 'recovery_bonus'}:
        raise ValueError('休養スペースの設定が不正です。')
    for key in ('cost', 'recovery_bonus'):
        if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('設備費用・疲労回復量は正の数で指定してください。')
    if data['recovery_bonus'] > 100:
        raise ValueError('追加の疲労回復量は100以下にしてください。')
    return copy.deepcopy(data)


def reason(core, selected):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules:
        return '出勤・病気ルールが有効な営業準備中に購入できます。'
    if core.rest_space is not None:
        return '休養スペースは購入・設置済みです。'
    if core.funds <= selected['cost']:
        return '購入後に資金が残る必要があります。'
    return ''


def purchase(core, selected=None):
    selected = rules(selected)
    problem = reason(core, selected)
    if problem:
        raise ValueError(problem)
    core.funds -= selected['cost']
    core.rest_space = dict(day=core.day, rules=selected)
    core._tick_events = []
    core._emit('rest_space_purchased', cost=selected['cost'], recovery_bonus=selected['recovery_bonus'])
    core._record(dict(kind='purchase_rest_space', rules=selected))


def bonus(core, cat_id):
    data = getattr(core, 'rest_space', None)
    if not data:
        return 0
    from .cafe_activities import activity
    return data['rules']['recovery_bonus'] if activity(core, cat_id) == 'cafe' else 0


def expenses(core, day=None):
    data = core.rest_space
    return data['rules']['cost'] if data and (day is None or data['day'] == day) else 0


def validate(core, data):
    if not isinstance(data, dict) or set(data) != {'day', 'rules'}:
        raise ValueError('休養スペースの購入記録が不正です。')
    selected = rules(data['rules'])
    if type(data['day']) is not int or not 1 <= data['day'] <= core.day or not core.shift_rules or not core.health_rules:
        raise ValueError('休養スペースの購入日・休養ルールが不正です。')
    for result in core.day_results:
        expected_cost = selected['cost'] if result['day'] == data['day'] else 0
        if result['summary'].get('equipment_expenses', 0) != expected_cost:
            raise ValueError('営業履歴と設備購入記録が一致しません。')
    return copy.deepcopy(data)
