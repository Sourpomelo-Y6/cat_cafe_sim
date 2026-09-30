"""準備中のケア用品購入。価格と効果は購入時の記録に固定する。"""
import copy
import json
import math
from pathlib import Path
from .cafe_items import definition


def rules(data=None):
    if data is None:
        data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_item_shop.json').read_text())
    if (not isinstance(data,dict) or set(data)!={'cost','item'}
            or type(data['cost']) not in (int,float) or not math.isfinite(data['cost']) or data['cost']<=0):
        raise ValueError('アイテム購入設定が不正です。')
    return dict(cost=data['cost'],item=definition(data['item']))


def reason(core,selected):
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if not core.compact or not core.can_set_shifts:return '購入は営業準備中に行ってください。'
    if core.funds<selected['cost']:return '購入する資金が足りません。'
    return ''


def purchase(core,selected):
    selected=rules(selected);problem=reason(core,selected)
    if problem:raise ValueError(problem)
    row=dict(source=f"item-purchase-{len(core.item_purchases)+1}",day=core.day,**selected)
    core.item_purchases.append(row);core.funds-=selected['cost']
    core._tick_events=[];core._emit('item_purchased',name=selected['item']['name'],cost=selected['cost'])
    from .cafe_management import check_end
    check_end(core)
    core._record(dict(kind='purchase_item',rules=selected))


def expenses(core,day=None):
    return sum(row['cost'] for row in core.item_purchases if day is None or row['day']==day)


def validate(core,data):
    if not isinstance(data,list) or not data:raise ValueError('アイテム購入記録が不正です。')
    previous=1
    for index,row in enumerate(data,1):
        if (not isinstance(row,dict) or set(row)!={'source','day','cost','item'}
                or row['source']!=f'item-purchase-{index}' or type(row['day']) is not int
                or not previous<=row['day']<=core.day):raise ValueError('アイテム購入記録が不正です。')
        rules(dict(cost=row['cost'],item=row['item']));previous=row['day']
    core.item_purchases=copy.deepcopy(data)
    for day in core.day_results:
        if day['summary'].get('item_expenses',0)!=expenses(core,day['day']):
            raise ValueError('アイテム購入費と日次結果が一致しません。')
    return core.item_purchases


def catalog():
    snack = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_nutrition_snack.json').read_text(encoding='utf-8'))
    return [rules(), rules(snack)]
