"""人気目標の最終段階クリア後に解放するVIP客。"""
import copy
import json
import math
from pathlib import Path

CUSTOMER_ID = 'vip-calico'
NAME = '三毛猫との特別な時間を望むVIP客'


def rules(data=None):
    if data is None:
        data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_vip_customer.json').read_text())
    fields={'feature','connect_count','open_up_count','simultaneous_count','bonus','popularity_bonus'}
    if not isinstance(data,dict) or set(data)!=fields or data['feature']!='calico':
        raise ValueError('VIP客の設定が不正です。')
    for key in ('connect_count','open_up_count','simultaneous_count'):
        if type(data[key]) is not int or data[key]<1:raise ValueError('VIP客の設定が不正です。')
    for key in ('bonus','popularity_bonus'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0:
            raise ValueError('VIP客の設定が不正です。')
    return copy.deepcopy(data)


def initialize(core,selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.vip_customer is not None
            or not core.goal or core.goal.get('tracking_only') or 'stages' not in core.goal['rules']):
        raise ValueError('VIP客は段階式人気目標の新規ゲームに設定してください。')
    core.vip_customer=rules(selected);core._tick_events=[]
    core._record(dict(kind='initialize_vip_customer',rules=copy.deepcopy(core.vip_customer)))


def unlocked_day(core):
    if core.vip_customer is None or not core.goal:return None
    # 最終段階は、先行2段階が履歴に入り、現在段階がクリアされた状態。
    if len(core.goal.get('history',[]))==2 and core.goal['status']=='cleared':return core.goal['resolved_day']
    return None


def schedule(core,day):
    unlocked=unlocked_day(core)
    return {CUSTOMER_ID:0} if unlocked is not None and day>unlocked else {}


def evaluate(core,result):
    if core.vip_customer is None or result['customer_id']!=CUSTOMER_ID:return None
    selected=core.vip_customer
    matched=selected['feature'] in (core.cat_features or {}).get(result['cat_id'],[])
    success=(matched and result['connect_count']>=selected['connect_count']
             and result['open_up_count']>=selected['open_up_count']
             and result['simultaneous_count']>=selected['simultaneous_count'])
    return dict(matched=matched,connect_count=result['connect_count'],open_up_count=result['open_up_count'],
                simultaneous_count=result['simultaneous_count'],success=success,
                bonus=selected['bonus'] if success else 0)


def result_text(core,result):
    row=evaluate(core,result);selected=core.vip_customer
    return (f"{'達成' if row['success'] else '未達'}：三毛猫{'一致' if row['matched'] else '不一致'}"
            f"・心をつかむ {row['connect_count']}/{selected['connect_count']}回"
            f"・心を開く {row['open_up_count']}/{selected['open_up_count']}回"
            f"・同時発動 {row['simultaneous_count']}/{selected['simultaneous_count']}回"
            f"・追加料金 {row['bonus']:g}")


def description(core):
    selected=core.vip_customer
    if selected is None:return ''
    day=unlocked_day(core);status='最終段階達成で解放' if day is None else f'{day}日目に解放・{day+1}日目から営業日に1名'
    return (f"{NAME}：{status}。三毛猫を担当にし、心をつかむ・心を開くを各1回以上、"
            f"同時発動を1回以上達成すると追加料金＋{selected['bonus']:g}・人気＋{selected['popularity_bonus']:g}。")


def popularity_bonus(core,outcome):
    value=evaluate(core,outcome)
    return core.vip_customer['popularity_bonus'] if value and value['success'] else 0


def validate(core,data):
    selected=rules(data);core.vip_customer=selected
    if not core.goal or core.goal.get('tracking_only') or 'stages' not in core.goal['rules']:
        raise ValueError('VIP客の人気目標設定がありません。')
    from .cafe_checkpoint import outcome_result
    rows=[outcome_result(value) for value in core.outcomes.values()];offset=0
    for day in core.day_results+[dict(day=core.day,summary=core.summary())]:
        count=day['summary']['completed_interactions']
        for result in rows[offset:offset+count]:
            if result['customer_id']==CUSTOMER_ID and CUSTOMER_ID not in schedule(core,day['day']):
                raise ValueError('解放前のVIP客の接客記録があります。')
        offset+=count
    return selected
