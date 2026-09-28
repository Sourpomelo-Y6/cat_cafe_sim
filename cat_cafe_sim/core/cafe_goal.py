"""閉店ごとの人気獲得と期限付き目標。旧営業には明示導入する。"""
import copy
import json
import math
from pathlib import Path
from .cafe_checkpoint import outcome_result


def rules(data=None):
    data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_goal.json').read_text()) if data is None else data
    if not isinstance(data, dict) or set(data) not in ({'days','target','cap','gain_per_success'}, {'days','target','cap','gain_per_success','stages'}):
        raise ValueError('目標の設定が不正です。')
    if type(data['days']) is not int or data['days'] < 1:
        raise ValueError('目標日数が不正です。')
    for key in ('target','cap','gain_per_success'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('目標の数値が不正です。')
    if not 100 < data['target'] <= data['cap']:
        raise ValueError('人気目標は100より大きく、上限以下にしてください。')
    if 'stages' in data:
        if not isinstance(data['stages'], list) or len(data['stages']) != 2:
            raise ValueError('後続の人気目標は2段階で指定してください。')
        previous = data['target']
        for row in data['stages']:
            if (not isinstance(row, dict) or set(row) != {'days', 'target'}
                    or type(row['days']) is not int or row['days'] < 1
                    or type(row['target']) not in (int, float) or not math.isfinite(row['target'])
                    or not previous < row['target'] <= data['cap']):
                raise ValueError('後続目標の日数・人気が不正です。')
            previous = row['target']
    return copy.deepcopy(data)


def progression_rules():
    selected = rules()
    selected['stages'] = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_goal_stages.json').read_text())
    return rules(selected)


def current_rules(data):
    index = len(data.get('history', []))
    return data['rules']['stages'][index-1] if index else data['rules']


def current_start(data):
    return data.get('stage_started_day', data['started_day'])


def summary_status(data, day):
    if current_start(data) > day and data.get('history'):
        return data['history'][-1]['status']
    return data['status']


def next_rules(data):
    index = len(data.get('history', []))
    stages = data['rules'].get('stages', [])
    return stages[index] if index < len(stages) else None


def advance_reason(core):
    from .cafe_activities import waiting_events
    from .cafe_player import active
    from .cafe_management import is_over
    from .cafe_patron import pending as patron_pending
    from .cafe_bond_goal import pending as bond_pending
    data = core.goal
    if is_over(core):
        return 'ゲームオーバー後は次の目標を開始できません。'
    if not data or data['status'] != 'cleared' or next_rules(data) is None:
        return '次に挑戦できる人気目標はありません。'
    if waiting_events(core) or active(core) or patron_pending(core) or bond_pending(core):
        return '先に交流・帰還・イベント・他の目標結果を確認してください。'
    if not (core.closed or core.can_set_shifts):
        return '次の目標は閉店結果または営業準備中に選べます。'
    return ''


def advance(core):
    reason = advance_reason(core)
    if reason:
        raise ValueError(reason)
    data = core.goal
    data['history'].append(dict(started_day=current_start(data), status=data['status'],
                                resolved_day=data['resolved_day'], continued=data['continued']))
    data.update(stage_started_day=core.day+int(core.closed), status='active', resolved_day=None, continued=False)
    core._tick_events=[]
    core._emit('goal_advanced', stage=len(data['history'])+1, started_day=current_start(data), target=current_rules(data)['target'])
    core._record(dict(kind='advance_goal'))


def pending(core):
    from .cafe_management import is_over
    return bool(core.goal and core.goal['status'] != 'active' and not core.goal['continued'] and not is_over(core))


def enable(core, selected=None, *, tracking_only=False):
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts or not core.management or core.goal:
        raise ValueError('経営ルールが有効な準備中に一度だけ目標を開始できます。')
    selected = rules(selected)
    if type(tracking_only) is not bool or (tracking_only and 'stages' in selected):
        raise ValueError('人気の集計設定が不正です。')
    core.goal = dict(rules=selected, started_day=core.day, days=[], status='active', resolved_day=None, continued=False)
    if tracking_only:
        core.goal['tracking_only'] = True
    if 'stages' in selected:
        core.goal.update(history=[], stage_started_day=core.day)
    core._tick_events=[]
    core._emit('goal_enabled', **({'tracking_only':True} if tracking_only else {}))
    core._record(dict(kind='enable_goal', rules=selected, **({'tracking_only':True} if tracking_only else {})))


def earn(core):
    if not core.goal:
        return
    rows = list(core.outcomes.values())[core.day_outcome_offset:]
    from .cafe_customer_satisfaction import qualified
    count = sum(qualified(core, outcome_result(row)) for row in rows)
    from .cafe_reservation import popularity_bonus
    from .cafe_vip_customer import popularity_bonus as vip_popularity_bonus
    extra=sum(popularity_bonus(core,outcome_result(row))+vip_popularity_bonus(core,outcome_result(row)) for row in rows)
    before = core.management['popularity']
    after = min(core.goal['rules']['cap'], before+count*core.goal['rules']['gain_per_success']+extra)
    core.management['popularity'] = after
    core.goal['days'].append(dict(day=core.day, qualified=count, gain=after-before))
    core._emit('popularity_earned', gain=after-before, qualified=count)


def settle(core):
    from .cafe_management import is_over
    data=core.goal
    if not data or data.get('tracking_only') or data['status']!='active' or is_over(core):
        return
    selected = current_rules(data)
    if core.day < current_start(data):
        return
    status = ('cleared' if core.management['popularity'] >= selected['target'] else
              'expired' if core.day >= current_start(data)+selected['days']-1 else 'active')
    if status!='active':
        data.update(status=status, resolved_day=core.day)
        core._emit('goal_result', status=status)
        from .cafe_clear_results import capture
        capture(core, 'popularity')
        if status == 'cleared' and core.advanced_customers is not None and not data.get('history'):
            core._emit('advanced_customer_unlocked', first_day=core.day+1)
        if status=='cleared' and core.reservation is not None and len(data.get('history',[]))==1:
            core._emit('reservation_unlocked',first_request_day=core.day+1)
        if status=='cleared' and core.vip_customer is not None and len(data.get('history',[]))==2:
            core._emit('vip_customer_unlocked',first_day=core.day+1)


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
    if not isinstance(data,dict) or set(data) not in ({'rules','started_day','days','status','resolved_day','continued'}, {'rules','started_day','days','status','resolved_day','continued','history','stage_started_day'}, {'rules','started_day','days','status','resolved_day','continued','tracking_only'}):
        raise ValueError('目標の状態が不正です。')
    rule=rules(data['rules'])
    if 'tracking_only' in data and (data['tracking_only'] is not True or 'stages' in rule):
        raise ValueError('人気集計のみの状態が不正です。')
    if data['status'] not in ('active','cleared','expired') or (data['resolved_day'] is not None and type(data['resolved_day']) is not int):
        raise ValueError('目標結果の種類・日付が不正です。')
    start=data['started_day']
    if type(start) is not int or not management['started_day']<=start<=core.day or type(data['continued']) is not bool:
        raise ValueError('目標の開始日・確認状態が不正です。')
    attempts = []
    if 'stages' in rule:
        history = data.get('history')
        stage_start = data.get('stage_started_day')
        if (not isinstance(history, list) or len(history) > len(rule['stages'])
                or type(stage_start) is not int or not start <= stage_start <= core.day+int(core.closed)):
            raise ValueError('目標段階の履歴・開始日が不正です。')
        for row in history:
            if (not isinstance(row, dict) or set(row) != {'started_day','status','resolved_day','continued'}
                    or type(row['started_day']) is not int or type(row['resolved_day']) is not int
                    or row['status'] != 'cleared' or type(row['continued']) is not bool):
                raise ValueError('達成済み目標の記録が不正です。')
        attempts = history + [dict(started_day=stage_start, status=data['status'], resolved_day=data['resolved_day'], continued=data['continued'])]
        if attempts[0]['started_day'] != start:
            raise ValueError('最初の目標の開始日が一致しません。')
        for previous, following in zip(attempts, attempts[1:]):
            if (not previous['started_day'] <= previous['resolved_day'] < following['started_day']
                    or (not previous['continued'] and following['started_day'] != previous['resolved_day']+1)):
                raise ValueError('次の目標が達成・結果確認より先に始まっています。')
    elif 'history' in data or 'stage_started_day' in data:
        raise ValueError('単段階目標には後続の履歴を保存できません。')
    else:
        attempts = [dict(started_day=start, status=data['status'], resolved_day=data['resolved_day'], continued=data['continued'])]
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
    daily_popularity={}
    for day,row in enumerate(data['days'],start):
        if (not isinstance(row,dict) or set(row)!={'day','qualified','gain'}
                or type(row['day']) is not int or type(row['qualified']) is not int
                or type(row['gain']) not in (int,float) or not math.isfinite(row['gain'])):
            raise ValueError('人気獲得の記録が不正です。')
        from .cafe_customer_satisfaction import qualified
        from .cafe_customer_trust import losses as customer_losses
        popularity=max(0,popularity-customer_losses(core,day))
        count=sum(qualified(core, outcome_result(value)) for value in offsets[day])
        from .cafe_reservation import popularity_bonus
        from .cafe_vip_customer import popularity_bonus as vip_popularity_bonus
        extra=sum(popularity_bonus(core,outcome_result(value))+vip_popularity_bonus(core,outcome_result(value)) for value in offsets[day])
        after=min(rule['cap'],popularity+count*rule['gain_per_success']+extra)
        expected=dict(day=day,qualified=count,gain=after-popularity)
        if row!=expected:
            raise ValueError('人気獲得と接客記録が一致しません。')
        popularity=max(0,after-sum(e['departed_day']==day for e in events)*management['rules']['popularity_loss'])
        daily_popularity[day] = popularity
    stage_rules = [rule] + rule.get('stages', [])
    for index, attempt in enumerate(attempts):
        status, resolved = 'active', None
        selected = stage_rules[index]
        last = attempts[index+1]['started_day']-1 if index+1 < len(attempts) else end
        for day in range(attempt['started_day'], last+1):
            ended = management['game_over'] and management['game_over']['reason']=='popularity' and management['game_over']['day']==day
            if status == 'active' and not ended and not data.get('tracking_only'):
                status = 'cleared' if daily_popularity[day] >= selected['target'] else 'expired' if day >= attempt['started_day']+selected['days']-1 else 'active'
                if status != 'active':
                    resolved = day
        if attempt['status'] != status or attempt['resolved_day'] != resolved or (status == 'active' and attempt['continued']):
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
