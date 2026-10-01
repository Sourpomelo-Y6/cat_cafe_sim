"""保存済みの来店予定から、クリア方針の出勤と席投資を見積もる。"""
from math import ceil

from .core.cafe_weekdays import schedule
from .core.cafe_traits import effect


def plan(session):
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
    predictions = {}
    workers = []
    for key in healthy:
        cat = core.cats[key]
        fatigue = min(core.shift_rules.max_fatigue,
                      cat.fatigue+actions*core.shift_rules.fatigue_per_service_tick*effect(core,key,'service_fatigue'))
        stress = min(100, core.management['stress'][key]+actions*core.management['rules']['stress_per_service_tick']*effect(core,key,'service_stress'))
        predictions[key] = dict(fatigue=fatigue, stress=stress, actions=actions)
        if fatigue <= 60 and stress <= 60 and len(workers) < desired:
            workers.append(key)
    return dict(arrivals=len(arrivals), peak=peak, workload=workload,
                desired=desired, workers=workers, predictions=predictions)


def expansion_reason(core, staffing):
    from .core.cafe_seat_equipment import seats
    count = len(seats(core))
    if len(staffing['workers']) <= count:
        return f"担当可能な出勤候補{len(staffing['workers'])}匹に対して既存{count}席で足りるため"
    if staffing['peak'] <= count:
        return f"来店予定{staffing['arrivals']}人・同時接客の見込み{staffing['peak']}人に対して既存{count}席で足りるため"
    return ''
