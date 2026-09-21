"""閉店ごとの人気獲得と期限付き目標。旧営業には明示導入する。"""
import copy
import json
import math
from pathlib import Path
from .cafe_checkpoint import outcome_result


def rules(data=None):
    data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_goal.json').read_text()) if data is None else data
    if not isinstance(data, dict) or set(data) != {'days','target','cap','gain_per_success'}:
        raise ValueError('目標の設定が不正です。')
    if type(data['days']) is not int or data['days'] < 1:
        raise ValueError('目標日数が不正です。')
    for key in ('target','cap','gain_per_success'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('目標の数値が不正です。')
    if not 100 < data['target'] <= data['cap']:
        raise ValueError('人気目標は100より大きく、上限以下にしてください。')
    return copy.deepcopy(data)


def pending(core):
    from .cafe_management import is_over
    return bool(core.goal and core.goal['status'] != 'active' and not core.goal['continued'] and not is_over(core))


def enable(core, selected=None):
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts or not core.management or core.goal:
        raise ValueError('経営ルールが有効な準備中に一度だけ目標を開始できます。')
    selected = rules(selected)
    core.goal = dict(rules=selected, started_day=core.day, days=[], status='active', resolved_day=None, continued=False)
    core._tick_events=[]
    core._emit('goal_enabled')
    core._record(dict(kind='enable_goal', rules=selected))


def earn(core):
    if not core.goal:
        return
    rows = list(core.outcomes.values())[core.day_outcome_offset:]
    count = sum(outcome_result(row)['affinity_pending'] > 0 for row in rows)
    before = core.management['popularity']
    after = min(core.goal['rules']['cap'], before+count*core.goal['rules']['gain_per_success'])
    core.management['popularity'] = after
    core.goal['days'].append(dict(day=core.day, qualified=count, gain=after-before))
    core._emit('popularity_earned', gain=after-before, qualified=count)


def settle(core):
    from .cafe_management import is_over
    data=core.goal
    if not data or data['status']!='active' or is_over(core):
        return
    status = ('cleared' if core.management['popularity'] >= data['rules']['target'] else
              'expired' if core.day >= data['started_day']+data['rules']['days']-1 else 'active')
    if status!='active':
        data.update(status=status, resolved_day=core.day)
        core._emit('goal_result', status=status)


def continue_game(core):
    from .cafe_activities import waiting_events
    core.require_running()
    if not pending(core):
        raise ValueError('確認待ちの目標結果はありません。')
    if waiting_events(core):
        raise ValueError('先に帰還・譲渡イベントを確認してください。')
    core.goal['continued']=True
    core._tick_events=[]
    core._emit('goal_continued')
    core._record(dict(kind='continue_goal'))


def validate(core, data, management):
    if not isinstance(data,dict) or set(data)!={'rules','started_day','days','status','resolved_day','continued'}:
        raise ValueError('目標の状態が不正です。')
    rule=rules(data['rules'])
    if data['status'] not in ('active','cleared','expired') or (data['resolved_day'] is not None and type(data['resolved_day']) is not int):
        raise ValueError('目標結果の種類・日付が不正です。')
    start=data['started_day']
    if type(start) is not int or not management['started_day']<=start<=core.day or type(data['continued']) is not bool:
        raise ValueError('目標の開始日・確認状態が不正です。')
    end=core.day if core.closed else core.day-1
    if not isinstance(data['days'],list) or len(data['days'])!=max(0,end-start+1):
        raise ValueError('人気獲得の日数が不正です。')
    outcomes=list(core.outcomes.values())
    offsets={}; offset=0
    for result in core.day_results:
        count=result['summary']['completed_interactions']
        offsets[result['day']]=outcomes[offset:offset+count]
        offset+=count
    offsets[core.day]=outcomes[core.day_outcome_offset:]
    events=list(management['events'].values())
    popularity=max(0,management['rules']['starting_popularity']-sum(e['departed_day']<start for e in events)*management['rules']['popularity_loss'])
    status='active'; resolved=None
    for day,row in enumerate(data['days'],start):
        if (not isinstance(row,dict) or set(row)!={'day','qualified','gain'}
                or type(row['day']) is not int or type(row['qualified']) is not int
                or type(row['gain']) not in (int,float) or not math.isfinite(row['gain'])):
            raise ValueError('人気獲得の記録が不正です。')
        count=sum(outcome_result(value)['affinity_pending']>0 for value in offsets[day])
        after=min(rule['cap'],popularity+count*rule['gain_per_success'])
        expected=dict(day=day,qualified=count,gain=after-popularity)
        if row!=expected:
            raise ValueError('人気獲得と接客記録が一致しません。')
        popularity=max(0,after-sum(e['departed_day']==day for e in events)*management['rules']['popularity_loss'])
        # A loss at this closing takes priority over a goal result.
        ended=management['game_over'] and management['game_over']['reason']=='popularity' and management['game_over']['day']==day
        if status=='active' and not ended:
            status='cleared' if popularity>=rule['target'] else 'expired' if day>=start+rule['days']-1 else 'active'
            if status!='active':resolved=day
    if data['status']!=status or data['resolved_day']!=resolved or (status=='active' and data['continued']):
        raise ValueError('目標の達成・期限判定が一致しません。')
    if popularity!=management['popularity']:
        raise ValueError('人気と接客・家出の記録が一致しません。')
    if status!='active' and not data['continued'] and not management['game_over']:
        same_closing = core.day==resolved and core.closed
        after_day_off = (core.day==resolved+1 and not core.closed and core.tick==0 and not core.visits
                         and core.day_results[-1].get('day_type')=='day_off')
        if not (same_closing or after_day_off):
            raise ValueError('目標結果の確認前に営業が進んでいます。')
    return copy.deepcopy(data)
