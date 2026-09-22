"""猫の外見的特徴と、来客ごとに固定する好み。特性・猫の個性とは独立。"""
import copy
import hashlib
import json
import math
from pathlib import Path
from .human_cat_relationship import identity

FEATURES = {
    'white': ('白猫', 'coat'), 'black': ('黒猫', 'coat'),
    'calico': ('三毛', 'coat'), 'orange_tabby': ('茶トラ', 'coat'),
    'brown_tabby': ('キジトラ', 'coat'), 'black_white': ('白黒', 'coat'),
    'short_hair': ('短毛', 'hair'), 'long_hair': ('長毛', 'hair'),
}


def validate_features(values):
    if not isinstance(values, list) or any(not isinstance(v, str) or v not in FEATURES for v in values):
        raise ValueError('猫の特徴が不正です。')
    if len({FEATURES[v][1] for v in values}) != len(values):
        raise ValueError('毛色・柄と毛の長さはそれぞれ1つまで指定してください。')
    return list(values)


def feature_text(values):
    return '・'.join(FEATURES[v][0] for v in values) if values else '未設定'


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_customer_preferences.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'pool', 'tension_multiplier'}:
        raise ValueError('お客さんの好み設定が不正です。')
    pool = data['pool']
    if (not isinstance(pool, list) or not pool or any(not isinstance(v, str) or v not in FEATURES for v in pool)
            or len(set(pool)) != len(pool)):
        raise ValueError('お客さんの好み候補が不正です。')
    multiplier = data['tension_multiplier']
    if type(multiplier) not in (int, float) or not math.isfinite(multiplier) or not 1 <= multiplier <= 2:
        raise ValueError('相性補正は1以上2以下にしてください。')
    return copy.deepcopy(data)


def validate_cats(core, data):
    if not isinstance(data, dict) or not set(data) <= set(core.cats):
        raise ValueError('特徴の対象猫が不正です。')
    return {key: validate_features(values) for key, values in data.items()}


def initialize(core, cats, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.cat_features is not None
            or core.customer_preferences is not None or core.recruitment or core.player_bond or core.activities):
        raise ValueError('特徴・好みは新規ゲームの準備中に一度だけ設定できます。')
    cats = validate_cats(core, cats)
    selected = rules(selected)
    core.cat_features = cats
    core.customer_preferences = dict(rules=selected, customers={})
    core._tick_events = []
    core._emit('preferences_initialized')
    core._record(dict(kind='initialize_preferences', cats=copy.deepcopy(cats), rules=selected))


def preference_for(seed, customer_id, pool):
    digest = hashlib.sha256(f'{seed}:{customer_id}'.encode('utf-8')).digest()
    return pool[int.from_bytes(digest[:8], 'big') % len(pool)]


def arrive(core):
    data = core.customer_preferences
    if data is not None:
        for key in core.visits:
            data['customers'].setdefault(key, preference_for(core.seed, key, data['rules']['pool']))


def validate_customers(core, data):
    if not isinstance(data, dict) or set(data) != {'rules', 'customers'} or not isinstance(data['customers'], dict):
        raise ValueError('お客さんの好み記録が不正です。')
    selected = rules(data['rules'])
    if set(data['customers']) != set(core.visits) | core.returning_customers:
        raise ValueError('お客さんの好みと来店記録が一致しません。')
    for key, value in data['customers'].items():
        identity(key)
        if value != preference_for(core.seed, key, selected['pool']):
            raise ValueError('お客さんの好みが一致しません。')
    return copy.deepcopy(data)


def match(core, cat_id, customer_id):
    features = (getattr(core, 'cat_features', None) or {}).get(cat_id, [])
    data = getattr(core, 'customer_preferences', None)
    preference = data['customers'].get(customer_id) if data else None
    matched = preference is not None and preference in features
    multiplier = data['rules']['tension_multiplier'] if matched else 1
    label = FEATURES[preference][0] + '好き' if preference else '好み未設定'
    effect = f'一致：通常のテンション上昇×{multiplier:g}' if matched else '特徴未設定・補正なし' if not features else '一致なし・補正なし'
    return dict(preference=preference, matched=matched, multiplier=multiplier,
                features=feature_text(features), text=f'{label} / {effect}')


def check_interaction(core, interaction):
    expected = match(core, interaction.cat_id, interaction.customer_id)['multiplier']
    if interaction.config.customer_tension_multiplier != expected:
        raise ValueError('交流の相性補正が猫の特徴・お客さんの好みと一致しません。')
