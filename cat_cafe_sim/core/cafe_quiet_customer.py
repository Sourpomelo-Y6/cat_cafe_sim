"""設備と実際の交流分類を条件にする、静かに過ごしたいお客さん。"""
import copy
import json
import math
from pathlib import Path

CUSTOMER_ID = 'advanced-quiet'
NAME = '静かに過ごしたいお客さん'


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_quiet_customer.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'equipment', 'quiet_count', 'bonus', 'popularity_bonus'}
            or data['equipment'] != 'quiet_space' or type(data['quiet_count']) is not int or data['quiet_count'] < 1):
        raise ValueError('静かな交流客の条件が不正です。')
    for key in ('bonus', 'popularity_bonus'):
        if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('静かな交流客の報酬が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.quiet_customer is not None
            or core.weekdays is None or not core.goal or core.goal.get('tracking_only')
            or 'stages' not in core.goal['rules'] or core.goal['status'] != 'active'):
        raise ValueError('静かな交流客は人気3段階の新規ゲームに設定してください。')
    core.quiet_customer = rules(selected)
    core._tick_events = []
    core._record(dict(kind='initialize_quiet_customer', rules=copy.deepcopy(core.quiet_customer)))


def applies(core, customer_id):
    return core.quiet_customer is not None and customer_id == CUSTOMER_ID


def unlocked_day(core):
    if core.quiet_customer is None or not core.goal:
        return None
    first = (core.goal.get('history') or [core.goal])[0]
    return first['resolved_day'] if first['status'] == 'cleared' else None


def schedule(core, day):
    unlocked = unlocked_day(core)
    if core.play_customer is not None:
        weekday = (core.weekdays['start_weekday'] + day - 1) % 7
        if weekday not in core.play_customer['quiet_weekdays']:
            return {}
    return {CUSTOMER_ID: 0} if unlocked is not None and day > unlocked else {}


def preferred_seat(core, customer_id, free_seats):
    from .cafe_seat_equipment import installed
    if applies(core, customer_id):
        for seat_id in free_seats:
            equipment = installed(core, seat_id)
            if equipment and equipment['id'] == core.quiet_customer['equipment']:
                return seat_id
    return free_seats[0]


def check_interaction(core, interaction):
    if interaction.config.quiet_service != applies(core, interaction.customer_id):
        raise ValueError('静かな交流客の接客設定が一致しません。')


def evaluate(core, result):
    if not applies(core, result['customer_id']):
        return None
    from .cafe_growth import TYPE_GROUPS
    if type(result.get('quiet_equipment')) is not bool:
        raise ValueError('静かな交流客の設備記録がありません。')
    count = sum(result['type_actions'][key] for key, group in TYPE_GROUPS.items() if group == 'quiet')
    selected = core.quiet_customer
    success = result['quiet_equipment'] and count >= selected['quiet_count']
    return dict(matched=result['quiet_equipment'], quiet_count=count, success=success,
                bonus=selected['bonus'] if success else 0)


def popularity_bonus(core, result):
    row = evaluate(core, result)
    return core.quiet_customer['popularity_bonus'] if row and row['success'] else 0


def result_text(core, result):
    row = evaluate(core, result)
    return (f"{'達成' if row['success'] else '未達'}：静かな交流スペース{'あり' if row['matched'] else 'なし'}"
            f"・静かな交流 {row['quiet_count']}/{core.quiet_customer['quiet_count']}回"
            f"・追加料金 {row['bonus']:g}・追加人気 {popularity_bonus(core, result):g}")


def description(core):
    selected = core.quiet_customer
    if selected is None:
        return ''
    day = unlocked_day(core)
    status = '人気第1段階達成で解放' if day is None else f'{day}日目に解放・翌日から営業日に1名'
    if core.play_customer is not None:
        from .cafe_weekdays import DAYS
        status += '（来店曜日：' + '・'.join(DAYS[day] for day in core.play_customer['quiet_weekdays']) + '）'
    return (f"{NAME}：{status}。静かな交流スペースの席で通常の静かな交流（声かけ・そばにいる）を"
            f"合計{selected['quiet_count']}回以上行うと追加料金＋{selected['bonus']:g}・人気＋{selected['popularity_bonus']:g}。")


def validate(core, data):
    core.quiet_customer = rules(data)
    if (core.weekdays is None or not core.goal or core.goal.get('tracking_only')
            or 'stages' not in core.goal['rules'] or core.goal['started_day'] != 1):
        raise ValueError('静かな交流客の来店・人気目標設定がありません。')
    from .cafe_checkpoint import outcome_result
    rows = [outcome_result(value) for value in core.outcomes.values()]
    offset = 0
    for day in core.day_results + [dict(day=core.day, summary=core.summary())]:
        count = day['summary']['completed_interactions']
        for result in rows[offset:offset+count]:
            if result['customer_id'] == CUSTOMER_ID:
                if CUSTOMER_ID not in schedule(core, day['day']):
                    raise ValueError('解放前の静かな交流客の接客記録があります。')
                evaluate(core, result)
            elif 'quiet_equipment' in result:
                raise ValueError('静かな交流客以外に設備判定の記録があります。')
        offset += count
    return core.quiet_customer
