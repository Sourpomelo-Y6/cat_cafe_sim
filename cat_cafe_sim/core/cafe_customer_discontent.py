"""待機失敗・高難度条件未達による累積不満と一時的な来店停止。"""
import copy
import json
import math
from pathlib import Path

FIELDS = {'waiting_gain', 'advanced_failure_gain', 'good_service_recovery', 'threshold', 'suspension_days', 'return_score'}


def rules(data=None):
    if data is None:
        data = json.loads((Path(__file__).resolve().parents[2] / 'config/cafe_customer_discontent.json').read_text())
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError('累積不満の設定が不正です。')
    for key in FIELDS-{'suspension_days'}:
        value = data[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('累積不満の設定が不正です。')
    if (type(data['suspension_days']) is not int or data['suspension_days'] < 1
            or data['threshold'] <= 0 or not 0 <= data['return_score'] < data['threshold']
            or max(data['waiting_gain'], data['advanced_failure_gain'], data['good_service_recovery']) > data['threshold']):
        raise ValueError('累積不満の設定が不正です。')
    return copy.deepcopy(data)


def initialize(core, selected=None):
    core.require_events_resolved()
    if (not core.compact or core.day != 1 or not core.can_set_shifts or core.customer_discontent is not None
            or core.weekdays is None or core.customer_loyalty is None):
        raise ValueError('累積不満は新規ゲームの準備中に設定してください。')
    core.customer_discontent = dict(rules=rules(selected), customers={})
    core._tick_events = []
    core._record(dict(kind='initialize_customer_discontent', rules=copy.deepcopy(core.customer_discontent['rules'])))


def effective_score(data, value, day):
    periods = value['suspensions']
    expired = periods and value['score_day'] <= periods[-1]['until'] < day
    return data['rules']['return_score'] if expired else value['score']


def row(core, customer_id, day=None):
    data = core.customer_discontent
    if data is None:
        return None
    day = core.day if day is None else day
    value = copy.deepcopy(data['customers'].get(customer_id, dict(score=0, score_day=0, suspensions=[])))
    value['score'] = effective_score(data, value, day)
    active = next((period for period in reversed(value['suspensions']) if period['day'] <= day <= period['until']), None)
    value['suspended_until'] = active['until'] if active else None
    return value


def _change(core, customer_id, delta, reason):
    data = core.customer_discontent
    if data is None or delta == 0:
        return
    value = data['customers'].get(customer_id)
    if value is None:
        value = dict(score=0, score_day=0, suspensions=[])
    before = effective_score(data, value, core.day)
    after = min(data['rules']['threshold'], max(0, before+delta))
    if after == before:
        return
    data['customers'][customer_id] = value
    value['score'] = after
    value['score_day'] = core.day
    suspended = False
    if before < data['rules']['threshold'] <= after:
        value['suspensions'].append(dict(day=core.day, until=core.day+data['rules']['suspension_days']))
        suspended = True
    core._emit('customer_discontent_changed', customer_id=customer_id, before=before, after=after,
               reason=reason, suspended=suspended,
               suspended_until=value['suspensions'][-1]['until'] if suspended else None)


def apply_departure(core, visit):
    if core.customer_discontent is not None and visit.departure_reason in ('queue_full', 'wait_timeout'):
        _change(core, visit.id, core.customer_discontent['rules']['waiting_gain'], visit.departure_reason)


def apply_service(core, result, advanced_evaluation, satisfaction=None):
    if core.customer_discontent is None:
        return
    selected = core.customer_discontent['rules']
    delta = selected['advanced_failure_gain'] if advanced_evaluation is not None and not advanced_evaluation['success'] else 0
    reasons = ['advanced_failure'] if delta else []
    good = satisfaction['level'] == 'satisfied' if satisfaction is not None else result['affinity_delta'] > 0
    if good:
        delta -= selected['good_service_recovery']; reasons.append('good_service')
    if satisfaction is not None and satisfaction['level'] == 'dissatisfied':
        delta += core.customer_satisfaction['dissatisfied_discontent_gain']; reasons.append('dissatisfied_service')
    _change(core, result['customer_id'], delta, '+'.join(reasons))


def available(core, customer_id, day):
    data = core.customer_discontent
    if data is None:
        return True
    value = data['customers'].get(customer_id)
    return value is None or not any(period['day'] < day <= period['until'] for period in value['suspensions'])


def filter_schedule(core, planned, day):
    return {key: tick for key, tick in planned.items() if available(core, key, day)}


def prepare(core, data):
    if not isinstance(data, dict) or set(data) != {'rules', 'customers'} or not isinstance(data['customers'], dict):
        raise ValueError('累積不満の記録が不正です。')
    selected = rules(data['rules'])
    for key, value in data['customers'].items():
        if (not isinstance(key, str) or not key or not isinstance(value, dict)
                or set(value) != {'score', 'score_day', 'suspensions'}
                or type(value['score']) not in (int, float) or not math.isfinite(value['score'])
                or not 0 <= value['score'] <= selected['threshold']
                or type(value['score_day']) is not int or not 1 <= value['score_day'] <= core.day
                or not isinstance(value['suspensions'], list)):
            raise ValueError('累積不満の記録が不正です。')
        previous = 0
        for period in value['suspensions']:
            if (not isinstance(period, dict) or set(period) != {'day', 'until'}
                    or type(period['day']) is not int or type(period['until']) is not int
                    or not previous < period['day'] <= core.day
                    or period['until'] != period['day']+selected['suspension_days']):
                raise ValueError('来店停止期間の記録が不正です。')
            previous = period['until']
    return copy.deepcopy(data)


def _simulate_change(state, selected, customer_id, day, delta):
    if delta == 0:
        return
    value = state.get(customer_id)
    if value is None:
        value = dict(score=0, score_day=0, suspensions=[])
    expired = value['suspensions'] and value['score_day'] <= value['suspensions'][-1]['until'] < day
    before = selected['return_score'] if expired else value['score']
    after = min(selected['threshold'], max(0, before+delta))
    if after == before:
        return
    state[customer_id] = value
    value['score'] = after
    value['score_day'] = day
    if before < selected['threshold'] <= after:
        value['suspensions'].append(dict(day=day, until=day+selected['suspension_days']))


def validate(core, data):
    data = prepare(core, data)
    selected = data['rules']
    from .cafe_checkpoint import outcome_result
    from .cafe_advanced_customers import evaluate
    from .cafe_customer_satisfaction import evaluate as evaluate_satisfaction
    outcomes = [outcome_result(value) for value in core.outcomes.values()]
    offset = 0
    expected = {}
    days = []
    for result in core.day_results:
        visits = result.get('customer_outcomes')
        valid_rows = (isinstance(visits, list) and all(isinstance(visit, dict)
                      and set(visit) == {'customer_id', 'reason', 'discontent'}
                      and isinstance(visit['customer_id'], str)
                      and (visit['reason'] in ('success', 'failure', 'queue_full', 'wait_timeout', 'closing', 'interaction_exhausted')
                           or isinstance(visit['reason'], str) and visit['reason'].startswith('interaction_'))
                      and type(visit['discontent']) in (int, float) and math.isfinite(visit['discontent'])
                      and visit['discontent'] >= 0 for visit in visits))
        if (not valid_rows or len(visits) != len(result['customer_visits'])
                or sorted(visit['customer_id'] for visit in visits) != result['customer_visits']):
            raise ValueError('累積不満の来店記録が不正です。')
        days.append((result['day'], result['summary']['completed_interactions'], visits))
    days.append((core.day, len(outcomes)-sum(count for _,count,_ in days),
                 [dict(customer_id=v.id, reason=v.departure_reason, discontent=v.discontent) for v in core.visits.values()]))
    for day, count, visits in days:
        for visit in visits:
            if visit['reason'] in ('queue_full', 'wait_timeout'):
                _simulate_change(expected, selected, visit['customer_id'], day, selected['waiting_gain'])
        for result in outcomes[offset:offset+count]:
            advanced = evaluate(core, result)
            satisfaction = evaluate_satisfaction(core, result, advanced)
            delta = selected['advanced_failure_gain'] if advanced is not None and not advanced['success'] else 0
            good = satisfaction['level'] == 'satisfied' if satisfaction is not None else result['affinity_delta'] > 0
            delta -= selected['good_service_recovery'] if good else 0
            if satisfaction is not None and satisfaction['level'] == 'dissatisfied':
                delta += core.customer_satisfaction['dissatisfied_discontent_gain']
            _simulate_change(expected, selected, result['customer_id'], day, delta)
        offset += count
    if data['customers'] != expected:
        raise ValueError('累積不満と来店・接客成果が一致しません。')
    return data
