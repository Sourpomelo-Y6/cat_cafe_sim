"""派遣1日目の選択イベント。出発時に条件を固定し、一度だけ解決する。"""
import copy
import json
import math
from pathlib import Path


def definition(data):
    if (not isinstance(data,dict) or set(data)!={'id','destination','title','choices'}
            or any(not isinstance(data[k],str) or not data[k].strip() for k in ('id','destination','title'))
            or not isinstance(data['choices'],list) or len(data['choices'])!=2):
        raise ValueError('派遣イベントの設定が不正です。')
    ids=[]
    for row in data['choices']:
        if (not isinstance(row,dict) or set(row)!={'id','label','reward','fatigue','stress'}
                or any(not isinstance(row[k],str) or not row[k].strip() for k in ('id','label'))):
            raise ValueError('派遣イベントの選択肢が不正です。')
        for key in ('reward','fatigue','stress'):
            if type(row[key]) not in (int,float) or not math.isfinite(row[key]):
                raise ValueError('派遣イベントの効果が不正です。')
        if abs(row['fatigue'])>100 or abs(row['stress'])>100:
            raise ValueError('疲労・ストレス変化は-100〜100で指定してください。')
        ids.append(row['id'])
    if len(set(ids))!=2:
        raise ValueError('選択肢が重複しています。')
    return copy.deepcopy(data)


def for_destination(destination):
    rows=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_dispatch_encounters.json').read_text())
    rows=[definition(row) for row in rows]
    if len({row['destination'] for row in rows})!=len(rows):
        raise ValueError('派遣イベントの対象が重複しています。')
    return next((row for row in rows if row['destination']==destination['id'] and destination['days']>=2),None)


def pending(event):
    return event.get('encounter',{}).get('status')=='waiting'


def waiting(core):
    return [e for e in (core.activities or {}).get('events',{}).values() if pending(e)]


def selected(event):
    data=event.get('encounter')
    if not data or data['status']!='resolved':
        return None
    return next(row for row in data['rules']['choices'] if row['id']==data['choice'])


def reward_delta(event):
    row=selected(event)
    return row['reward'] if row else 0


def attach(event, rules):
    if rules is None:
        return
    rules=definition(rules)
    if rules['destination']!=event['destination']['id'] or event['destination']['days']<2:
        raise ValueError('派遣先と選択イベントが一致しません。')
    event['encounter']=dict(rules=rules,status='scheduled',occurred_day=None,resolved_day=None,choice=None,changes=None)


def close_day(core,event):
    data=event.get('encounter')
    if data and data['status']=='scheduled':
        data.update(status='waiting',occurred_day=core.day)
        core._emit('dispatch_choice_waiting',event_id=event['id'],cat_id=event['cat_id'],title=data['rules']['title'])


def resolve(core,event_id,choice):
    core.require_running()
    event=(core.activities or {}).get('events',{}).get(event_id)
    if not event or not event.get('encounter'):
        raise ValueError('派遣イベントを選んでください。')
    data=event['encounter']
    row=next((r for r in data['rules']['choices'] if r['id']==choice),None)
    if row is None:
        raise ValueError('選択肢を確認してください。')
    if data['status']=='resolved':
        if data['choice']!=choice:
            raise ValueError('回答済みの選択は変更できません。')
        return
    if not pending(event) or event['status']!='travelling' or not (core.closed or core.can_set_shifts):
        raise ValueError('回答待ちの派遣イベントではありません。')
    from .cafe_activities import reward
    if not math.isfinite(reward(core,event)+row['reward']):
        raise ValueError('派遣報酬が大きすぎます。')
    cat=core.cats[event['cat_id']]
    before=cat.fatigue
    cat.fatigue=max(0,min(core.shift_rules.max_fatigue,before+row['fatigue']))
    stress_before=core.management['stress'][cat.id] if core.management else None
    stress_after=max(0,min(100,stress_before+row['stress'])) if stress_before is not None else None
    if core.management:
        core.management['stress'][cat.id]=stress_after
    data.update(status='resolved',resolved_day=core.day,choice=choice,
                changes=dict(fatigue_before=before,fatigue_after=cat.fatigue,stress_before=stress_before,stress_after=stress_after))
    core._tick_events=[]
    core._emit('dispatch_choice_resolved',event_id=event_id,cat_id=cat.id,label=row['label'],reward_delta=row['reward'],changes=copy.deepcopy(data['changes']))
    core._record(dict(kind='resolve_dispatch_choice',event_id=event_id,choice=choice))


def validate(core,event):
    data=event.get('encounter')
    if 'encounter' not in event:
        return
    if not isinstance(data,dict) or set(data)!={'rules','status','occurred_day','resolved_day','choice','changes'}:
        raise ValueError('派遣中イベントの状態が不正です。')
    rule=definition(data['rules'])
    if rule['destination']!=event['destination']['id'] or event['destination']['days']<2:
        raise ValueError('派遣中イベントの対象が不正です。')
    elapsed=core.day-event['started_day']+int(core.closed)
    if data['status']=='scheduled':
        if elapsed!=0 or any(data[k] is not None for k in ('occurred_day','resolved_day','choice','changes')):
            raise ValueError('未発生の派遣イベントの記録が不正です。')
        return
    if (type(data['occurred_day']) is not int or data['occurred_day']!=event['started_day'] or elapsed<1):
        raise ValueError('派遣イベントの発生日が不正です。')
    if data['status']=='waiting':
        if elapsed!=1 or event['status']!='travelling' or any(data[k] is not None for k in ('resolved_day','choice','changes')):
            raise ValueError('派遣イベントの回答前に日程が進んでいます。')
        return
    row=next((r for r in rule['choices'] if r['id']==data['choice']),None)
    if (data['status']!='resolved' or row is None or type(data['resolved_day']) is not int
            or not event['started_day']<=data['resolved_day']<=min(core.day,event['started_day']+1)):
        raise ValueError('派遣イベントの回答記録が不正です。')
    changes=data['changes']
    if not isinstance(changes,dict) or set(changes)!={'fatigue_before','fatigue_after','stress_before','stress_after'}:
        raise ValueError('派遣イベントの効果記録が不正です。')
    for key,maximum in (('fatigue',core.shift_rules.max_fatigue),('stress',100)):
        before,after=changes[key+'_before'],changes[key+'_after']
        if key=='stress' and before is None and after is None:
            continue
        if (type(before) not in (int,float) or not math.isfinite(before) or not 0<=before<=maximum
                or type(after) not in (int,float) or after!=max(0,min(maximum,before+row[key]))):
            raise ValueError('派遣イベントの効果と記録が一致しません。')
