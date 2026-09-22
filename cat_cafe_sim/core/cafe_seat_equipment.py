"""購入した接客設備の保管・席への設置と交流補正。"""
import copy
import json
import math
from pathlib import Path


def definition(data):
    if (not isinstance(data, dict) or set(data) != {'id','name','cost','engagement','tension'}
            or data['id'] not in ('toys','cushion') or not isinstance(data['name'], str) or not data['name'].strip()):
        raise ValueError('接客設備の設定が不正です。')
    for key in ('cost','engagement','tension'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]):
            raise ValueError('設備の価格・効果が不正です。')
    if data['cost'] <= 0 or not 1 <= data['engagement'] <= 2 or not 1 <= data['tension'] <= 2:
        raise ValueError('設備の価格は正の数、効果倍率は1〜2で指定してください。')
    return copy.deepcopy(data)


def catalog():
    data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_seat_equipment.json').read_text())
    rows = [definition(row) for row in data]
    if len(rows) != 2 or {r['id'] for r in rows} != {'toys','cushion'}:
        raise ValueError('接客設備は2種類設定してください。')
    return rows


def seats(core):
    return core.seats if hasattr(core, 'seats') else {core.seat.id:core.seat}


def owned(core):
    return (core.equipment_store or {}).get('purchases', [])


def reason(core):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    return '' if core.compact and core.can_set_shifts else '接客設備の購入・設置は営業準備中に行ってください。'


def place(core, seat_id, item_id):
    target = seats(core)[seat_id]
    if item_id is not None:
        for seat in seats(core).values():
            if seat.equipment == item_id:
                seat.equipment = None
    target.equipment = item_id


def purchase(core, seat_id, selected):
    selected = definition(selected)
    problem = reason(core)
    if problem or seat_id not in seats(core):
        raise ValueError(problem or '席を選んでください。')
    if core.funds <= selected['cost']:
        raise ValueError('購入後に資金が残る必要があります。')
    if core.equipment_store is None:
        core.equipment_store = dict(purchases=[])
    item_id = f"equipment-{len(owned(core))+1}"
    owned(core).append(dict(id=item_id, day=core.day, rules=selected))
    core.funds -= selected['cost']
    place(core, seat_id, item_id)
    core._tick_events = []
    core._emit('seat_equipment_purchased', name=selected['name'], cost=selected['cost'], seat=seat_id)
    core._record(dict(kind='purchase_seat_equipment', seat_id=seat_id, rules=selected))


def equip(core, seat_id, item_id=None):
    problem = reason(core)
    if problem or seat_id not in seats(core):
        raise ValueError(problem or '席を選んでください。')
    if item_id is not None and item_id not in {r['id'] for r in owned(core)}:
        raise ValueError('購入済みの設備を選んでください。')
    if seats(core)[seat_id].equipment == item_id:
        return
    place(core, seat_id, item_id)
    core._tick_events = []
    core._emit('seat_equipment_changed', seat=seat_id, item_id=item_id)
    core._record(dict(kind='equip_seat', seat_id=seat_id, item_id=item_id))


def installed(core, seat_id):
    if seat_id not in seats(core):
        raise ValueError('席を選んでください。')
    key = seats(core)[seat_id].equipment
    return next((row['rules'] for row in owned(core) if row['id'] == key), None)


def effects(core, seat_id):
    data = installed(core, seat_id)
    return dict(equipment_engagement_multiplier=data['engagement'] if data else 1,
                equipment_tension_multiplier=data['tension'] if data else 1)


def description(core, seat_id):
    data = installed(core, seat_id)
    if not data:
        return '設備なし'
    effect = '・'.join(label + f'×{data[key]:g}' for key,label in (('engagement','関心'),('tension','テンション')) if data[key] != 1) or '補正なし'
    return f"{data['name']}（通常上昇：{effect}）"


def check_interaction(core, interaction, seat_id):
    if any(getattr(interaction.config,key) != value for key,value in effects(core, seat_id).items()):
        raise ValueError('交流の設備効果と席の設備が一致しません。')


def expenses(core, day=None):
    return sum(row['rules']['cost'] for row in owned(core) if day is None or row['day'] == day)


def validate(core, data):
    if not isinstance(data, dict) or set(data) != {'purchases'} or not isinstance(data['purchases'],list) or not data['purchases']:
        raise ValueError('接客設備の購入履歴が不正です。')
    last_day = 1
    for i,row in enumerate(data['purchases']):
        if (not isinstance(row,dict) or set(row) != {'id','day','rules'} or row['id'] != f'equipment-{i+1}'
                or type(row['day']) is not int or not last_day <= row['day'] <= core.day):
            raise ValueError('接客設備の購入日・IDが不正です。')
        definition(row['rules'])
        last_day = row['day']
    core.equipment_store = copy.deepcopy(data)
    installed_ids = [seat.equipment for seat in seats(core).values() if seat.equipment is not None]
    if len(set(installed_ids)) != len(installed_ids) or not set(installed_ids) <= {r['id'] for r in owned(core)}:
        raise ValueError('未購入の設備または同じ設備を複数席へ設置しています。')
    for day in core.day_results:
        if day['summary'].get('seat_equipment_expenses',0) != expenses(core,day['day']):
            raise ValueError('接客設備の購入費用と日次履歴が一致しません。')
    return core.equipment_store
