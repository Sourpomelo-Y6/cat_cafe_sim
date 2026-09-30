"""最初に常連になったお客さんから、一度だけ固定の猫を紹介される。"""
import copy
import json
from pathlib import Path

from .cafe_recruitment import validate_candidates
from .human_cat_relationship import identity


def rules(data=None):
    if data is None:
        from .human_cat_types import load_presets
        from .cafe_traits import definitions
        row=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_regular_introduction.json').read_text())
        data=dict(cat_id=row['cat_id'],candidate=dict(name=row['name'],cost=row['cost'],
            personality=load_presets()[row['preset']].to_dict(),trait=definitions()[row['trait']],features=row['features']))
    if not isinstance(data,dict) or set(data)!={'cat_id','candidate'}:
        raise ValueError('常連からの猫紹介設定が不正です。')
    identity(data['cat_id']); validate_candidates({data['cat_id']:data['candidate']})
    return copy.deepcopy(data)


def reserved_ids(core):
    return {core.regular_introduction['rules']['cat_id']} if core.regular_introduction else set()


def initialize(core, selected=None):
    core.require_events_resolved()
    selected=rules(selected)
    from .cafe_dispatch_introduction import reserved_ids as dispatch_ids
    used=set(core.cats)|set((core.recruitment or {}).get('candidates',{}))|set((core.pet_shop or {}).get('candidates',{}))|dispatch_ids(core)
    if core.intake_request:used.add(core.intake_request['rules']['cat_id'])
    if (not core.compact or core.day!=1 or not core.can_set_shifts or core.regular_introduction is not None
            or core.customer_loyalty is None or not core.shift_rules or not core.health_rules
            or selected['cat_id'] in used):
        raise ValueError('常連からの猫紹介は常連度・出勤・健康ルールが有効な新規開始時に設定してください。')
    core.regular_introduction=dict(rules=selected,status='untriggered',customer_id=None,
                                   regular_day=None,presented_day=None,resolved_day=None)
    core._tick_events=[]
    core._record(dict(kind='initialize_regular_introduction',rules=copy.deepcopy(selected)))


def first_regular(core):
    rows=(core.customer_loyalty or {}).get('customers',{})
    choices=sorted((row['regular_day'],key) for key,row in rows.items() if row['regular_day'] is not None)
    return choices[0] if choices else None


def pending(core):
    return bool(core.regular_introduction and core.regular_introduction['status']=='waiting')


def present(core):
    from .cafe_management import is_over
    data=core.regular_introduction; first=first_regular(core)
    if (data and data['status']=='untriggered' and first and first[0]<core.day
            and core.can_set_shifts and not is_over(core)):
        data.update(status='waiting',customer_id=first[1],regular_day=first[0],presented_day=core.day)
        core._emit('regular_introduction_waiting',customer_id=first[1],name=data['rules']['candidate']['name'])


def response_reason(core):
    try:
        core.require_events_resolved(ignore_intake=True,ignore_introductions=True,ignore_regular_introduction=True)
    except ValueError as exc:return str(exc)
    if not core.compact or not core.can_set_shifts or not pending(core):
        return '常連からの猫紹介への回答は営業準備中に行ってください。'
    return ''


def admission_reason(core):
    problem=response_reason(core)
    if problem:return problem
    from .cafe_housing import admission_reason as housing_reason
    problem=housing_reason(core)
    if problem:return problem
    if core.funds<=core.regular_introduction['rules']['candidate']['cost']:
        return '受け入れ後に資金が残る必要があります。'
    return ''


def resolve(core,choice):
    core.require_running()
    data=core.regular_introduction
    if not data or choice not in ('accept','decline'):
        raise ValueError('常連からの猫紹介で迎える／見送るを選んでください。')
    status='accepted' if choice=='accept' else 'declined'
    if data['status'] in ('accepted','declined'):
        if data['status']!=status:raise ValueError('回答済みの猫紹介は変更できません。')
        return
    problem=admission_reason(core) if choice=='accept' else response_reason(core)
    if problem:raise ValueError(problem)
    rule=data['rules']
    if choice=='accept':
        from .cafe_recruitment import join_cat
        join_cat(core,rule['cat_id'],rule['candidate'])
    data.update(status=status,resolved_day=core.day)
    core._tick_events=[]
    core._emit('regular_introduction_resolved',choice=choice,customer_id=data['customer_id'],
               cat_id=rule['cat_id'],name=rule['candidate']['name'],cost=rule['candidate']['cost'] if choice=='accept' else 0)
    core._record(dict(kind='resolve_regular_introduction',choice=choice))


def accepted(core):
    data=core.regular_introduction
    return {data['rules']['cat_id']:data['rules']['candidate']} if data and data['status']=='accepted' else {}


def expenses(core,day=None):
    data=core.regular_introduction
    return data['rules']['candidate']['cost'] if accepted(core) and (day is None or data['resolved_day']==day) else 0


def prepare(data,day,used_ids):
    if not isinstance(data,dict) or set(data)!={'rules','status','customer_id','regular_day','presented_day','resolved_day'}:
        raise ValueError('常連からの猫紹介記録が不正です。')
    selected=rules(data['rules'])
    if selected['cat_id'] in used_ids:raise ValueError('常連紹介の猫IDが既存の猫・候補と重複しています。')
    status=data['status']
    if status=='untriggered':
        if any(data[key] is not None for key in ('customer_id','regular_day','presented_day','resolved_day')):
            raise ValueError('未発生の常連紹介記録が不正です。')
    elif status in ('waiting','accepted','declined'):
        identity(data['customer_id'])
        if (type(data['regular_day']) is not int or type(data['presented_day']) is not int
                or not 1<=data['regular_day']<data['presented_day']<=day
                or data['presented_day']!=data['regular_day']+1):
            raise ValueError('常連紹介の発生日が不正です。')
        if status=='waiting':
            if data['resolved_day'] is not None or data['presented_day']!=day:
                raise ValueError('常連紹介への回答前に日付が進んでいます。')
        elif type(data['resolved_day']) is not int or data['resolved_day']!=data['presented_day']:
            raise ValueError('常連紹介の回答日が不正です。')
    else:raise ValueError('常連紹介の状態が不正です。')
    return copy.deepcopy(data)


def validate(core):
    from .cafe_management import is_over
    data=core.regular_introduction
    if data is None:return
    if core.customer_loyalty is None or not core.shift_rules or not core.health_rules:
        raise ValueError('常連紹介に必要な常連度・出勤・健康設定がありません。')
    first=first_regular(core)
    if data['status']=='untriggered':
        if first and first[0]<core.day and not is_over(core):
            raise ValueError('常連からの猫紹介が提示されていません。')
    elif first!=(data['regular_day'],data['customer_id']):
        raise ValueError('常連紹介と常連になった接客履歴が一致しません。')
    if pending(core) and not core.can_set_shifts:
        raise ValueError('常連紹介への回答前に営業が進んでいます。')
    for key,row in accepted(core).items():
        if (core.traits or {}).get(key)!=row.get('trait') or (core.cat_features or {}).get(key)!=row.get('features'):
            raise ValueError('常連紹介で加入した猫の特徴・特性が一致しません。')
