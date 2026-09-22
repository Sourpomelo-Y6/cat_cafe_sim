"""プレイヤーとの好感度が高い在籍猫を集める任意目標。"""
import copy
import json
import math
from pathlib import Path


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_bond_goal.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'target', 'affinity'}
            or type(data['target']) is not int or data['target'] < 1
            or type(data['affinity']) not in (int, float)
            or not math.isfinite(data['affinity']) or not 0 < data['affinity'] <= 100):
        raise ValueError('好感度目標の設定が不正です。')
    return copy.deepcopy(data)


def qualifying(core, selected=None):
    from .cafe_player import state
    selected = selected or (core.bond_goal['rules'] if core.bond_goal else rules())
    return sorted(key for key, value in state(core)['affinity'].items()
                  if value >= selected['affinity'] and core.activity(key) != 'adopted')


def pending(core):
    from .cafe_management import is_over
    data = core.bond_goal
    return bool(data and data['status'] == 'cleared' and not data['continued'] and not is_over(core))


def evaluate(core):
    from .cafe_management import is_over
    data = core.bond_goal
    if not data or data['status'] != 'active' or is_over(core):
        return
    cats = qualifying(core)
    if len(cats) >= data['rules']['target']:
        data.update(status='cleared', resolved_day=core.day, achieved_cats=cats)
        core._emit('bond_goal_cleared', cat_ids=cats)


def enable(core, selected=None):
    core.require_events_resolved()
    if not core.compact or not core.can_set_shifts or not core.management or core.bond_goal:
        raise ValueError('経営ルールが有効な準備中に一度だけ好感度目標を開始できます。')
    selected = rules(selected)
    core.bond_goal = dict(rules=selected, started_day=core.day, status='active',
                          resolved_day=None, continued=False, achieved_cats=[])
    core._tick_events = []
    core._emit('bond_goal_enabled')
    evaluate(core)
    core._record(dict(kind='enable_bond_goal', rules=selected))


def continue_game(core):
    from .cafe_activities import waiting_events
    core.require_running()
    if not pending(core) or waiting_events(core):
        raise ValueError('確認待ちの好感度目標がないか、先に帰還・譲渡の確認が必要です。')
    core.bond_goal['continued'] = True
    core._tick_events = []
    core._emit('bond_goal_continued')
    core._record(dict(kind='continue_bond_goal'))


def validate(core, data):
    from .cafe_management import is_over
    if not isinstance(data, dict) or set(data) != {'rules','started_day','status','resolved_day','continued','achieved_cats'}:
        raise ValueError('好感度目標の状態が不正です。')
    selected = rules(data['rules'])
    if (not core.management or type(data['started_day']) is not int
            or not core.management['started_day'] <= data['started_day'] <= core.day
            or data['status'] not in ('active', 'cleared') or type(data['continued']) is not bool):
        raise ValueError('好感度目標の開始日・結果が不正です。')
    cats = data['achieved_cats']
    if (not isinstance(cats, list) or any(not isinstance(key, str) or key not in core.cats for key in cats)
            or len(set(cats)) != len(cats)):
        raise ValueError('好感度目標の達成猫が不正です。')
    if data['status'] == 'active':
        if (data['resolved_day'] is not None or data['continued'] or cats
                or (not is_over(core) and len(qualifying(core, selected)) >= selected['target'])):
            raise ValueError('好感度目標の未達成状態が不正です。')
    else:
        if (type(data['resolved_day']) is not int
                or not data['started_day'] <= data['resolved_day'] <= core.day
                or len(cats) < selected['target']):
            raise ValueError('好感度目標の達成記録が不正です。')
        if not data['continued'] and not is_over(core):
            if (core.day != data['resolved_day'] or not core.can_set_shifts
                    or not set(cats) <= set(qualifying(core, selected))):
                raise ValueError('好感度目標の結果確認前に状態が変化しています。')
    return copy.deepcopy(data)


def progress(core):
    data = core.bond_goal
    if not data:
        return '好感度目標：未導入'
    label = 'クリア（継続中）' if data['continued'] else 'クリア・結果確認待ち' if data['status'] == 'cleared' else '挑戦中'
    return f"好感度目標：{len(qualifying(core))} / {data['rules']['target']}匹 · {label}"
