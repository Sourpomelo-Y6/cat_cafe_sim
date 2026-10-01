"""人気第2段階から日付ごとに確率来店する長毛好きの触れ合い客。"""
import copy
import hashlib
import json
import math
from pathlib import Path

CUSTOMER_ID='advanced-longhair'
NAME='気まぐれな長毛好きのお客さん'


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_longhair_customer.json').read_text())
    if (not isinstance(data,dict) or set(data)!={'probability','contact_count','bonus','popularity_bonus'}
            or type(data['contact_count']) is not int or data['contact_count']<1):
        raise ValueError('長毛好き客の条件が不正です。')
    for key in ('probability','bonus','popularity_bonus'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0:
            raise ValueError('長毛好き客の報酬・確率が不正です。')
    if data['probability']>1:raise ValueError('来店確率は1以下で指定してください。')
    return copy.deepcopy(data)


def initialize(core,selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.longhair_customer is not None
            or core.weekdays is None or not core.goal or core.goal.get('tracking_only')
            or 'stages' not in core.goal['rules'] or core.goal['status']!='active'):
        raise ValueError('長毛好き客は人気3段階の新規ゲームに設定してください。')
    core.longhair_customer=rules(selected)
    core._tick_events=[];core._record(dict(kind='initialize_longhair_customer',rules=copy.deepcopy(core.longhair_customer)))


def applies(core,customer_id):
    return getattr(core,'longhair_customer',None) is not None and customer_id==CUSTOMER_ID


def unlocked_day(core):
    if getattr(core,'longhair_customer',None) is None or not core.goal:return None
    stages=[*core.goal.get('history',[]),core.goal]
    return stages[1]['resolved_day'] if len(stages)>1 and stages[1]['status']=='cleared' else None


def draw(seed,day):
    raw=hashlib.sha256(f'longhair-customer:{seed}:{day}'.encode()).digest()
    return int.from_bytes(raw[:8],'big')/2**64


def schedule(core,day):
    unlocked=unlocked_day(core)
    return {CUSTOMER_ID:0} if unlocked is not None and day>unlocked and draw(core.seed,day)<core.longhair_customer['probability'] else {}


def evaluate(core,result):
    if not applies(core,result['customer_id']):return None
    from .cafe_growth import TYPE_GROUPS
    count=sum(result['type_actions'][key] for key,group in TYPE_GROUPS.items() if group=='contact')
    matched='long_hair' in (core.cat_features or {}).get(result['cat_id'],[])
    success=matched and count>=core.longhair_customer['contact_count']
    return dict(matched=matched,contact_count=count,success=success,bonus=core.longhair_customer['bonus'] if success else 0)


def popularity_bonus(core,result):
    row=evaluate(core,result)
    return core.longhair_customer['popularity_bonus'] if row and row['success'] else 0


def result_text(core,result):
    row=evaluate(core,result)
    return f"{'達成' if row['success'] else '未達'}：長毛{'一致' if row['matched'] else '不一致'}・触れ合い {row['contact_count']}/{core.longhair_customer['contact_count']}回・追加料金 {row['bonus']:g}・追加人気 {popularity_bonus(core,result):g}"


def description(core):
    if getattr(core,'longhair_customer',None) is None:return ''
    day=unlocked_day(core);r=core.longhair_customer
    status='人気第2段階達成で解放' if day is None else f'{day}日目に解放・翌日以降'
    return f"{NAME}：{status}、営業日に{r['probability']*100:g}％で1名。長毛猫との通常の触れ合い{r['contact_count']}回以上で追加料金＋{r['bonus']:g}・人気＋{r['popularity_bonus']:g}。"


def validate(core,data):
    core.longhair_customer=rules(data)
    if core.weekdays is None or not core.goal or core.goal.get('tracking_only') or 'stages' not in core.goal['rules'] or core.goal['started_day']!=1:
        raise ValueError('長毛好き客の人気目標設定がありません。')
    from .cafe_checkpoint import outcome_result
    rows=[outcome_result(v) for v in core.outcomes.values()];offset=0
    for day in core.day_results+[dict(day=core.day,summary=core.summary())]:
        count=day['summary']['completed_interactions']
        for result in rows[offset:offset+count]:
            if result['customer_id']==CUSTOMER_ID:
                if CUSTOMER_ID not in schedule(core,day['day']):raise ValueError('解放・抽選条件外の長毛好き客の記録があります。')
                evaluate(core,result)
        offset+=count
    return core.longhair_customer
