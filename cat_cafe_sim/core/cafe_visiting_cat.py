"""店先に通う猫と1日1回交流し、慣れた後に任意で迎える。"""
import copy
import json
from pathlib import Path

from .cafe_recruitment import validate_candidates
from .human_cat_relationship import identity


def rules(data=None):
    if data is None:
        from .human_cat_types import load_presets
        from .cafe_traits import definitions
        row=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_visiting_cat.json').read_text())
        data=dict(cat_id=row['cat_id'],interactions_required=row['interactions_required'],
            candidate=dict(name=row['name'],cost=row['cost'],personality=load_presets()[row['preset']].to_dict(),
                           trait=definitions()[row['trait']],features=row['features']))
    if (not isinstance(data,dict) or set(data)!={'cat_id','candidate','interactions_required'}
            or type(data['interactions_required']) is not int or data['interactions_required']<1):
        raise ValueError('店先に通う猫の設定が不正です。')
    identity(data['cat_id']); validate_candidates({data['cat_id']:data['candidate']})
    return copy.deepcopy(data)


def reserved_ids(core):
    return {core.visiting_cat['rules']['cat_id']} if core.visiting_cat else set()


def initialize(core,selected=None):
    core.require_events_resolved(); selected=rules(selected)
    from .cafe_dispatch_introduction import reserved_ids as dispatch_ids
    from .cafe_regular_introduction import reserved_ids as regular_ids
    used=set(core.cats)|set((core.recruitment or {}).get('candidates',{}))|set((core.pet_shop or {}).get('candidates',{}))|dispatch_ids(core)|regular_ids(core)
    if core.intake_request:used.add(core.intake_request['rules']['cat_id'])
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.visiting_cat is not None
            or not core.goal or not core.shift_rules or not core.health_rules or selected['cat_id'] in used):
        raise ValueError('店先に通う猫は人気・出勤・健康ルールのある新規ゲームの準備中に設定してください。')
    core.visiting_cat=dict(rules=selected,status='untriggered',presented_day=None,actions=[],accepted_day=None)
    core._tick_events=[]; core._record(dict(kind='initialize_visiting_cat',rules=copy.deepcopy(selected)))


def unlocked_day(core):
    goal=core.goal
    if not goal or goal.get('tracking_only'):return None
    first=(goal.get('history') or [goal])[0]
    return first['resolved_day'] if first['status']=='cleared' else None


def present(core):
    from .cafe_management import is_over
    data=core.visiting_cat; day=unlocked_day(core)
    if (data and data['status']=='untriggered' and day is not None and day<core.day
            and core.can_set_shifts and not is_over(core)):
        data.update(status='visiting',presented_day=core.day)
        core._emit('visiting_cat_presented',name=data['rules']['candidate']['name'])


def progress(core):
    return sum(row['choice']=='interact' for row in core.visiting_cat['actions']) if core.visiting_cat else 0


def response_reason(core):
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if not core.compact or not core.can_set_shifts:
        return '店先の猫との交流・加入は営業準備中に行ってください。'
    if not core.visiting_cat or core.visiting_cat['status'] not in ('visiting','ready'):
        return '交流できる店先の猫はいません。'
    return ''


def daily_reason(core):
    problem=response_reason(core)
    if problem:return problem
    if any(row['day']==core.day for row in core.visiting_cat['actions']):
        return '今日は交流または見送り済みです。次の準備日に会えます。'
    return ''


def admission_reason(core):
    problem=response_reason(core)
    if problem:return problem
    if core.visiting_cat['status']!='ready':
        return f"迎えるには店先で{core.visiting_cat['rules']['interactions_required']}回の交流が必要です。"
    from .cafe_housing import admission_reason as housing_reason
    problem=housing_reason(core)
    if problem:return problem
    if core.funds<=core.visiting_cat['rules']['candidate']['cost']:
        return '受け入れ後に資金が残る必要があります。'
    return ''


def resolve(core,choice):
    core.require_running(); data=core.visiting_cat
    if not data or choice not in ('interact','skip','accept'):raise ValueError('店先の猫と交流する／今日は見送る／迎えるを選んでください。')
    if choice=='accept' and data['status']=='accepted':return
    problem=admission_reason(core) if choice=='accept' else daily_reason(core)
    if problem:raise ValueError(problem)
    if choice=='interact' and data['status']=='ready':raise ValueError('十分に慣れています。迎えるか、今日は見送ることができます。')
    if choice=='accept':
        from .cafe_recruitment import join_cat
        rule=data['rules']; join_cat(core,rule['cat_id'],rule['candidate'])
        data.update(status='accepted',accepted_day=core.day)
    else:
        data['actions'].append(dict(day=core.day,choice=choice))
        if progress(core)>=data['rules']['interactions_required']:data['status']='ready'
    core._tick_events=[]
    core._emit('visiting_cat_resolved',choice=choice,cat_id=data['rules']['cat_id'],name=data['rules']['candidate']['name'],
               progress=progress(core),required=data['rules']['interactions_required'],cost=data['rules']['candidate']['cost'] if choice=='accept' else 0)
    core._record(dict(kind='resolve_visiting_cat',choice=choice))


def accepted(core):
    data=core.visiting_cat
    return {data['rules']['cat_id']:data['rules']['candidate']} if data and data['status']=='accepted' else {}


def expenses(core,day=None):
    data=core.visiting_cat
    return data['rules']['candidate']['cost'] if accepted(core) and (day is None or data['accepted_day']==day) else 0


def prepare(data,day,used_ids):
    if (not isinstance(data,dict) or set(data)!={'rules','status','presented_day','actions','accepted_day'}
            or not isinstance(data['actions'],list)):
        raise ValueError('店先に通う猫の記録が不正です。')
    selected=rules(data['rules'])
    if selected['cat_id'] in used_ids:raise ValueError('店先の猫IDが既存の猫・候補と重複しています。')
    status=data['status']; presented=data['presented_day']; joined=data['accepted_day']
    if status=='untriggered':
        if presented is not None or joined is not None or data['actions']:raise ValueError('未出現の店先の猫に交流・加入記録があります。')
    elif status in ('visiting','ready','accepted'):
        if type(presented) is not int or not 1<=presented<=day:raise ValueError('店先の猫の出現日が不正です。')
        previous=presented-1; count=0
        for row in data['actions']:
            if (not isinstance(row,dict) or set(row)!={'day','choice'} or type(row['day']) is not int
                    or not previous<row['day']<=day or row['choice'] not in ('interact','skip')
                    or (row['choice']=='interact' and count>=selected['interactions_required'])):
                raise ValueError('店先の猫の1日1回の交流記録が不正です。')
            previous=row['day']; count+=row['choice']=='interact'
        if (status=='visiting')!=(count<selected['interactions_required']):raise ValueError('店先の猫の交流回数と状態が一致しません。')
        if status=='accepted':
            if type(joined) is not int or not max(presented,previous)<=joined<=day:raise ValueError('店先の猫の加入日が不正です。')
        elif joined is not None:raise ValueError('加入前の店先の猫に加入日があります。')
    else:raise ValueError('店先の猫の状態が不正です。')
    return copy.deepcopy(data)


def validate(core):
    from .cafe_management import is_over
    data=core.visiting_cat
    if data is None:return
    if not core.goal or not core.shift_rules or not core.health_rules:raise ValueError('店先の猫に必要な人気・出勤・健康設定がありません。')
    day=unlocked_day(core)
    if data['status']=='untriggered':
        if day is not None and day<core.day and not is_over(core):raise ValueError('人気達成後の店先の猫が出現していません。')
    elif day is None or data['presented_day']!=day+1:raise ValueError('店先の猫と人気達成日が一致しません。')
    for key,row in accepted(core).items():
        if (core.traits or {}).get(key)!=row.get('trait') or (core.cat_features or {}).get(key)!=row.get('features'):
            raise ValueError('店先から加入した猫の特徴・特性が一致しません。')
