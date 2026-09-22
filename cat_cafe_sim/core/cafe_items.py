"""派遣ごとに固定したケア用品。残数は受取済み報酬と使用記録から求める。"""
import copy
import json
import math
from pathlib import Path


def definition(data):
    if (not isinstance(data, dict) or set(data) != {'id', 'name', 'stress_relief'}
            or data['id'] != 'care_supplies' or not isinstance(data['name'], str) or not data['name'].strip()
            or type(data['stress_relief']) not in (int, float)
            or not math.isfinite(data['stress_relief']) or not 0 < data['stress_relief'] <= 100):
        raise ValueError('ケア用品の設定が不正です。')
    return copy.deepcopy(data)


def for_destination(destination):
    rows = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_item_rewards.json').read_text(encoding='utf-8'))
    row = rows.get(destination['id'])
    return definition(row) if row is not None else None


def inventory(core):
    used = {row['source'] for row in core.item_uses}
    return {key: copy.deepcopy(event['item_reward'])
            for key, event in (core.activities or {}).get('events', {}).items()
            if event['status'] == 'resolved' and 'item_reward' in event and key not in used}


def unavailable_reason(core, source, cat_id):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts:
        return 'アイテムは営業準備中に使えます。'
    if core.management is None:
        return 'ストレスを管理する経営ルールの導入が必要です。'
    if source not in inventory(core):
        return '所持しているアイテムを選んでください。'
    if cat_id not in core.cats or core.activity(cat_id) != 'cafe':
        return '在店している猫を選んでください。'
    if core.management['stress'][cat_id] <= 0:
        return 'この猫のストレスは0です。アイテムは消費しません。'
    return ''


def use(core, source, cat_id):
    reason = unavailable_reason(core, source, cat_id)
    if reason:
        raise ValueError(reason)
    item = inventory(core)[source]
    before = core.management['stress'][cat_id]
    after = max(0, before-item['stress_relief'])
    core.management['stress'][cat_id] = after
    core.item_uses.append(dict(source=source, cat_id=cat_id, day=core.day, before=before, after=after))
    core._tick_events = []
    core._emit('item_used', cat_id=cat_id, name=item['name'], before=before, after=after)
    core._record(dict(kind='use_item', source=source, cat_id=cat_id))


def validate_uses(core, data):
    if not isinstance(data, list) or not data or core.management is None:
        raise ValueError('アイテムの使用記録が不正です。')
    sources = set()
    last_day = 0
    for row in data:
        if not isinstance(row, dict) or set(row) != {'source', 'cat_id', 'day', 'before', 'after'}:
            raise ValueError('アイテムの使用項目が不正です。')
        if not isinstance(row['source'], str) or not isinstance(row['cat_id'], str):
            raise ValueError('使用したアイテム・対象猫が不正です。')
        event = (core.activities or {}).get('events', {}).get(row['source'])
        if not event or event['status'] != 'resolved' or 'item_reward' not in event or row['source'] in sources:
            raise ValueError('未受取または使用済みのアイテムが消費されています。')
        if (row['cat_id'] not in core.cats or type(row['day']) is not int
                or not max(last_day, event['resolved_day'], event['occurred_day']+1, core.management['started_day']) <= row['day'] <= core.day):
            raise ValueError('アイテムの使用日・対象猫が不正です。')
        if any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) or not 0 <= row[k] <= 100 for k in ('before', 'after')):
            raise ValueError('アイテムによるストレス変化が不正です。')
        if row['before'] <= 0 or row['after'] != max(0, row['before']-event['item_reward']['stress_relief']):
            raise ValueError('アイテムの効果と使用結果が一致しません。')
        sources.add(row['source'])
        last_day = row['day']
    return copy.deepcopy(data)
