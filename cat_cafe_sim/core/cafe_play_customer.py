"""設備と実際の交流分類を条件にする、遊び好きのお客さん。"""
import copy
import json
import math
from pathlib import Path

CUSTOMER_ID = 'advanced-play'
NAME = '遊び好きのお客さん'


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_play_customer.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'equipment', 'play_count', 'bonus', 'popularity_bonus', 'weekdays', 'quiet_weekdays'}
            or data['equipment'] != 'cat_tower' or type(data['play_count']) is not int or data['play_count'] < 1):
        raise ValueError('遊び客の条件が不正です。')
    for key in ('weekdays', 'quiet_weekdays'):
        values = data[key]
        if (not isinstance(values, list) or not values
                or any(type(day) is not int or not 0 <= day < 7 for day in values)
                or len(set(values)) != len(values)):
            raise ValueError('交流客の来店曜日が不正です。')
    if set(data['weekdays']) & set(data['quiet_weekdays']):
        raise ValueError('遊び客と静かな交流客の曜日は分けてください。')
    for key in ('bonus', 'popularity_bonus'):
        if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] <= 0:
            raise ValueError('遊び客の報酬が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.play_customer is not None
            or core.weekdays is None or not core.goal or core.goal.get('tracking_only')
            or 'stages' not in core.goal['rules'] or core.goal['status'] != 'active'):
        raise ValueError('遊び客は人気3段階の新規ゲームに設定してください。')
    core.play_customer = rules(selected)
    core._tick_events = []
    core._record(dict(kind='initialize_play_customer', rules=copy.deepcopy(core.play_customer)))


def applies(core, customer_id):
    return core.play_customer is not None and customer_id == CUSTOMER_ID


def unlocked_day(core):
    if core.play_customer is None or not core.goal:
        return None
    first = (core.goal.get('history') or [core.goal])[0]
    return first['resolved_day'] if first['status'] == 'cleared' else None


def schedule(core, day):
    unlocked = unlocked_day(core)
    weekday = (core.weekdays['start_weekday'] + day - 1) % 7 if core.weekdays else None
    return {CUSTOMER_ID: 0} if unlocked is not None and day > unlocked and weekday in core.play_customer['weekdays'] else {}


def preferred_seat(core, customer_id, free_seats):
    from .cafe_seat_equipment import installed
    if applies(core, customer_id):
        for seat_id in free_seats:
            equipment = installed(core, seat_id)
            if equipment and equipment['id'] == core.play_customer['equipment']:
                return seat_id
    return free_seats[0]


def check_interaction(core, interaction):
    if interaction.config.play_service != applies(core, interaction.customer_id):
        raise ValueError('遊び客の接客設定が一致しません。')


def evaluate(core, result):
    if not applies(core, result['customer_id']):
        return None
    from .cafe_growth import TYPE_GROUPS
    if type(result.get('play_equipment')) is not bool:
        raise ValueError('遊び客の設備記録がありません。')
    count = sum(result['type_actions'][key] for key, group in TYPE_GROUPS.items() if group == 'play')
    selected = core.play_customer
    success = result['play_equipment'] and count >= selected['play_count']
    return dict(matched=result['play_equipment'], play_count=count, success=success,
                bonus=selected['bonus'] if success else 0)


def popularity_bonus(core, result):
    row = evaluate(core, result)
    return core.play_customer['popularity_bonus'] if row and row['success'] else 0


def result_text(core, result):
    row = evaluate(core, result)
    return (f"{'達成' if row['success'] else '未達'}：キャットタワー{'あり' if row['matched'] else 'なし'}"
            f"・遊び {row['play_count']}/{core.play_customer['play_count']}回"
            f"・追加料金 {row['bonus']:g}・追加人気 {popularity_bonus(core, result):g}")


def description(core):
    selected = core.play_customer
    if selected is None:
        return ''
    day = unlocked_day(core)
    status = '人気第1段階達成で解放' if day is None else f'{day}日目に解放・翌日以降の対象曜日に1名'
    from .cafe_weekdays import DAYS
    days = '・'.join(DAYS[day] for day in selected['weekdays'])
    return (f"{NAME}：{status}（来店曜日：{days}）。キャットタワーの席で通常の遊び（ねこじゃらし・ボール・ぬいぐるみ・トンネル）を"
            f"合計{selected['play_count']}回以上行うと追加料金＋{selected['bonus']:g}・人気＋{selected['popularity_bonus']:g}。")


def validate(core, data):
    core.play_customer = rules(data)
    if (core.weekdays is None or not core.goal or core.goal.get('tracking_only')
            or 'stages' not in core.goal['rules'] or core.goal['started_day'] != 1):
        raise ValueError('遊び客の来店・人気目標設定がありません。')
    from .cafe_checkpoint import outcome_result
    rows = [outcome_result(value) for value in core.outcomes.values()]
    offset = 0
    for day in core.day_results + [dict(day=core.day, summary=core.summary())]:
        count = day['summary']['completed_interactions']
        for result in rows[offset:offset+count]:
            if result['customer_id'] == CUSTOMER_ID:
                if CUSTOMER_ID not in schedule(core, day['day']):
                    raise ValueError('解放前の遊び客の接客記録があります。')
                evaluate(core, result)
            elif 'play_equipment' in result:
                raise ValueError('遊び客以外に設備判定の記録があります。')
        offset += count
    return core.play_customer
