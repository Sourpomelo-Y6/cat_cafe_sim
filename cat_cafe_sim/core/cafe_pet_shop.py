"""新規ゲームの固定候補から、準備中に猫を購入する。"""
import copy
import json
from pathlib import Path

from .cafe_recruitment import catalog, validate_candidates, require_preparation, join_cat


def candidates(used_ids, definitions=None):
    if definitions is None:
        definitions = catalog(json.loads((Path(__file__).resolve().parents[2] /
            'config/cafe_pet_shop.json').read_text(encoding='utf-8')))
    rows = {}
    used = set(used_ids)
    index = 1
    for candidate in definitions:
        while f'shop-{index}' in used:
            index += 1
        key = f'shop-{index}'
        rows[key] = copy.deepcopy(candidate)
        used.add(key)
    return validate_candidates(rows)


def initialize(core, rows):
    require_preparation(core)
    if core.day != 1 or core.pet_shop is not None:
        raise ValueError('ペットショップは新規ゲームの準備中に一度だけ設定できます。')
    rows = validate_candidates(rows)
    from .cafe_dispatch_introduction import reserved_ids
    from .cafe_regular_introduction import reserved_ids as regular_ids
    from .cafe_visiting_cat import reserved_ids as visiting_ids
    used = (regular_ids(core)|visiting_ids(core)) | set(core.cats) | set((core.recruitment or {}).get('candidates', {})) | reserved_ids(core)
    if core.intake_request:
        used.add(core.intake_request['rules']['cat_id'])
    if set(rows) & used:
        raise ValueError('購入候補の猫IDが既存の猫・候補と重複しています。')
    core.pet_shop = dict(opened_day=core.day, candidates=rows, accepted={})
    core._tick_events = []
    core._emit('pet_shop_initialized')
    core._record(dict(kind='initialize_pet_shop', candidates=copy.deepcopy(rows)))


def purchase(core, cat_id):
    require_preparation(core)
    data = core.pet_shop
    if not data or cat_id not in data['candidates']:
        raise ValueError('ペットショップの購入候補を選んでください。')
    if cat_id in data['accepted']:
        raise ValueError('この猫はすでに購入しています。')
    row = data['candidates'][cat_id]
    join_cat(core, cat_id, row)
    data['accepted'][cat_id] = core.day
    core._tick_events = []
    core._emit('cat_purchased', cat_id=cat_id, name=row['name'], cost=row['cost'])
    core._record(dict(kind='purchase_cat', cat_id=cat_id))


def accepted(core):
    data = core.pet_shop
    return {key: data['candidates'][key] for key in data['accepted']} if data else {}


def expenses(core, day=None):
    data = core.pet_shop
    return sum(data['candidates'][key]['cost'] for key, joined in data['accepted'].items()
               if day is None or joined == day) if data else 0


def prepare(data, day, used_ids):
    from .cafe_recruitment import validate
    if not isinstance(data, dict) or set(data) != {'opened_day', 'candidates', 'accepted'}:
        raise ValueError('ペットショップの購入記録が不正です。')
    result = validate(data, day, used_ids)
    if result['opened_day'] != 1:
        raise ValueError('ペットショップの候補は新規開始時に固定してください。')
    return result


def validate(core):
    if core.pet_shop is not None and (not core.shift_rules or not core.health_rules):
        raise ValueError('猫の購入には出勤・病気ルールが必要です。')
    for key, row in accepted(core).items():
        if ((core.traits or {}).get(key) != row.get('trait')
                or (core.cat_features or {}).get(key) != row.get('features')):
            raise ValueError('購入した猫の特徴・特性が候補と一致しません。')
