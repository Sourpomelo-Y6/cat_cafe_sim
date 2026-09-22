"""準備中の保護猫受け入れ。候補と費用を固定し、加入を一度だけ記録する。"""
import copy
import json
import math
from pathlib import Path

from .human_cat_relationship import identity
from .human_cat_types import Personality, load_presets
from .models import Cat


REFRESH_DAYS = 3


def candidates(used_ids, batch=0):
    definitions = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_recruitment.json').read_text(encoding='utf-8'))
    presets = load_presets()
    from .cafe_traits import definitions as trait_definitions
    traits = trait_definitions()
    used = set(used_ids)
    rows = {}
    index = 1
    for row in definitions:
        while f'rescue-{index}' in used:
            index += 1
        key = f'rescue-{index}'
        used.add(key)
        rows[key] = dict(name=row['name'] if batch == 0 else f"{row['name']}（紹介{batch + 1}）", personality=presets[row['preset']].to_dict(), cost=row['cost'])
        if 'features' in row:
            from .cafe_preferences import validate_features
            rows[key]['features'] = validate_features(row['features'])
        if row.get('trait') is not None:
            rows[key]['trait'] = copy.deepcopy(traits[row['trait']])
    return validate_candidates(rows)


def validate_candidates(rows):
    if not isinstance(rows, dict) or not rows:
        raise ValueError('受け入れ候補が不正です。')
    for key, row in rows.items():
        identity(key)
        if not isinstance(row, dict) or not {'name', 'personality', 'cost'} <= set(row) <= {'name', 'personality', 'cost', 'trait', 'features'}:
            raise ValueError('候補の項目が不正です。')
        if 'features' in row:
            from .cafe_preferences import validate_features
            validate_features(row['features'])
        if 'trait' in row:
            from .cafe_traits import validate_trait
            validate_trait(row['trait'])
        identity(row['name'])
        Personality.from_dict(row['personality'])
        cost = row['cost']
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
            raise ValueError('受け入れ費用が不正です。')
    return copy.deepcopy(rows)


def require_preparation(core):
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules:
        raise ValueError('受け入れは出勤・病気ルールが有効な営業準備中に行ってください。')


def open_candidates(core, rows):
    require_preparation(core)
    if core.recruitment is not None:
        raise ValueError('受け入れ候補はすでに決まっています。')
    rows = validate_candidates(rows)
    if set(rows) & (set(core.cats) | ({core.intake_request['rules']['cat_id']} if core.intake_request else set())):
        raise ValueError('候補の猫IDが所属猫と重複しています。')
    core.recruitment = dict(opened_day=core.day, candidates=copy.deepcopy(rows), accepted={})
    core._tick_events = []
    core._emit('recruitment_opened')
    core._record(dict(kind='open_recruitment', candidates=rows))


def next_candidate_day(data):
    return data.get('last_added_day', data['opened_day']) + REFRESH_DAYS


def add_candidates(core, rows):
    require_preparation(core)
    data = core.recruitment
    if data is None or core.day < next_candidate_day(data):
        raise ValueError('次の候補追加日までお待ちください。')
    rows = validate_candidates(rows)
    if set(rows) & (set(core.cats) | set(data['candidates']) | ({core.intake_request['rules']['cat_id']} if core.intake_request else set())):
        raise ValueError('追加候補の猫IDが重複しています。')
    if 'presented_days' not in data:
        data['presented_days'] = {key: data['opened_day'] for key in data['candidates']}
    data['candidates'].update(rows)
    data['presented_days'].update({key: core.day for key in rows})
    data['last_added_day'] = core.day
    core._tick_events = []
    core._emit('recruitment_added', count=len(rows))
    core._record(dict(kind='add_recruitment', candidates=rows))


def accept(core, cat_id):
    require_preparation(core)
    data = core.recruitment
    if not data or cat_id not in data['candidates']:
        raise ValueError('受け入れる候補を選んでください。')
    if cat_id in data['accepted'] or cat_id in core.cats:
        raise ValueError('この猫はすでに受け入れています。')
    row = data['candidates'][cat_id]
    join_cat(core,cat_id,row)
    data['accepted'][cat_id] = core.day
    core._tick_events = []
    core._emit('cat_recruited', cat_id=cat_id, name=row['name'], cost=row['cost'])
    core._record(dict(kind='recruit_cat', cat_id=cat_id))


def join_cat(core,cat_id,row):
    validate_candidates({cat_id:row})
    if cat_id in core.cats:
        raise ValueError('この猫はすでに加入しています。')
    if core.funds <= row['cost']:
        raise ValueError('受け入れ後に資金が残る必要があります。')
    cat = Cat(id=cat_id, stamina=core.config.max_stamina, spirit=core.config.max_spirit)
    core.cats[cat_id] = cat
    core.cat_service_ticks[cat_id] = 0
    core.initial_fatigue[cat_id] = 0
    core.initial_health[cat_id] = dict(status='healthy', remaining=0)
    if core.activities is not None:
        core.activities['cats'][cat_id] = 'cafe'
        core.activities['day_locations'][cat_id] = 'cafe'
    if core.player_bond is not None:
        for field in ('affinity', 'today', 'total'):
            core.player_bond[field][cat_id] = 0
    if core.management is not None:
        core.management['stress'][cat_id] = 0
    if 'trait' in row:
        if core.traits is None:
            core.traits = {}
        core.traits[cat_id] = copy.deepcopy(row['trait'])
    if 'features' in row:
        if core.cat_features is None:
            core.cat_features = {}
        core.cat_features[cat_id] = list(row['features'])
    core.funds -= row['cost']


def expenses(core, day=None):
    data = core.recruitment
    from .cafe_intake_request import expenses as request_expenses
    return (sum(data['candidates'][key]['cost'] for key, joined in data['accepted'].items()
               if day is None or joined == day) if data else 0) + request_expenses(core,day)


def validate(data, day, initial_ids):
    if not isinstance(data, dict) or set(data) not in ({'opened_day', 'candidates', 'accepted'}, {'opened_day', 'candidates', 'accepted', 'last_added_day', 'presented_days'}):
        raise ValueError('受け入れ記録が不正です。')
    rows = validate_candidates(data['candidates'])
    if set(rows) & set(initial_ids):
        raise ValueError('候補と初期所属猫が重複しています。')
    if type(data['opened_day']) is not int or not 1 <= data['opened_day'] <= day:
        raise ValueError('候補の提示日が不正です。')
    if not isinstance(data['accepted'], dict) or not set(data['accepted']) <= set(rows):
        raise ValueError('受け入れた猫が不正です。')
    if any(type(joined) is not int or not data['opened_day'] <= joined <= day for joined in data['accepted'].values()):
        raise ValueError('受け入れ日が不正です。')
    if 'presented_days' in data:
        days = data['presented_days']
        if not isinstance(days, dict) or set(days) != set(rows):
            raise ValueError('候補の追加日が不正です。')
        if any(type(value) is not int or not data['opened_day'] <= value <= day for value in days.values()):
            raise ValueError('候補の追加日が不正です。')
        dates = sorted(set(days.values()))
        if dates[0] != data['opened_day'] or any(b - a < REFRESH_DAYS for a, b in zip(dates, dates[1:])):
            raise ValueError('候補の追加間隔が不正です。')
        if type(data['last_added_day']) is not int or data['last_added_day'] != dates[-1]:
            raise ValueError('最終追加日が不正です。')
        if any(joined < days[key] for key, joined in data['accepted'].items()):
            raise ValueError('提示前に受け入れた猫があります。')
    return copy.deepcopy(data)
