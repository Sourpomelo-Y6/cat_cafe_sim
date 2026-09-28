"""人気第2段階で解放する、翌日1件の特別予約。"""
import copy
import json
import math
from pathlib import Path

CUSTOMER_ID='reservation-longhair'
NAME='長毛猫との時間を望む予約客'


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_reservation.json').read_text())
    if (not isinstance(data,dict) or set(data)!={'feature','open_up_count','arrival_tick','bonus','popularity_bonus'}
            or data['feature']!='long_hair' or type(data['open_up_count']) is not int or data['open_up_count']<1
            or type(data['arrival_tick']) is not int or data['arrival_tick']<0):
        raise ValueError('特別予約の設定が不正です。')
    for key in ('bonus','popularity_bonus'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0:raise ValueError('特別予約の設定が不正です。')
    return copy.deepcopy(data)


def initialize(core,selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.reservation is not None
            or not core.goal or core.goal.get('tracking_only') or 'stages' not in core.goal['rules']):
        raise ValueError('特別予約は段階式人気目標の新規ゲームに設定してください。')
    core.reservation=dict(rules=rules(selected),request=None)
    core._tick_events=[];core._record(dict(kind='initialize_reservation',rules=core.reservation['rules']))


def second_cleared_day(core):
    if core.reservation is None or not core.goal:return None
    history=core.goal.get('history',[])
    if len(history)>=2:return history[1]['resolved_day']
    if len(history)==1 and core.goal['status']=='cleared':return core.goal['resolved_day']
    return None


def waiting(core):
    request=(core.reservation or {}).get('request')
    return request if request and request['status']=='waiting' else None


def present(core):
    data=core.reservation
    if data is None:return
    request=data['request']
    if request and request['status']=='accepted' and request['visit_day']<core.day and request['result'] is None:
        request['result']='unserved';core._emit('reservation_unserved',customer_id=CUSTOMER_ID)
    unlocked=second_cleared_day(core)
    if unlocked is None or data['request'] is not None or core.day<=unlocked:return
    data['request']=dict(id=f'reservation-{core.day}',offered_day=core.day,visit_day=core.day+1,
                        status='waiting',choice=None,resolved_day=None,result=None,session_id=None)
    core._emit('reservation_offered',visit_day=core.day+1,customer_id=CUSTOMER_ID)


def resolve(core,choice):
    core.require_running();request=waiting(core)
    if request is None or choice not in ('accept','decline'):raise ValueError('特別予約の依頼と回答を確認してください。')
    if not core.can_set_shifts:raise ValueError('特別予約は営業準備中に回答してください。')
    request.update(status='accepted' if choice=='accept' else 'declined',choice=choice,resolved_day=core.day)
    core._tick_events=[];core._emit('reservation_resolved',choice=choice,visit_day=request['visit_day'])
    core._record(dict(kind='resolve_reservation',choice=choice))


def schedule(core,day):
    request=(core.reservation or {}).get('request')
    return {CUSTOMER_ID:core.reservation['rules']['arrival_tick']} if request and request['status']=='accepted' and request['visit_day']==day else {}


def evaluate(core,result):
    if core.reservation is None or result['customer_id']!=CUSTOMER_ID:return None
    selected=core.reservation['rules'];matched=selected['feature'] in (core.cat_features or {}).get(result['cat_id'],[])
    success=matched and result['open_up_count']>=selected['open_up_count']
    return dict(matched=matched,open_up_count=result['open_up_count'],success=success,bonus=selected['bonus'] if success else 0)


def apply_result(core,result,evaluation):
    if evaluation is None:return
    request=core.reservation['request']
    if request['result'] is not None:raise ValueError('特別予約の接客結果は確定済みです。')
    request.update(result='success' if evaluation['success'] else 'failure',session_id=result['session_id'])
    core._emit('reservation_result',success=evaluation['success'],bonus=evaluation['bonus'],customer_id=CUSTOMER_ID)


def popularity_bonus(core,outcome):
    value=evaluate(core,outcome)
    return core.reservation['rules']['popularity_bonus'] if value and value['success'] else 0


def day_off_reason(core):
    request=(core.reservation or {}).get('request')
    return '受け入れた特別予約があるため休業できません。' if request and request['status']=='accepted' and request['visit_day']==core.day else ''


def prepare(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','request'}:raise ValueError('特別予約の記録が不正です。')
    selected=rules(data['rules']);request=data['request']
    if request is not None:
        fields={'id','offered_day','visit_day','status','choice','resolved_day','result','session_id'}
        if (not isinstance(request,dict) or set(request)!=fields or type(request['offered_day']) is not int
                or request['id']!=f"reservation-{request['offered_day']}" or request['visit_day']!=request['offered_day']+1
                or not 1<=request['offered_day']<=core.day or request['status'] not in ('waiting','accepted','declined')):
            raise ValueError('特別予約の依頼記録が不正です。')
        if request['status']=='waiting' and any(request[key] is not None for key in ('choice','resolved_day','result','session_id')):raise ValueError('未回答の特別予約が不正です。')
        if request['status']=='declined' and (request['choice']!='decline' or request['resolved_day']!=request['offered_day'] or request['result'] is not None or request['session_id'] is not None):raise ValueError('見送った特別予約が不正です。')
        if request['status']=='accepted' and (request['choice']!='accept' or request['resolved_day']!=request['offered_day'] or request['result'] not in (None,'success','failure','unserved')):raise ValueError('受け入れた特別予約が不正です。')
        if request['status']=='accepted':
            if request['result'] is None and (request['session_id'] is not None or core.day>request['visit_day']):raise ValueError('未確定の特別予約が不正です。')
            if request['result']=='unserved' and (request['session_id'] is not None or core.day<=request['visit_day']):raise ValueError('未接客の特別予約が不正です。')
            if request['result'] in ('success','failure') and not isinstance(request['session_id'],str):raise ValueError('特別予約の接客IDが不正です。')
    return dict(rules=selected,request=copy.deepcopy(request))


def validate(core,data):
    data=prepare(core,data);core.reservation=data;request=data['request'];unlocked=second_cleared_day(core)
    if request and (unlocked is None or request['offered_day']<=unlocked):raise ValueError('解放前の特別予約があります。')
    if request and request['result'] in ('success','failure'):
        if request['session_id'] not in core.outcomes:raise ValueError('特別予約の接客成果がありません。')
        from .cafe_checkpoint import outcome_result
        result=outcome_result(core.outcomes[request['session_id']]);value=evaluate(core,result)
        if result['customer_id']!=CUSTOMER_ID or request['result']!=('success' if value['success'] else 'failure'):raise ValueError('特別予約の結果が接客成果と一致しません。')
    return data
