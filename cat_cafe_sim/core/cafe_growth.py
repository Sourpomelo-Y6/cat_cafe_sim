"""猫の活動経験、得意分野・分類熟練・個別行動熟練。"""
import copy
import json
import math
from pathlib import Path

SPECIALIZATIONS=('service','rest','dispatch')
LABELS={'service':'接客','rest':'休養','dispatch':'派遣'}
MASTERY_GROUPS=('play','contact','quiet')
GROUP_LABELS={'play':'遊び','contact':'触れ合い','quiet':'静かな交流'}
TYPE_GROUPS={'teaser':'play','ball':'play','plush':'play','tunnel':'play',
             'pet':'contact','brush':'contact','voice':'quiet','presence':'quiet'}


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_growth.json').read_text())
    legacy={'threshold','service_xp','rest_xp','dispatch_xp','service_stamina_refund','rest_recovery_bonus','dispatch_reward_multiplier'}
    fields=legacy|{'mastery_threshold','mastery_engagement_multiplier'}
    individual=fields|{'type_mastery_threshold','type_mastery_engagement_multiplier'}
    if (not isinstance(data,dict) or set(data) not in (legacy,fields,individual) or type(data['threshold']) is not int or data['threshold']<1
            or ('mastery_threshold' in data and (type(data['mastery_threshold']) is not int or data['mastery_threshold']<1))
            or ('type_mastery_threshold' in data and (type(data['type_mastery_threshold']) is not int or data['type_mastery_threshold']<1))
            or any(type(data[k]) not in (int,float) or not math.isfinite(data[k]) or data[k]<=0 for k in set(data)-{'threshold','mastery_threshold','type_mastery_threshold'})
            or not 0<data['service_stamina_refund']<1):raise ValueError('猫の成長設定が不正です。')
    if 'mastery_engagement_multiplier' in data and not 1<data['mastery_engagement_multiplier']<=2:
        raise ValueError('猫の成長設定が不正です。')
    if 'type_mastery_engagement_multiplier' in data and not 1<data['type_mastery_engagement_multiplier']<=2:
        raise ValueError('猫の個別行動熟練設定が不正です。')
    return copy.deepcopy(data)


def blank(selected=None):
    row=dict(service=0,rest=0,dispatch=0,type_actions=dict.fromkeys(TYPE_GROUPS,0),
             groups=dict.fromkeys(MASTERY_GROUPS,0),specialization=None,selected_day=None)
    if selected is not None and 'mastery_threshold' in selected:
        row.update(mastery_groups=dict.fromkeys(MASTERY_GROUPS,0),mastery=None,mastery_selected_day=None)
    if selected is not None and 'type_mastery_threshold' in selected:
        row.update(type_mastery_actions=dict.fromkeys(TYPE_GROUPS,0),type_mastery=None,type_mastery_selected_day=None)
    return row


def initialize(core,selected=None):
    core.require_events_resolved()
    if not core.compact or core.day!=1 or not core.can_set_shifts or core.growth is not None:
        raise ValueError('猫の成長は新規ゲームの準備中に設定してください。')
    selected=rules(selected);core.growth=dict(rules=selected,cats={key:blank(selected) for key in core.cats})
    core._tick_events=[];core._emit('growth_initialized');core._record(dict(kind='initialize_growth',rules=core.growth['rules']))


def ensure_cat(core,cat_id):
    if core.growth is not None and cat_id not in core.growth['cats']:core.growth['cats'][cat_id]=blank(core.growth['rules'])


def total(row):return row['service']+row['rest']+row['dispatch']


def summary(core,cat_id):
    """Return a short growth label suitable for cat-selection tables."""
    growth=getattr(core,'growth',None)
    if growth is None:return '未導入'
    row=growth['cats'].get(cat_id)
    if row is None:return '記録なし'
    if row.get('type_mastery') is not None:
        return f"得意：接客・{GROUP_LABELS[row['mastery']]}・{type_label(row['type_mastery'])}"
    if row.get('mastery') is not None:return f"得意：接客・{GROUP_LABELS[row['mastery']]}"
    if row['specialization'] is not None:return f"得意：{LABELS[row['specialization']]}"
    return f"経験 {total(row):g}/{growth['rules']['threshold']:g}"


def description(core,cat_id):
    """Describe progress, service practice, and the currently active effect."""
    growth=getattr(core,'growth',None)
    if growth is None:return '成長ルールは未導入です。'
    row=growth['cats'].get(cat_id)
    if row is None:return 'この猫の成長記録はありません。'
    selected=growth['rules'];value=total(row)
    progress=(f"経験 {value:g}（接客 {row['service']:g} / 休養 {row['rest']:g} / 派遣 {row['dispatch']:g}）")
    practice=(f"接客実績：遊び {row['groups']['play']:g} / 触れ合い {row['groups']['contact']:g} / "
              f"静かな交流 {row['groups']['quiet']:g}")
    specialization=row['specialization']
    mastery=''
    if 'mastery_groups' in row:
        qualified=sum(row['mastery_groups'].values())
        if row['mastery'] is not None:
            mastery=(f"\n得意な交流：{GROUP_LABELS[row['mastery']]}（関心の通常増加×"
                     f"{selected['mastery_engagement_multiplier']:g}）")
        elif specialization=='service':
            mastery=f"\n接客熟練まであと {max(0,selected['mastery_threshold']-qualified):g}（親しみが増えた接客のみ）"
    if specialization=='service':effect=f"得意：接客（接客終了時に消費体力の{selected['service_stamina_refund']*100:g}%を回復）"
    elif specialization=='rest':effect=f"得意：休養（在店休養時の疲労回復＋{selected['rest_recovery_bonus']:g}）"
    elif specialization=='dispatch':effect=f"得意：派遣（派遣報酬×{selected['dispatch_reward_multiplier']:g}）"
    else:effect=(f"得意分野まであと {max(0,selected['threshold']-value):g}"
                 if value<selected['threshold'] else '得意分野を選択できます。')
    individual=''
    if 'type_mastery_actions' in row and row['mastery'] is not None:
        if row['type_mastery'] is not None:
            individual=f"\n得意な行動：{type_label(row['type_mastery'])}（関心の通常増加×{selected['type_mastery_engagement_multiplier']:g}）"
        else:
            remaining=max(0,selected['type_mastery_threshold']-sum(row['type_mastery_actions'].values()))
            individual=f"\n個別行動熟練まであと {remaining:g}（分類習得後、得意分類で親しみが増えた接客のみ）"
    return f'{progress} / {effect}\n{practice}{mastery}{individual}'


def pending(core):
    if core.growth is None:return []
    threshold=core.growth['rules']['threshold']
    return [key for key,row in core.growth['cats'].items() if row['specialization'] is None and total(row)>=threshold]


def mastery_pending(core):
    if core.growth is None or 'mastery_threshold' not in core.growth['rules']:return []
    threshold=core.growth['rules']['mastery_threshold']
    return [key for key,row in core.growth['cats'].items()
            if row['specialization']=='service' and row['mastery'] is None
            and sum(row['mastery_groups'].values())>=threshold]


def mastery_choices(core,cat_id):
    if cat_id not in mastery_pending(core):return ()
    row=core.growth['cats'][cat_id]
    return tuple(group for group in MASTERY_GROUPS if row['mastery_groups'][group]>0)


def type_label(type_id):
    from .human_cat_types import default_types
    return next(row.name for row in default_types() if row.id==type_id)


def type_mastery_pending(core):
    if core.growth is None or 'type_mastery_threshold' not in core.growth['rules']:return []
    threshold=core.growth['rules']['type_mastery_threshold']
    return [key for key,row in core.growth['cats'].items()
            if row['mastery'] is not None and row['type_mastery'] is None
            and sum(row['type_mastery_actions'].values())>=threshold]


def type_mastery_choices(core,cat_id):
    if cat_id not in type_mastery_pending(core):return ()
    row=core.growth['cats'][cat_id]
    return tuple(key for key,group in TYPE_GROUPS.items()
                 if group==row['mastery'] and row['type_mastery_actions'][key]>0)


def _gain(core,cat_id,field,amount):
    if core.growth is None:return
    ensure_cat(core,cat_id);row=core.growth['cats'][cat_id];was=total(row)>=core.growth['rules']['threshold']
    row[field]+=amount
    if not was and total(row)>=core.growth['rules']['threshold']:
        core._emit('growth_ready',cat_id=cat_id,total=total(row))


def service(core,result):
    if core.growth is None:return
    cat_id=result['cat_id'];_gain(core,cat_id,'service',core.growth['rules']['service_xp']);row=core.growth['cats'][cat_id]
    mastery_before=sum(row.get('mastery_groups',{}).values())
    individual_before=sum(row.get('type_mastery_actions',{}).values())
    for key,count in result.get('type_actions',{}).items():
        if key in row['type_actions']:
            row['type_actions'][key]+=count;row['groups'][TYPE_GROUPS[key]]+=count
            if 'mastery_groups' in row and result.get('affinity_delta',0)>0:
                row['mastery_groups'][TYPE_GROUPS[key]]+=count
            if ('type_mastery_actions' in row and row['mastery']==TYPE_GROUPS[key]
                    and result.get('affinity_delta',0)>0):
                row['type_mastery_actions'][key]+=count
    if ('mastery_groups' in row and row['specialization']=='service' and row['mastery'] is None
            and mastery_before<core.growth['rules']['mastery_threshold']
            and sum(row['mastery_groups'].values())>=core.growth['rules']['mastery_threshold']):
        core._emit('growth_mastery_ready',cat_id=cat_id,total=sum(row['mastery_groups'].values()))
    if ('type_mastery_actions' in row and row['mastery'] is not None and row['type_mastery'] is None
            and individual_before<core.growth['rules']['type_mastery_threshold']
            and sum(row['type_mastery_actions'].values())>=core.growth['rules']['type_mastery_threshold']):
        core._emit('growth_type_mastery_ready',cat_id=cat_id,total=sum(row['type_mastery_actions'].values()))
    if row['specialization']=='service':
        refund=result['stamina_spent']*core.growth['rules']['service_stamina_refund']
        core.cats[cat_id].stamina=min(core.config.max_stamina,core.cats[cat_id].stamina+refund)
        core._emit('growth_service_effect',cat_id=cat_id,stamina_refund=refund)


def rest_day(core):
    if core.growth is None:return
    for key in core.cats:
        if core.activity(key)=='cafe' and key not in core.working_cats:_gain(core,key,'rest',core.growth['rules']['rest_xp'])


def dispatch_return(core,cat_id):
    if core.growth is not None:_gain(core,cat_id,'dispatch',core.growth['rules']['dispatch_xp'])


def day_gain(core,cat_id):
    if core.growth is None:return None
    from .cafe_checkpoint import outcome_result
    service_count=sum(outcome_result(value)['cat_id']==cat_id for value in list(core.outcomes.values())[core.day_outcome_offset:])
    location=(core.activities or {}).get('day_locations',{}).get(cat_id,core.activity(cat_id))
    rest_count=int(location=='cafe' and cat_id not in core.working_cats)
    dispatch_count=sum(e['cat_id']==cat_id and e['status']=='resolved' and e['resolved_day']==core.day
                       for e in (core.activities or {}).get('events',{}).values())
    selected=core.growth['rules']
    return dict(service=service_count*selected['service_xp'],rest=rest_count*selected['rest_xp'],
                dispatch=dispatch_count*selected['dispatch_xp'])


def resolve(core,cat_id,choice):
    core.require_running()
    if cat_id not in pending(core) or choice not in SPECIALIZATIONS:raise ValueError('成長できる猫と得意分野を選んでください。')
    row=core.growth['cats'][cat_id];row.update(specialization=choice,selected_day=core.day)
    core._tick_events=[];core._emit('growth_selected',cat_id=cat_id,specialization=choice,label=LABELS[choice])
    core._record(dict(kind='resolve_growth',cat_id=cat_id,choice=choice))


def resolve_mastery(core,cat_id,choice):
    core.require_running()
    if choice not in mastery_choices(core,cat_id):raise ValueError('熟練できる猫と接客分類を選んでください。')
    row=core.growth['cats'][cat_id];row.update(mastery=choice,mastery_selected_day=core.day)
    core._tick_events=[];core._emit('growth_mastery_selected',cat_id=cat_id,mastery=choice,label=GROUP_LABELS[choice])
    core._record(dict(kind='resolve_growth_mastery',cat_id=cat_id,choice=choice))


def resolve_type_mastery(core,cat_id,choice):
    core.require_running()
    if choice not in type_mastery_choices(core,cat_id):raise ValueError('熟練できる猫と個別行動を選んでください。')
    row=core.growth['cats'][cat_id];row.update(type_mastery=choice,type_mastery_selected_day=core.day)
    core._tick_events=[];core._emit('growth_type_mastery_selected',cat_id=cat_id,type_mastery=choice,label=type_label(choice))
    core._record(dict(kind='resolve_growth_type_mastery',cat_id=cat_id,choice=choice))


def interaction_terms(core,cat_id):
    growth=getattr(core,'growth',None);row=(growth or {}).get('cats',{}).get(cat_id,{})
    mastery=row.get('mastery')
    individual=row.get('type_mastery')
    return dict(group=mastery or '',multiplier=(growth['rules']['mastery_engagement_multiplier'] if mastery else 1),
                type=individual or '',type_multiplier=(growth['rules']['type_mastery_engagement_multiplier'] if individual else 1))


def check_interaction(core,interaction):
    selected=interaction_terms(core,interaction.cat_id)
    if (interaction.config.mastery_group!=selected['group']
            or interaction.config.mastery_engagement_multiplier!=selected['multiplier']
            or interaction.config.type_mastery!=selected['type']
            or interaction.config.type_mastery_engagement_multiplier!=selected['type_multiplier']):
        raise ValueError('接客熟練の条件が営業状態と一致しません。')


def rest_bonus(core,cat_id):
    growth=getattr(core,'growth',None);row=(growth or {}).get('cats',{}).get(cat_id,{})
    return growth['rules']['rest_recovery_bonus'] if row.get('specialization')=='rest' else 0


def dispatch_multiplier(core,cat_id):
    growth=getattr(core,'growth',None);row=(growth or {}).get('cats',{}).get(cat_id,{})
    return growth['rules']['dispatch_reward_multiplier'] if row.get('specialization')=='dispatch' else 1


def validate(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','cats'} or set(data.get('cats',{}))!=set(core.cats):raise ValueError('猫の成長記録が不正です。')
    selected=rules(data['rules']);template=blank(selected)
    for row in data['cats'].values():
        if (not isinstance(row,dict) or set(row)!=set(template) or set(row['type_actions'])!=set(TYPE_GROUPS)
                or set(row['groups'])!=set(MASTERY_GROUPS)
                or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in [row['service'],row['rest'],row['dispatch'],*row['type_actions'].values(),*row['groups'].values()])
                or row['specialization'] not in (None,*SPECIALIZATIONS)
                or (row['specialization'] is None)!=(row['selected_day'] is None)
                or (row['selected_day'] is not None and (type(row['selected_day']) is not int or not 1<=row['selected_day']<=core.day))
                or any(row['groups'][group]!=sum(row['type_actions'][key] for key,value in TYPE_GROUPS.items() if value==group) for group in row['groups'])
                or (row['specialization'] is not None and total(row)<selected['threshold'])):
            raise ValueError('猫の経験・成長選択が不正です。')
        if 'mastery_groups' in row and (set(row['mastery_groups'])!=set(MASTERY_GROUPS)
                or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in row['mastery_groups'].values())
                or any(row['mastery_groups'][group]>row['groups'][group] for group in MASTERY_GROUPS)
                or row['mastery'] not in (None,*MASTERY_GROUPS)
                or (row['mastery'] is None)!=(row['mastery_selected_day'] is None)
                or (row['mastery'] is not None and (row['specialization']!='service'
                    or row['mastery_groups'][row['mastery']]<=0
                    or sum(row['mastery_groups'].values())<selected['mastery_threshold']))
                or (row['mastery_selected_day'] is not None and (type(row['mastery_selected_day']) is not int
                    or not 1<=row['mastery_selected_day']<=core.day))):
            raise ValueError('猫の接客熟練記録が不正です。')
        if 'type_mastery_actions' in row:
            actions=row['type_mastery_actions'];choice=row['type_mastery'];day=row['type_mastery_selected_day']
            if (not isinstance(actions,dict) or set(actions)!=set(TYPE_GROUPS)
                    or any(type(v) is not int or v<0 for v in actions.values())
                    or any(actions[key]>row['type_actions'][key] for key in TYPE_GROUPS)
                    or any(actions[key]>0 and TYPE_GROUPS[key]!=row['mastery'] for key in TYPE_GROUPS)
                    or sum(actions.values())>row['mastery_groups'].get(row['mastery'],0)
                    or choice not in (None,*TYPE_GROUPS)
                    or (choice is None)!=(day is None)
                    or (choice is not None and (TYPE_GROUPS[choice]!=row['mastery'] or actions[choice]<=0
                        or sum(actions.values())<selected['type_mastery_threshold']))
                    or (day is not None and (type(day) is not int or not row['mastery_selected_day']<=day<=core.day))):
                raise ValueError('猫の個別行動熟練記録が不正です。')
    core.growth=copy.deepcopy(data);return core.growth
