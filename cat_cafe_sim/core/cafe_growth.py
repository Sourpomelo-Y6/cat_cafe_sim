"""猫の活動経験と、初回1回の得意分野選択。"""
import copy
import json
import math
from pathlib import Path

SPECIALIZATIONS=('service','rest','dispatch')
LABELS={'service':'接客','rest':'休養','dispatch':'派遣'}
TYPE_GROUPS={'teaser':'play','ball':'play','plush':'play','tunnel':'play',
             'pet':'contact','brush':'contact','voice':'quiet','presence':'quiet'}


def rules(data=None):
    if data is None:data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_growth.json').read_text())
    fields={'threshold','service_xp','rest_xp','dispatch_xp','service_stamina_refund','rest_recovery_bonus','dispatch_reward_multiplier'}
    if (not isinstance(data,dict) or set(data)!=fields or type(data['threshold']) is not int or data['threshold']<1
            or any(type(data[k]) not in (int,float) or not math.isfinite(data[k]) or data[k]<=0 for k in fields-{'threshold'})
            or not 0<data['service_stamina_refund']<1):raise ValueError('猫の成長設定が不正です。')
    return copy.deepcopy(data)


def blank():
    return dict(service=0,rest=0,dispatch=0,type_actions=dict.fromkeys(TYPE_GROUPS,0),
                groups=dict.fromkeys(('play','contact','quiet'),0),specialization=None,selected_day=None)


def initialize(core,selected=None):
    core.require_events_resolved()
    if not core.compact or core.day!=1 or not core.can_set_shifts or core.growth is not None:
        raise ValueError('猫の成長は新規ゲームの準備中に設定してください。')
    core.growth=dict(rules=rules(selected),cats={key:blank() for key in core.cats})
    core._tick_events=[];core._emit('growth_initialized');core._record(dict(kind='initialize_growth',rules=core.growth['rules']))


def ensure_cat(core,cat_id):
    if core.growth is not None and cat_id not in core.growth['cats']:core.growth['cats'][cat_id]=blank()


def total(row):return row['service']+row['rest']+row['dispatch']


def summary(core,cat_id):
    """Return a short growth label suitable for cat-selection tables."""
    growth=getattr(core,'growth',None)
    if growth is None:return '未導入'
    row=growth['cats'].get(cat_id)
    if row is None:return '記録なし'
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
    if specialization=='service':effect=f"得意：接客（接客終了時に消費体力の{selected['service_stamina_refund']*100:g}%を回復）"
    elif specialization=='rest':effect=f"得意：休養（在店休養時の疲労回復＋{selected['rest_recovery_bonus']:g}）"
    elif specialization=='dispatch':effect=f"得意：派遣（派遣報酬×{selected['dispatch_reward_multiplier']:g}）"
    else:effect=(f"得意分野まであと {max(0,selected['threshold']-value):g}"
                 if value<selected['threshold'] else '得意分野を選択できます。')
    return f'{progress} / {effect}\n{practice}'


def pending(core):
    if core.growth is None:return []
    threshold=core.growth['rules']['threshold']
    return [key for key,row in core.growth['cats'].items() if row['specialization'] is None and total(row)>=threshold]


def _gain(core,cat_id,field,amount):
    if core.growth is None:return
    ensure_cat(core,cat_id);row=core.growth['cats'][cat_id];was=total(row)>=core.growth['rules']['threshold']
    row[field]+=amount
    if not was and total(row)>=core.growth['rules']['threshold']:
        core._emit('growth_ready',cat_id=cat_id,total=total(row))


def service(core,result):
    if core.growth is None:return
    cat_id=result['cat_id'];_gain(core,cat_id,'service',core.growth['rules']['service_xp']);row=core.growth['cats'][cat_id]
    for key,count in result.get('type_actions',{}).items():
        if key in row['type_actions']:
            row['type_actions'][key]+=count;row['groups'][TYPE_GROUPS[key]]+=count
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


def rest_bonus(core,cat_id):
    growth=getattr(core,'growth',None);row=(growth or {}).get('cats',{}).get(cat_id,{})
    return growth['rules']['rest_recovery_bonus'] if row.get('specialization')=='rest' else 0


def dispatch_multiplier(core,cat_id):
    growth=getattr(core,'growth',None);row=(growth or {}).get('cats',{}).get(cat_id,{})
    return growth['rules']['dispatch_reward_multiplier'] if row.get('specialization')=='dispatch' else 1


def validate(core,data):
    if not isinstance(data,dict) or set(data)!={'rules','cats'} or set(data.get('cats',{}))!=set(core.cats):raise ValueError('猫の成長記録が不正です。')
    selected=rules(data['rules'])
    for row in data['cats'].values():
        if (not isinstance(row,dict) or set(row)!=set(blank()) or set(row['type_actions'])!=set(TYPE_GROUPS)
                or set(row['groups'])!={'play','contact','quiet'}
                or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in [row['service'],row['rest'],row['dispatch'],*row['type_actions'].values(),*row['groups'].values()])
                or row['specialization'] not in (None,*SPECIALIZATIONS)
                or (row['specialization'] is None)!=(row['selected_day'] is None)
                or (row['selected_day'] is not None and (type(row['selected_day']) is not int or not 1<=row['selected_day']<=core.day))
                or any(row['groups'][group]!=sum(row['type_actions'][key] for key,value in TYPE_GROUPS.items() if value==group) for group in row['groups'])
                or (row['specialization'] is not None and total(row)<selected['threshold'])):
            raise ValueError('猫の経験・成長選択が不正です。')
    core.growth=copy.deepcopy(data);return core.growth
