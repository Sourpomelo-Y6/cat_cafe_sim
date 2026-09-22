"""固定日の保護猫受け入れ依頼。新規ゲームに設定を固定して導入する。"""
import copy
import json
from pathlib import Path
from .cafe_recruitment import validate_candidates


def rules(data=None):
    if data is None:
        from .human_cat_types import load_presets
        from .cafe_traits import definitions
        row=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_intake_request.json').read_text())
        data=dict(day=row['day'],cat_id=row['cat_id'],candidate=dict(name=row['name'],cost=row['cost'],
            personality=load_presets()[row['preset']].to_dict(),trait=definitions()[row['trait']],features=row['features']))
    if not isinstance(data,dict) or set(data)!={'day','cat_id','candidate'} or type(data['day']) is not int or data['day']<1:
        raise ValueError('受け入れ依頼の設定が不正です。')
    from .human_cat_relationship import identity
    identity(data['cat_id'])
    validate_candidates({data['cat_id']:data['candidate']})
    return copy.deepcopy(data)


def pending(core):
    return bool(core.intake_request and core.intake_request['status']=='waiting')


def initialize(core,selected=None):
    core.require_events_resolved()
    selected=rules(selected)
    used=set(core.cats)|set((core.recruitment or {}).get('candidates',{}))
    if not core.compact or core.day!=1 or not core.can_set_shifts or not core.shift_rules or not core.health_rules or core.intake_request or selected['cat_id'] in used:
        raise ValueError('受け入れ依頼は新規ゲームの準備時に一度だけ設定できます。')
    core.intake_request=dict(rules=selected,status='scheduled',presented_day=None,resolved_day=None)
    core._tick_events=[]
    core._emit('intake_request_initialized')
    present(core)
    core._record(dict(kind='initialize_intake_request',rules=selected))


def present(core):
    from .cafe_management import is_over
    data=core.intake_request
    if data and data['status']=='scheduled' and core.day==data['rules']['day'] and not is_over(core):
        data.update(status='waiting',presented_day=core.day)
        core._emit('intake_request_waiting',name=data['rules']['candidate']['name'])


def require_response(core):
    core.require_events_resolved(ignore_intake=True)
    if not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules:
        raise ValueError('依頼への回答は営業準備中に行ってください。')


def resolve(core,choice):
    if choice not in ('accept','decline'):
        raise ValueError('迎えるか見送るかを選んでください。')
    core.require_running()
    data=core.intake_request
    if not data:
        raise ValueError('受け入れ依頼はありません。')
    if data['status'] in ('accepted','declined'):
        if data['status']!=('accepted' if choice=='accept' else 'declined'):
            raise ValueError('回答済みの依頼は変更できません。')
        return
    require_response(core)
    if not pending(core):
        raise ValueError('回答待ちの依頼はありません。')
    if choice=='accept':
        from .cafe_recruitment import join_cat
        join_cat(core,data['rules']['cat_id'],data['rules']['candidate'])
    data.update(status='accepted' if choice=='accept' else 'declined',resolved_day=core.day)
    core._tick_events=[]
    core._emit('intake_request_resolved',choice=choice,name=data['rules']['candidate']['name'],cat_id=data['rules']['cat_id'],cost=data['rules']['candidate']['cost'] if choice=='accept' else 0)
    core._record(dict(kind='resolve_intake_request',choice=choice))


def accepted(core):
    data=core.intake_request
    return {data['rules']['cat_id']:data['rules']['candidate']} if data and data['status']=='accepted' else {}


def expenses(core,day=None):
    data=core.intake_request
    return data['rules']['candidate']['cost'] if accepted(core) and (day is None or data['resolved_day']==day) else 0


def validate(data,day,used_ids):
    if not isinstance(data,dict) or set(data)!={'rules','status','presented_day','resolved_day'}:
        raise ValueError('受け入れ依頼の状態が不正です。')
    selected=rules(data['rules'])
    if selected['cat_id'] in used_ids:
        raise ValueError('依頼の猫IDが既存の猫・候補と重複しています。')
    if data['status']=='scheduled':
        if day>=selected['day'] or data['presented_day'] is not None or data['resolved_day'] is not None:
            raise ValueError('未発生の依頼記録が不正です。')
    elif data['status'] in ('waiting','accepted','declined'):
        if type(data['presented_day']) is not int or data['presented_day']!=selected['day'] or day<selected['day']:
            raise ValueError('依頼の発生日が不正です。')
        if data['status']=='waiting':
            if day!=selected['day'] or data['resolved_day'] is not None:
                raise ValueError('依頼への回答前に日付が進んでいます。')
        elif type(data['resolved_day']) is not int or data['resolved_day']!=selected['day']:
            raise ValueError('依頼の回答日が不正です。')
    else:
        raise ValueError('受け入れ依頼の状態が不正です。')
    return copy.deepcopy(data)
