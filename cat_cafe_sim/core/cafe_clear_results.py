"""クリア時の成果を一度だけ固定する。旧セーブの過去の数値は補完しない。"""
import copy
import math


def goals(core):
    return {'popularity':core.goal, 'patron':core.patron, 'bond':core.bond_goal}


def completed(core, mode):
    data=goals(core)[mode]
    if not data or data['status']!='cleared':
        return False
    if mode=='popularity':
        from .cafe_goal import next_rules
        return not data.get('tracking_only') and next_rules(data) is None
    return True


def metric(core, mode):
    data=goals(core)[mode]
    if mode=='popularity':
        from .cafe_goal import current_rules
        return current_rules(data)['target'], core.management['popularity']
    if mode=='patron':
        return data['rules']['target'], data['satisfaction']
    return data['rules']['target'], len(data['achieved_cats'])


def initialize(core):
    core.require_events_resolved()
    if not core.compact or core.clear_results is not None or core.day!=1 or not core.can_set_shifts or any(completed(core,m) for m in goals(core)):
        raise ValueError('クリア成果の記録は新規ゲームの準備時に開始します。')
    core.clear_results={}
    core._tick_events=[]
    core._record(dict(kind='initialize_clear_results'))


def capture(core, mode):
    if core.clear_results is None or mode in core.clear_results or not completed(core,mode):
        return
    target,value=metric(core,mode)
    revenue=sum(row['summary']['revenue'] for row in core.day_results)+sum(v.bill for v in core.visits.values())
    core.clear_results[mode]=dict(day=core.day, target=target, value=value, funds=core.funds,
        popularity=core.management['popularity'], cats=sum(core.activity(key)!='adopted' for key in core.cats), revenue=revenue)


def validate(core, data):
    if not isinstance(data,dict) or set(data)!={m for m in goals(core) if completed(core,m)}:
        raise ValueError('クリア結果と達成済み目標が一致しません。')
    for mode,row in data.items():
        if not isinstance(row,dict) or set(row)!={'day','target','value','funds','popularity','cats','revenue'}:
            raise ValueError('クリア結果の項目が不正です。')
        target,_=metric(core,mode)
        if (type(row['day']) is not int or row['day']!=goals(core)[mode]['resolved_day']
                or type(row['cats']) is not int or not 0<=row['cats']<=len(core.cats)):
            raise ValueError('クリア結果の日付・在籍猫数が不正です。')
        if any(type(row[k]) not in (int,float) or not math.isfinite(row[k]) or row[k]<0 for k in ('target','value','funds','popularity','revenue')):
            raise ValueError('クリア結果の数値が不正です。')
        if row['target']!=target or row['value']<target or row['funds']<=0 or row['popularity']<=0:
            raise ValueError('クリア結果の達成値が不正です。')
        if mode=='popularity' and (row['value']!=row['popularity'] or row['value']>core.goal['rules']['cap']):
            raise ValueError('クリア時の人気が不正です。')
        if mode=='patron' and row['value']!=target:
            raise ValueError('クリア時の満足度が不正です。')
        if mode=='bond' and row['value']!=len(core.bond_goal['achieved_cats']):
            raise ValueError('クリア時の好感度対象猫数が不正です。')
    return copy.deepcopy(data)
