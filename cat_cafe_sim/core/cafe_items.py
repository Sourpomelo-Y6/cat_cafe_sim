"""派遣ごとに固定したケア用品。残数は受取済み報酬と使用記録から求める。"""
import copy
import json
import math
from pathlib import Path


def definition(data):
    fields = {'care_supplies': ('stress_relief',), 'nutrition_snack': ('fatigue_relief',),
              'special_care_set': ('fatigue_relief','stress_relief')}
    item_id = data.get('id') if isinstance(data, dict) else None
    selected = fields.get(item_id) if isinstance(item_id, str) else None
    if (not selected or set(data) != {'id', 'name', *selected}
            or not isinstance(data['name'], str) or not data['name'].strip()
            or any(type(data[field]) not in (int, float) or not math.isfinite(data[field])
                   or not 0 < data[field] <= 100 for field in selected)):
        raise ValueError('ケア用品の設定が不正です。')
    return copy.deepcopy(data)


def stat(item):
    if item['id']=='special_care_set':return 'both'
    return 'fatigue' if item['id'] == 'nutrition_snack' else 'stress'


def label(item):
    if stat(item)=='both':return '疲労・ストレス'
    return '疲労' if stat(item) == 'fatigue' else 'ストレス'


def relief(item):
    if stat(item)=='both':return dict(fatigue=item['fatigue_relief'],stress=item['stress_relief'])
    return item[stat(item) + '_relief']


def current(core, item, cat_id):
    if stat(item)=='both':return dict(fatigue=core.cats[cat_id].fatigue,stress=core.management['stress'][cat_id])
    return core.cats[cat_id].fatigue if stat(item) == 'fatigue' else core.management['stress'][cat_id]


def effect_text(item):
    if stat(item)=='both':return f"疲労 −{item['fatigue_relief']:g} / ストレス −{item['stress_relief']:g}"
    return f'{label(item)} −{relief(item):g}'


def after_value(item,before):
    if stat(item)=='both':return {key:max(0,value-relief(item)[key]) for key,value in before.items()}
    return max(0,before-relief(item))


def change_text(item,before,after):
    if stat(item)=='both':return ' / '.join(f"{title} {before[key]:g} → {after[key]:g}" for key,title in (('fatigue','疲労'),('stress','ストレス')))
    return f'{label(item)} {before:g} → {after:g}'


def for_destination(destination):
    rows = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_item_rewards.json').read_text(encoding='utf-8'))
    row = rows.get(destination['id'])
    return definition(row) if row is not None else None


def rewards(core):
    result={key:dict(item=copy.deepcopy(event['item_reward']),available_day=event['resolved_day'])
            for key,event in (core.activities or {}).get('events',{}).items()
            if event['status']=='resolved' and 'item_reward' in event}
    from .cafe_store_events import item_rewards
    result.update(item_rewards(core))
    result.update({row["source"]:dict(item=copy.deepcopy(row["item"]),available_day=row["day"])
                   for row in core.item_purchases})
    return result


def reward_for_source(core,source):
    return rewards(core).get(source)


def inventory(core):
    used = {row['source'] for row in core.item_uses} | {row['source'] for row in core.item_sales}
    return {key:copy.deepcopy(value['item']) for key,value in rewards(core).items() if key not in used}


def unavailable_reason(core, source, cat_id):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts:
        return 'アイテムは営業準備中に使えます。'
    if source not in inventory(core):
        return '所持しているアイテムを選んでください。'
    item = inventory(core)[source]
    if stat(item) in ('stress','both') and core.management is None:
        return 'ストレスを管理する経営ルールの導入が必要です。'
    if stat(item) in ('fatigue','both') and core.shift_rules is None:
        return '疲労を管理する出勤ルールの導入が必要です。'
    if cat_id not in core.cats or core.activity(cat_id) != 'cafe':
        return '在店している猫を選んでください。'
    value=current(core,item,cat_id)
    if (all(amount<=0 for amount in value.values()) if stat(item)=='both' else value<=0):
        return f'この猫の{label(item)}は0です。アイテムは消費しません。'
    return ''


def use(core, source, cat_id):
    reason = unavailable_reason(core, source, cat_id)
    if reason:
        raise ValueError(reason)
    item = inventory(core)[source]
    before = current(core, item, cat_id)
    after = after_value(item,before)
    if stat(item) in ('fatigue','both'):
        fatigue=after['fatigue'] if stat(item)=='both' else after
        core.cats[cat_id].fatigue = fatigue
        # 閉店精算でも、使用後の疲労を基準にする。
        core.initial_fatigue[cat_id] = fatigue
    if stat(item) in ('stress','both'):
        core.management['stress'][cat_id] = after['stress'] if stat(item)=='both' else after
    core.item_uses.append(dict(source=source, cat_id=cat_id, day=core.day, before=before, after=after))
    core._tick_events = []
    core._emit('item_used', cat_id=cat_id, name=item['name'], before=before, after=after,
               **({'stat': stat(item)} if stat(item) != 'stress' else {}))
    core._record(dict(kind='use_item', source=source, cat_id=cat_id))


def validate_uses(core, data):
    if not isinstance(data, list) or not data:
        raise ValueError('アイテムの使用記録が不正です。')
    sources = set()
    last_day = 0
    for row in data:
        if not isinstance(row, dict) or set(row) != {'source', 'cat_id', 'day', 'before', 'after'}:
            raise ValueError('アイテムの使用項目が不正です。')
        if not isinstance(row['source'], str) or not isinstance(row['cat_id'], str):
            raise ValueError('使用したアイテム・対象猫が不正です。')
        reward=reward_for_source(core,row['source'])
        if not reward or row['source'] in sources:
            raise ValueError('未受取または使用済みのアイテムが消費されています。')
        item = reward['item']
        if ((stat(item) in ('stress','both') and core.management is None)
                or (stat(item) in ('fatigue','both') and core.shift_rules is None)):
            raise ValueError('アイテムの効果に必要なルールがありません。')
        started = core.management['started_day'] if stat(item) in ('stress','both') else 1
        if (row['cat_id'] not in core.cats or type(row['day']) is not int
                or not max(last_day,reward['available_day'],started) <= row['day'] <= core.day):
            raise ValueError('アイテムの使用日・対象猫が不正です。')
        if stat(item)=='both':
            if any(not isinstance(row[key],dict) or set(row[key])!={'fatigue','stress'} for key in ('before','after')):
                raise ValueError('ケアセットの状態変化が不正です。')
            values={key:row[key] for key in ('before','after')}
        else:
            values={key:{stat(item):row[key]} for key in ('before','after')}
        for changes in values.values():
            for key,value in changes.items():
                maximum=core.shift_rules.max_fatigue if key=='fatigue' else 100
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=maximum:
                    raise ValueError('アイテムによる状態変化が不正です。')
        if not any(value>0 for value in values['before'].values()) or row['after'] != after_value(item,row['before']):
            raise ValueError('アイテムの効果と使用結果が一致しません。')
        sources.add(row['source'])
        last_day = row['day']
    return copy.deepcopy(data)
