"""人気の最初の達成で解放する客。解放日・評価は保存済み成果から導出する。"""
import copy
import json
import math
from pathlib import Path

CUSTOMER_ID = 'advanced-white'
NAME = '白猫好きのこだわり客'


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_advanced_customers.json').read_text())
    if (not isinstance(data, dict) or set(data) != {'feature', 'connect_count', 'bonus'}
            or data['feature'] != 'white' or type(data['connect_count']) is not int or data['connect_count'] < 1
            or type(data['bonus']) not in (int, float) or not math.isfinite(data['bonus']) or data['bonus'] <= 0):
        raise ValueError('高難度客の条件・追加料金が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.advanced_customers is not None
            or core.weekdays is None or core.customer_preferences is None or not core.goal
            or core.goal.get('tracking_only') or core.goal['status'] != 'active'):
        raise ValueError('高難度客は人気目標のある新規ゲームの準備中に設定してください。')
    core.advanced_customers = rules(selected)
    core._tick_events = []
    core._record(dict(kind='initialize_advanced_customers', rules=copy.deepcopy(core.advanced_customers)))


def unlocked_day(core):
    if core.advanced_customers is None or not core.goal or core.goal.get('tracking_only'):
        return None
    first = (core.goal.get('history') or [core.goal])[0]
    return first['resolved_day'] if first['status'] == 'cleared' else None


def schedule(core, day):
    unlocked = unlocked_day(core)
    # 翌日以降、営業した日は1名。既存の通常客の曜日・枠は変更しない。
    return {CUSTOMER_ID: 0} if unlocked is not None and day > unlocked else {}


def evaluate(core, result):
    if core.advanced_customers is None or result['customer_id'] != CUSTOMER_ID:
        return None
    selected = core.advanced_customers
    matched = selected['feature'] in (core.cat_features or {}).get(result['cat_id'], [])
    count = result['connect_count']
    success = matched and count >= selected['connect_count']
    return dict(matched=matched, connect_count=count, success=success,
                bonus=selected['bonus'] if success else 0)


def result_text(core, result):
    row = evaluate(core, result)
    return (f"{'達成' if row['success'] else '未達'}：白猫{'一致' if row['matched'] else '不一致'}"
            f"・心をつかむ {row['connect_count']}/{core.advanced_customers['connect_count']}回"
            f"・追加料金 {row['bonus']:g}")


def description(core):
    selected = core.advanced_customers
    if selected is None:
        return ''
    day = unlocked_day(core)
    status = '第1段階達成で解放' if day is None else f'{day}日目に解放・{day+1}日目から営業日に1名'
    return (f'{NAME}：{status}。白猫を担当にし、心をつかむを'
            f"{selected['connect_count']}回以上発動すると追加料金＋{selected['bonus']:g}。")


def validate(core, data):
    selected = rules(data)
    if (core.weekdays is None or core.customer_preferences is None or not core.goal
            or core.goal.get('tracking_only') or core.goal['started_day'] != 1):
        raise ValueError('高難度客の来店・好み・目標設定がありません。')
    from .cafe_checkpoint import outcome_result
    core.advanced_customers = selected
    rows = [outcome_result(value) for value in core.outcomes.values()]
    offset = 0
    for day in core.day_results + [dict(day=core.day, summary=core.summary())]:
        count = day['summary']['completed_interactions']
        results = rows[offset:offset+count]
        offset += count
        total = 0
        for result in results:
            evaluation = evaluate(core, result)
            if evaluation is not None and CUSTOMER_ID not in schedule(core, day['day']):
                raise ValueError('解放前の高難度客の接客記録があります。')
            from .cafe_customer_satisfaction import evaluate as evaluate_satisfaction
            satisfaction = evaluate_satisfaction(core, result, evaluation)
            from .cafe_reservation import evaluate as reservation_evaluate
            reservation=reservation_evaluate(core,result)
            from .cafe_vip_customer import evaluate as vip_evaluate
            vip=vip_evaluate(core,result)
            total += result['bonus_funds'] + (evaluation['bonus'] if evaluation else 0) + (reservation['bonus'] if reservation else 0) + (vip['bonus'] if vip else 0) + (satisfaction['bonus'] if satisfaction else 0)
        if day['summary']['interaction_bonus'] != total:
            raise ValueError('高難度客を含む追加料金と接客記録が一致しません。')
    return selected
