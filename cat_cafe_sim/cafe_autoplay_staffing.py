"""保存済みの来店予定から、経営方針の出勤と席投資を見積もる。"""
from math import ceil

from .core.cafe_weekdays import schedule
from .core.cafe_traits import effect


def plan(session, mode="clear"):
    core = session.core
    arrivals = schedule(core)
    duration = session.interaction_config.ticks
    workload = sum(min(duration, core.config.opening_ticks-tick) for tick in arrivals.values())
    # 来店時点から通常の交流時間を使った重なり。待機や早期終了を推測しない。
    peak = max((sum(start <= tick < min(core.config.opening_ticks, start+duration)
                    for start in arrivals.values()) for tick in arrivals.values()), default=0)
    healthy = [key for key, cat in core.cats.items()
               if core.activity(key) == 'cafe' and cat.health_status == 'healthy'
               and cat.stamina > 0 and not cat.cannot_continue]
    healthy.sort(key=lambda key: (core.cats[key].fatigue+core.management['stress'][key], key))
    desired = min(len(healthy), max(peak, ceil(workload/20)))
    from .core.cafe_seat_equipment import seats
    capacity = len(seats(core))*core.config.opening_ticks
    actions = max(20, ceil(min(workload, capacity)/max(1, desired)))
    # 両経営方針は前日の担当実績と好みの集中も見積もる。
    # 好みは公開済みの固定設定から求め、来店記録を作らない。
    from .core.cafe_preferences import customer_preference
    preferences = core.customer_preferences
    predicted_preferences = ({key: customer_preference(core, key, preferences['rules'])
                              for key in arrivals} if preferences else {})
    previous = core.day_results[-1].get('cats', {}) if core.day_results else {}
    predictions = {}
    workers = []
    for key in healthy:
        cat = core.cats[key]
        individual = actions
        if mode in ('clear', 'fast'):
            features = (core.cat_features or {}).get(key, [])
            matched_work = sum(min(duration, core.config.opening_ticks-tick)
                               for customer, tick in arrivals.items()
                               if predicted_preferences.get(customer) in features)
            individual = max(actions, min(core.config.opening_ticks, matched_work),
                             min(core.config.opening_ticks, previous.get(key, {}).get('service_ticks', 0)))
        fatigue_limit, stress_limit = (65, 60) if mode == 'fast' else (60, 60)
        fatigue = min(core.shift_rules.max_fatigue,
                      cat.fatigue+individual*core.shift_rules.fatigue_per_service_tick*effect(core,key,'service_fatigue'))
        stress = min(100, core.management['stress'][key]+individual*core.management['rules']['stress_per_service_tick']*effect(core,key,'service_stress'))
        predictions[key] = dict(fatigue=fatigue, stress=stress, actions=individual)
        if fatigue <= fatigue_limit and stress <= stress_limit and len(workers) < desired:
            workers.append(key)
    return dict(arrivals=len(arrivals), peak=peak, workload=workload,
                desired=desired, workers=workers, predictions=predictions, healthy=len(healthy))


def expansion_reason(core, staffing, mode="clear"):
    from .core.cafe_seat_equipment import seats
    count = len(seats(core))
    if mode == 'fast' and staffing['arrivals'] > count and staffing['healthy'] > count:
        # 休養交代も含めて使える猫がいれば、待機客と増設による新客に備える。
        return ''
    if len(staffing['workers']) <= count:
        return f"担当可能な出勤候補{len(staffing['workers'])}匹に対して既存{count}席で足りるため"
    if staffing['peak'] <= count:
        return f"来店予定{staffing['arrivals']}人・同時接客の見込み{staffing['peak']}人に対して既存{count}席で足りるため"
    return ''
