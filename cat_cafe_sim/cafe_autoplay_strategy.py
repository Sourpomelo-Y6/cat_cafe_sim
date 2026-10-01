"""クリア方針の準備判断。ゲーム状態の変更は返した通常操作に任せる。"""
from .cafe_shift_forecast import shift_forecast
from .core import cafe_equipment, cafe_expansion, cafe_seat_equipment, cafe_goal, cafe_reservation
from .core.cafe_traits import effect


def reserve(core):
    """2日分の運営費と最低300を確保する。"""
    cost = (core.operating_cost or {}).get('rules', {})
    seats = len(cafe_seat_equipment.seats(core))
    return max(300, 2*(cost.get('base_cost', 0)+cost.get('per_seat_cost', 0)*(seats+1)))


def prepare(session, emit, name):
    c = session.core
    remaining = cafe_goal.current_start(c.goal)+cafe_goal.current_rules(c.goal)['days']-c.day
    buffer = reserve(c)
    for rules, reason, action, label in (
        (cafe_equipment.rules(), cafe_equipment.reason, session.purchase_rest_space, '休養スペースを購入'),
        (cafe_expansion.rules(), cafe_expansion.reason, session.expand_seats, '席を増設'),
        (cafe_equipment.upgrade_rules(), cafe_equipment.upgrade_reason, session.upgrade_rest_space, '休養スペースを強化')):
        step = cafe_expansion.next_step(c, rules) if action==session.expand_seats else None
        cost = step['cost'] if step else rules.get('cost', 0)
        if remaining>1 and not reason(c, rules) and c.funds-cost>=buffer:
            return f'{label}（費用{cost:g}、運営予備資金{buffer:g}を確保）', lambda action=action, rules=rules: action(rules)
    toy = next(row for row in cafe_seat_equipment.catalog() if row['id']=='toys')
    for key, seat in sorted(cafe_seat_equipment.seats(c).items()):
        if seat.equipment is None and c.funds-toy['cost']>=buffer and not cafe_seat_equipment.reason(c):
            return f'{key}に{toy["name"]}を購入（接客の関心を高め、残り{remaining}日、予備資金{buffer:g}を確保）', lambda key=key: session.purchase_seat_equipment(key, toy)
    selected = cafe_equipment.soundproof_rules()
    if remaining>1 and not cafe_equipment.soundproof_reason(c, selected) and c.funds-selected['cost']>=buffer:
        return f'休養スペースを防音改修（ストレス回復を強め、予備資金{buffer:g}を確保）', lambda: session.soundproof_rest_space(selected)

    workers = []
    for key, cat in sorted(c.cats.items()):
        if c.activity(key)!='cafe' or cat.health_status!='healthy':
            continue
        forecast = shift_forecast(c, key)
        # 休んだ前日や初日の0行動を、出勤しても負担ゼロとは扱わない。
        actions = max(20, forecast['previous_actions'] or 0)
        if forecast['work'] is not None and forecast['previous_actions']>=20:
            fatigue = forecast['work']['fatigue']
            stress = forecast['work_stress']
        else:
            fatigue = min(c.shift_rules.max_fatigue, cat.fatigue+actions*c.shift_rules.fatigue_per_service_tick*effect(c, key, 'service_fatigue'))
            stress = min(100, c.management['stress'][key]+actions*c.management['rules']['stress_per_service_tick']*effect(c, key, 'service_stress'))
        if fatigue<=60 and stress<=60:
            workers.append(key)
        if emit:
            emit(f'{c.day}日目の出勤予測: {name(key)} / 疲労 {fatigue:g} / ストレス {stress:g} / {"出勤" if key in workers else "休養"}')
    if not workers:
        if cafe_reservation.day_off_reason(c):
            healthy = [key for key, cat in c.cats.items() if c.activity(key)=='cafe' and cat.health_status=='healthy']
            workers = sorted(healthy, key=lambda key: (c.cats[key].fatigue+c.management['stress'][key], key))[:1]
            if set(workers)!=c.working_cats:
                return '予約当日の休業を避け、最も負担の小さい健康な猫を配置', lambda: session.set_shifts(workers)
            return '予約当日は営業を継続（全員療養時は接客できないまま結果を確認）', session.automatic_step
        return '出勤予測が全員60を超えるため休業（負担を回復）', session.day_off
    if set(workers)!=c.working_cats:
        return f'予測で出勤を設定: {", ".join(map(name, workers))}（疲労・ストレスとも60以下）', lambda: session.set_shifts(workers)
    return f'予測で決めた出勤予定で営業開始（目標期限まで残り{remaining}日）', session.automatic_step
