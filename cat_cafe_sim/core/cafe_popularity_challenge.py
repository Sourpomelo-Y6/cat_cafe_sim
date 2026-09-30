"""自由営業の人気集計を維持し、任意操作で3段階の挑戦を開始する。"""
import copy

CUSTOMERS=('advanced_customers','reservation','quiet_customer','play_customer','contact_customer','vip_customer')


def rules(core, selected=None):
    from . import cafe_goal, cafe_advanced_customers, cafe_reservation, cafe_quiet_customer
    from . import cafe_play_customer, cafe_contact_customer, cafe_vip_customer
    providers=dict(zip(CUSTOMERS,(cafe_advanced_customers,cafe_reservation,cafe_quiet_customer,
                                  cafe_play_customer,cafe_contact_customer,cafe_vip_customer)))
    if selected is None:
        goal=cafe_goal.progression_rules()
        for key in ('cap','gain_per_success'):goal[key]=core.goal['rules'][key]
        selected=dict(goal=goal,**{key:module.rules() for key,module in providers.items()})
    if not isinstance(selected,dict) or set(selected)!={'goal',*CUSTOMERS}:
        raise ValueError('自由営業からの人気挑戦設定が不正です。')
    goal=cafe_goal.rules(selected['goal'])
    if ('stages' not in goal or any(goal[key]!=core.goal['rules'][key] for key in ('cap','gain_per_success'))):
        raise ValueError('人気挑戦は既存の人気増加量・上限を維持してください。')
    return dict(goal=goal,**{key:module.rules(selected[key]) for key,module in providers.items()})


def reason(core):
    if core.objective!='free' or not core.goal or not core.goal.get('tracking_only'):
        return '人気への挑戦開始は、まだ挑戦していない自由営業が対象です。'
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if not core.compact or not core.can_set_shifts:
        return '人気への挑戦は営業準備中に開始してください。'
    if not core.management or core.weekdays is None or core.customer_preferences is None:
        return '人気挑戦に必要な経営・曜日・好みの設定がありません。'
    if any(getattr(core,key) is not None for key in CUSTOMERS):
        return '追加客の設定は導入済みです。'
    return ''


def start(core, selected=None):
    problem=reason(core)
    if problem:raise ValueError(problem)
    selected=rules(core,selected)
    # 検証を終えてから変更し、設定エラーでは既存の店と履歴を変更しない。
    core.goal['rules']=selected['goal']
    core.goal.pop('tracking_only')
    core.goal.update(challenge_started_day=core.day,stage_started_day=core.day,history=[])
    for key in CUSTOMERS:
        value=selected[key]
        setattr(core,key,dict(rules=value,request=None) if key=='reservation' else value)
    core._tick_events=[];core._emit('popularity_challenge_started',started_day=core.day)
    core._record(dict(kind='start_popularity_challenge',rules=copy.deepcopy(selected)))
