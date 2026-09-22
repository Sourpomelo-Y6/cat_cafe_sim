"""猫ごとに固定して保存するパッシブ特性。特性なしは従来の係数を使う。"""
import copy
import json
import math
from pathlib import Path

DEFAULTS = dict(service_stress=1, service_fatigue=1, rest_fatigue=1, dispatch_reward=1, return_stress=0)


def validate_trait(data):
    if not isinstance(data, dict) or set(data) != {'id', 'name'} | set(DEFAULTS):
        raise ValueError('猫の特性の項目が不正です。')
    for field in ('id', 'name'):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError('猫の特性の名前が不正です。')
    for field in DEFAULTS:
        value = data[field]
        maximum = 100 if field == 'return_stress' else 2
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise ValueError('猫の特性の効果が不正です。')
    return copy.deepcopy(data)


def definitions():
    rows = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_traits.json').read_text(encoding='utf-8'))
    if not isinstance(rows, dict):
        raise ValueError('特性の設定が不正です。')
    for key, row in rows.items():
        validate_trait(row)
        if key != row['id']:
            raise ValueError('特性のIDが一致しません。')
    return rows


def validate(core, data):
    if not isinstance(data, dict) or not set(data) <= set(core.cats):
        raise ValueError('特性を持つ猫が不正です。')
    return {key: validate_trait(row) for key, row in data.items()}


def initialize(core, data):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.traits is not None
            or core.activities or core.recruitment or core.player_bond):
        raise ValueError('初期特性は新規ゲームの準備時に一度だけ設定できます。')
    core.traits = validate(core, data)
    core._tick_events = []
    core._emit('traits_initialized')
    core._record(dict(kind='initialize_traits', traits=copy.deepcopy(core.traits)))


def trait(core, cat_id):
    return (getattr(core,'traits',None) or {}).get(cat_id)


def effect(core, cat_id, field):
    return (trait(core, cat_id) or DEFAULTS)[field]


def fatigue_change(core, cat_id, working, service_ticks):
    if working:
        return service_ticks * core.shift_rules.fatigue_per_service_tick * effect(core, cat_id, 'service_fatigue')
    from .cafe_equipment import bonus
    return -(core.shift_rules.rest_day_recovery * effect(core, cat_id, 'rest_fatigue') + bonus(core, cat_id))


def dispatch_terms(core, cat_id, base_reward):
    reward = base_reward * effect(core, cat_id, 'dispatch_reward')
    if not math.isfinite(reward):
        raise ValueError('派遣報酬が大きすぎます。')
    return dict(reward=reward, stress=effect(core, cat_id, 'return_stress') if core.management else 0)


def description(data):
    if data is None:
        return [('特性', 'なし')]
    rows = [('特性', data['name'])]
    for key, label in (('service_stress', '接客ストレス'), ('service_fatigue', '接客疲労'),
                       ('rest_fatigue', '休養時の疲労回復'), ('dispatch_reward', '派遣報酬')):
        if data[key] != 1:
            rows.append((label, f"通常の{data[key]:g}倍"))
    if data['return_stress']:
        rows.append(('派遣帰還時のストレス', f"＋{data['return_stress']:g}（経営ルール有効時）"))
    return rows
