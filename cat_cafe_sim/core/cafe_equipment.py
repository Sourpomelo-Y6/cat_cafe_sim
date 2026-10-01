"""休養スペースの購入・設置と、在店休養時の疲労回復補助。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2]/'config/cafe_rest_space.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'cost', 'recovery_bonus'}:
        raise ValueError('休養スペースの設定が不正です。')
    for key in ('cost', 'recovery_bonus'):
        if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('設備費用・疲労回復量は正の数で指定してください。')
    if data['recovery_bonus'] > 100:
        raise ValueError('追加の疲労回復量は100以下にしてください。')
    return copy.deepcopy(data)


def reason(core, selected):
    try:
        core.require_events_resolved()
    except ValueError as exc:
        return str(exc)
    if not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules:
        return '出勤・病気ルールが有効な営業準備中に購入できます。'
    if core.rest_space is not None:
        return '休養スペースは購入・設置済みです。'
    if core.funds <= selected['cost']:
        return '購入後に資金が残る必要があります。'
    return ''


def purchase(core, selected=None):
    selected = rules(selected)
    problem = reason(core, selected)
    if problem:
        raise ValueError(problem)
    core.funds -= selected['cost']
    core.rest_space = dict(day=core.day, rules=selected)
    core._tick_events = []
    core._emit('rest_space_purchased', cost=selected['cost'], recovery_bonus=selected['recovery_bonus'])
    core._record(dict(kind='purchase_rest_space', rules=selected))


def upgrade_rules(data=None):
    if data is None:
        data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_rest_space_upgrade.json').read_text(encoding='utf-8'))
    return rules(data)


def upgrade_reason(core,selected):
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules:
        return '休養スペースの強化は出勤・病気ルールが有効な営業準備中に行ってください。'
    if core.rest_space is None:return '先に休養スペースを購入・設置してください。'
    if 'upgrade' in core.rest_space:return '休養スペースは強化済みです。'
    from .cafe_expansion import first_popularity_cleared
    if not first_popularity_cleared(core):return '休養スペースの強化は人気第1段階達成後に解放されます。'
    if selected['recovery_bonus']<=core.rest_space['rules']['recovery_bonus']:
        return '強化後の疲労回復量は現在の設備より大きい必要があります。'
    if core.funds<=selected['cost']:return '強化後に資金が残る必要があります。'
    return ''


def upgrade(core,selected=None):
    selected=upgrade_rules(selected); problem=upgrade_reason(core,selected)
    if problem:raise ValueError(problem)
    core.funds-=selected['cost']
    core.rest_space['upgrade']=dict(day=core.day,rules=selected)
    core._tick_events=[]
    core._emit('rest_space_upgraded',cost=selected['cost'],recovery_bonus=selected['recovery_bonus'])
    core._record(dict(kind='upgrade_rest_space',rules=selected))


def recovery_bonus(core):
    data=core.rest_space
    return data.get('upgrade',data)['rules']['recovery_bonus'] if data else 0


def bonus(core, cat_id):
    data = getattr(core, 'rest_space', None)
    if not data:
        return 0
    from .cafe_activities import activity
    return recovery_bonus(core) if activity(core, cat_id) == 'cafe' else 0


def expenses(core, day=None):
    data = core.rest_space
    if not data:return 0
    return sum(row['rules']['cost'] for row in (data, *(data[key] for key in ('upgrade','soundproof') if key in data))
               if day is None or row['day']==day)


def validate(core, data):
    if not isinstance(data, dict) or not {'day','rules'}<=set(data)<={'day','rules','upgrade','soundproof'}:
        raise ValueError('休養スペースの購入記録が不正です。')
    selected = rules(data['rules'])
    if type(data['day']) is not int or not 1 <= data['day'] <= core.day or not core.shift_rules or not core.health_rules:
        raise ValueError('休養スペースの購入日・休養ルールが不正です。')
    if 'upgrade' in data:
        row=data['upgrade']
        if (not isinstance(row,dict) or set(row)!={'day','rules'} or type(row['day']) is not int
                or not data['day']<=row['day']<=core.day):
            raise ValueError('休養スペースの強化日・記録が不正です。')
        upgraded=upgrade_rules(row['rules'])
        if upgraded['recovery_bonus']<=selected['recovery_bonus']:
            raise ValueError('休養スペースの強化で疲労回復量が増えていません。')
    if 'soundproof' in data:
        row=data['soundproof']
        if (not isinstance(row,dict) or set(row)!={'day','rules'} or type(row['day']) is not int
                or not data['day']<=row['day']<=core.day):
            raise ValueError('防音改修の日付・記録が不正です。')
        soundproof_rules(row['rules'])
    for result in core.day_results:
        expected_cost = (selected['cost'] if result['day'] == data['day'] else 0)
        if 'upgrade' in data and result['day']==data['upgrade']['day']:expected_cost+=data['upgrade']['rules']['cost']
        if 'soundproof' in data and result['day']==data['soundproof']['day']:expected_cost+=data['soundproof']['rules']['cost']
        if result['summary'].get('equipment_expenses', 0) != expected_cost:
            raise ValueError('営業履歴と設備購入記録が一致しません。')
    return copy.deepcopy(data)


def validate_upgrade(core):
    data=core.rest_space
    if data and 'soundproof' in data:
        if core.management is None or data['soundproof']['day']<core.management['started_day']:
            raise ValueError('防音改修の経営ルールがありません。')
        from .cafe_expansion import second_popularity_cleared
        if not second_popularity_cleared(core):raise ValueError('防音改修の解放条件を満たしていません。')
        second=([*core.goal.get('history',[]),core.goal])[1]
        if data['soundproof']['day']<=second['resolved_day']:raise ValueError('人気第2段階達成前に防音改修しています。')
    if not data or 'upgrade' not in data:return
    from .cafe_expansion import first_popularity_cleared
    if not first_popularity_cleared(core):raise ValueError('休養スペースの強化条件を満たしていません。')
    first=(core.goal.get('history') or [core.goal])[0]
    if data['upgrade']['day']<=first['resolved_day']:
        raise ValueError('人気第1段階達成前に休養スペースが強化されています。')


def soundproof_rules(data=None):
    if data is None:
        data=json.loads((Path(__file__).resolve().parents[2]/'config/cafe_rest_space_soundproof.json').read_text(encoding='utf-8'))
    if not isinstance(data,dict) or set(data)!={'cost','stress_recovery_bonus'}:
        raise ValueError('防音改修の設定が不正です。')
    for key in ('cost','stress_recovery_bonus'):
        if type(data[key]) not in (int,float) or not math.isfinite(data[key]) or data[key]<=0:
            raise ValueError('防音改修の費用・回復量が不正です。')
    if data['stress_recovery_bonus']>100:raise ValueError('ストレス回復量は100以下にしてください。')
    return copy.deepcopy(data)


def soundproof_reason(core,selected):
    try:core.require_events_resolved()
    except ValueError as exc:return str(exc)
    if not core.compact or not core.can_set_shifts or not core.shift_rules or not core.health_rules or core.management is None:
        return '防音改修は経営・出勤・病気ルールが有効な営業準備中に行ってください。'
    if core.rest_space is None:return '先に休養スペースを購入・設置してください。'
    if 'soundproof' in core.rest_space:return '防音改修は実施済みです。'
    from .cafe_expansion import second_popularity_cleared
    if not second_popularity_cleared(core):return '防音改修は人気第2段階達成後に解放されます。'
    if core.funds<=selected['cost']:return '改修後に資金が残る必要があります。'
    return ''


def soundproof(core,selected=None):
    selected=soundproof_rules(selected);problem=soundproof_reason(core,selected)
    if problem:raise ValueError(problem)
    core.funds-=selected['cost']
    core.rest_space['soundproof']=dict(day=core.day,rules=selected)
    core._tick_events=[]
    core._emit('rest_space_soundproofed',cost=selected['cost'],stress_recovery_bonus=selected['stress_recovery_bonus'])
    core._record(dict(kind='soundproof_rest_space',rules=selected))


def stress_bonus(core,cat_id):
    data=getattr(core,'rest_space',None)
    if not data or 'soundproof' not in data:return 0
    return data['soundproof']['rules']['stress_recovery_bonus'] if core.activity(cat_id)=='cafe' else 0
