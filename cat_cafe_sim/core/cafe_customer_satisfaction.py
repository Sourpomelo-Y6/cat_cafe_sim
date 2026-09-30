"""1回の接客を満足・普通・不満に分け、後続の経営結果へ接続する。"""
import copy
import json
import math
from pathlib import Path

FIELDS = {'satisfied_score', 'dissatisfied_score', 'gauge_target',
          'satisfied_bonus', 'dissatisfied_discontent_gain'}
LABELS = {'satisfied': '満足', 'normal': '普通', 'dissatisfied': '不満'}


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_customer_satisfaction.json').read_text())
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError('接客満足度の設定が不正です。')
    for value in data.values():
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('接客満足度の設定が不正です。')
    if (data['satisfied_score'] <= data['dissatisfied_score']
            or not 0 <= data['gauge_target'] <= 100):
        raise ValueError('接客満足度の設定が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts
            or core.customer_satisfaction is not None or core.customer_preferences is None or core.weekdays is None):
        raise ValueError('接客満足度は新規ゲームの準備中に設定してください。')
    core.customer_satisfaction = rules(selected)
    core._tick_events = []
    core._record(dict(kind='initialize_customer_satisfaction', rules=copy.deepcopy(core.customer_satisfaction)))


def evaluate(core, result, advanced=None):
    selected = core.customer_satisfaction
    if selected is None:
        return None
    preferred = None
    if core.customer_preferences is not None:
        from .cafe_preferences import preference_for
        if advanced is not None:
            preferred = core.advanced_customers['feature']
        else:
            from .cafe_vip_customer import CUSTOMER_ID as VIP_ID
            preferred = core.vip_customer['feature'] if core.vip_customer is not None and result['customer_id']==VIP_ID else core.customer_preferences['customers'].get(result['customer_id'])
            if preferred is None:
                preferred = preference_for(core.seed, result['customer_id'], core.customer_preferences['rules']['pool'])
    matched = preferred is not None and preferred in (core.cat_features or {}).get(result['cat_id'], [])
    special = result['connect_count'] + result['open_up_count'] > 0
    gauges = result['tension'] >= selected['gauge_target'] and result['engagement'] >= selected['gauge_target']
    score = int(result['affinity_delta'] > 0) + int(special) + int(gauges) + int(matched)
    reasons = [name for yes, name in ((result['affinity_delta'] > 0, '親しみ上昇'),
               (special, '特別行動'), (gauges, '関心・テンション'), (matched, '好み一致')) if yes]
    if advanced is not None:
        score += 1 if advanced['success'] else -1
        reasons.append('高難度条件達成' if advanced['success'] else '高難度条件未達')
    from .cafe_reservation import evaluate as reservation_evaluate
    reservation=reservation_evaluate(core,result)
    if reservation is not None:
        score += 1 if reservation['success'] else -1
        reasons.append('予約条件達成' if reservation['success'] else '予約条件未達')
    from .cafe_vip_customer import evaluate as vip_evaluate
    vip=vip_evaluate(core,result)
    if vip is not None:
        score += 1 if vip['success'] else -1
        reasons.append('VIP条件達成' if vip['success'] else 'VIP条件未達')
    from .cafe_quiet_customer import evaluate as quiet_evaluate
    quiet = quiet_evaluate(core, result)
    if quiet is not None:
        score += 1 if quiet['success'] else -1
        reasons.append('静かな交流条件達成' if quiet['success'] else '静かな交流条件未達')
    from .cafe_play_customer import evaluate as play_evaluate
    play = play_evaluate(core, result)
    if play is not None:
        score += 1 if play['success'] else -1
        reasons.append('遊び条件達成' if play['success'] else '遊び条件未達')
    if result['end_reason'] == 'exhausted':
        score -= 2
        reasons.append('体力切れ')
    level = ('satisfied' if score >= selected['satisfied_score'] else
             'dissatisfied' if score <= selected['dissatisfied_score'] else 'normal')
    return dict(level=level, label=LABELS[level], score=score, reasons=reasons,
                matched=matched, special=special, gauges=gauges,
                bonus=selected['satisfied_bonus'] if level == 'satisfied' else 0)


def latest(core, customer_id):
    if core.customer_satisfaction is None:
        return None
    from .cafe_checkpoint import outcome_result
    from .cafe_advanced_customers import evaluate as advanced_evaluate
    for value in reversed(list(core.outcomes.values())):
        result = outcome_result(value)
        if result['customer_id'] == customer_id:
            return evaluate(core, result, advanced_evaluate(core, result))
    return None


def qualified(core, outcome):
    if core.customer_satisfaction is None:
        return outcome['affinity_pending'] > 0
    from .cafe_advanced_customers import evaluate as advanced_evaluate
    return evaluate(core, outcome, advanced_evaluate(core, outcome))['level'] == 'satisfied'


def counts(core, outcomes):
    result = dict.fromkeys(LABELS, 0)
    if core.customer_satisfaction is None:
        return None
    from .cafe_advanced_customers import evaluate as advanced_evaluate
    for outcome in outcomes:
        result[evaluate(core, outcome, advanced_evaluate(core, outcome))['level']] += 1
    return result


def validate(core, data):
    selected = rules(data)
    core.customer_satisfaction = selected
    from .cafe_checkpoint import outcome_result
    from .cafe_advanced_customers import evaluate as advanced_evaluate
    outcomes = [outcome_result(value) for value in core.outcomes.values()]
    offset = 0
    days = core.day_results + [dict(summary=core.summary())]
    for index, day in enumerate(days):
        count = day['summary']['completed_interactions']
        current = outcomes[offset:offset+count] if index < len(core.day_results) else outcomes[core.day_outcome_offset:]
        expected = counts(core, current)
        if day['summary'].get('customer_satisfaction') != expected:
            raise ValueError('接客満足度と日次結果が一致しません。')
        bonus = 0
        for outcome in current:
            advanced = advanced_evaluate(core, outcome)
            from .cafe_reservation import evaluate as reservation_evaluate
            reservation=reservation_evaluate(core,outcome)
            from .cafe_vip_customer import evaluate as vip_evaluate
            vip=vip_evaluate(core,outcome)
            from .cafe_quiet_customer import evaluate as quiet_evaluate
            quiet = quiet_evaluate(core, outcome)
            from .cafe_play_customer import evaluate as play_evaluate
            play = play_evaluate(core, outcome)
            bonus += outcome['bonus_funds'] + (advanced['bonus'] if advanced else 0) + (reservation['bonus'] if reservation else 0) + (vip['bonus'] if vip else 0) + (quiet['bonus'] if quiet else 0) + (play['bonus'] if play else 0) + evaluate(core, outcome, advanced)['bonus']
        if day['summary']['interaction_bonus'] != bonus:
            raise ValueError('接客評価の追加料金と接客記録が一致しません。')
        if index < len(core.day_results):
            offset += count
    return selected
