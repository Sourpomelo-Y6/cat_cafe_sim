"""未使用の所持品を1個ずつ売却し、収入を売却時に固定する。"""
import copy
import json
import math
from pathlib import Path


def prices():
    data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_item_sales.json').read_text(encoding='utf-8'))
    legacy={'care_supplies','nutrition_snack'}
    if not isinstance(data, dict) or set(data) not in (legacy,legacy|{'special_care_set'}):
        raise ValueError('アイテム売却価格の設定が不正です。')
    for value in data.values():
        validate_price(value)
    return data


def validate_price(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('アイテム売却価格は有限の正数で指定してください。')


def reason(core, source):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts:
        return 'アイテム売却は営業準備中に行ってください。'
    from .cafe_items import inventory
    if source not in inventory(core):
        return '未使用の所持品を選んでください。'
    return ''


def sell(core, source, price):
    validate_price(price)
    problem = reason(core, source)
    if problem:
        raise ValueError(problem)
    if not math.isfinite(core.funds + price):
        raise ValueError('売却後の資金が大きすぎます。')
    from .cafe_items import inventory
    item = inventory(core)[source]
    core.item_sales.append(dict(source=source, day=core.day, price=price))
    core.funds += price
    core._tick_events = []
    core._emit('item_sold', name=item['name'], price=price)
    core._record(dict(kind='sell_item', source=source, price=price))


def income(core, day=None):
    return sum(row['price'] for row in core.item_sales if day is None or row['day'] == day)


def validate(core, data):
    if not isinstance(data, list) or not data:
        raise ValueError('アイテム売却記録が不正です。')
    from .cafe_items import reward_for_source
    consumed = {row['source'] for row in core.item_uses}
    last_day = 1
    for row in data:
        if not isinstance(row, dict) or set(row) != {'source', 'day', 'price'} or not isinstance(row['source'], str):
            raise ValueError('アイテム売却の項目が不正です。')
        reward = reward_for_source(core, row['source'])
        if not reward or row['source'] in consumed:
            raise ValueError('未受取・使用済み・売却済みのアイテムが売却されています。')
        if type(row['day']) is not int or not max(last_day, reward['available_day']) <= row['day'] <= core.day:
            raise ValueError('アイテム売却日が不正です。')
        validate_price(row['price'])
        consumed.add(row['source'])
        last_day = row['day']
    core.item_sales = copy.deepcopy(data)
    for result in core.day_results:
        if result['summary'].get('item_sales_income', 0) != income(core, result['day']):
            raise ValueError('用品売却収入と日次結果が一致しません。')
    return core.item_sales
