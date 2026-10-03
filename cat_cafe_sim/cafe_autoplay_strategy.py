"""経営方針の準備判断。ゲーム状態の変更は返した通常操作に任せる。"""
from .cafe_autoplay_staffing import plan, expansion_reason
from .core import cafe_equipment, cafe_expansion, cafe_seat_equipment, cafe_goal, cafe_reservation, cafe_waiting_area


def reserve(core):
    """2日分の運営費と最低300を確保する。"""
    cost = (core.operating_cost or {}).get('rules', {})
    seats = len(cafe_seat_equipment.seats(core))
    return max(300, 2*(cost.get('base_cost', 0)+cost.get('per_seat_cost', 0)*(seats+1)))


def waiting_reserve(core, daily_cost=None):
    """待合の維持費も含め、増席後の2日分の運営費を残す。"""
    if daily_cost is None:
        daily_cost = cafe_waiting_area.daily_cost(core)
    cost = (core.operating_cost or {}).get('rules', {})
    seats = len(cafe_seat_equipment.seats(core))
    return max(reserve(core), 2*(cost.get('base_cost', 0)
               +cost.get('per_seat_cost', 0)*(seats+1)+daily_cost))


def waiting_investment(session, staffing, remaining, report=None):
    """待機の取りこぼしがあるとき、保存済みの待合設備を通常購入する。"""
    c = session.core
    if c.waiting_area is None or remaining <= 1:
        return None
    departures = c.day_results[-1]['summary'].get('departures', {}) if c.day_results else {}
    demand = staffing['arrivals'] > min(len(cafe_seat_equipment.seats(c)), len(staffing['workers']))
    if not demand and not any(departures.get(key, 0) for key in ('wait_timeout', 'queue_full')):
        return None
    if cafe_waiting_area.purchased(c):
        selected = cafe_waiting_area.upgrade_rules()
        problem = cafe_waiting_area.upgrade_reason(c, selected)
        action = lambda: session.upgrade_waiting_area(selected)
        label = '待合スペースの2段階目を強化'
    else:
        selected = c.waiting_area['rules']
        problem = cafe_waiting_area.reason(c)
        action = session.purchase_waiting_area
        label = '待合スペースを強化'
    buffer = waiting_reserve(c, selected['daily_cost'])
    if problem or c.funds-selected['cost'] < buffer:
        return None
    reason = (f'来店予定{staffing["arrivals"]}人・出勤候補{len(staffing["workers"])}匹、'
              f'前日の待機期限切れ{departures.get("wait_timeout", 0)}件・列満員退店{departures.get("queue_full", 0)}件。'
              f'待機枠と猶予を広げて接客を待てるようにする。費用{selected["cost"]:g}、'
              f'維持費{selected["daily_cost"]:g}/日、購入後の資金{c.funds-selected["cost"]:g}で予備資金{buffer:g}を確保')
    if report:
        report(label, '購入', reason)
    return f'{label}（{reason}）', action


def prepare(session, emit, name, report=None, mode="clear", *, objective="popularity"):
    c = session.core
    remaining = (cafe_goal.current_start(c.goal)+cafe_goal.current_rules(c.goal)['days']-c.day
                 if not c.goal.get('tracking_only') else float('inf'))
    duration = f'期限まで残り{remaining}日' if remaining != float('inf') else '目標期限なし'
    buffer = waiting_reserve(c) if mode == 'fast' and objective == 'popularity' else reserve(c)
    staffing = plan(session, mode=mode)
    limits = "疲労65・ストレス60以下で早期達成を優先" if mode == "fast" else "疲労・ストレスとも60以下で休養を優先"
    if emit:
        emit(f'{c.day}日目の来店予測: {staffing["arrivals"]}人 / 同時接客の見込み{staffing["peak"]}人 / 出勤候補{len(staffing["workers"])}匹')
    for rules, reason, action, label in (
        (cafe_equipment.rules(), cafe_equipment.reason, session.purchase_rest_space, '休養スペースを購入'),
        (cafe_expansion.rules(), cafe_expansion.reason, session.expand_seats, '席を増設'),
        (cafe_equipment.upgrade_rules(), cafe_equipment.upgrade_reason, session.upgrade_rest_space, '休養スペースを強化')):
        step = cafe_expansion.next_step(c, rules) if action==session.expand_seats else None
        cost = step['cost'] if step else rules.get('cost', 0)
        if action == session.expand_seats:
            if mode == 'fast' and objective == 'popularity':
                investment = waiting_investment(session, staffing, remaining, report)
                if investment:
                    return investment
            skipped = expansion_reason(c, staffing, mode=mode)
            if skipped:
                if report:
                    report('席の増設', '見送り', skipped)
                if emit:
                    emit('席の増設を見送り: '+skipped)
                continue
        if remaining>1 and not reason(c, rules) and c.funds-cost>=buffer:
            demand = (f'来店予定{staffing["arrivals"]}人、同時接客の見込み{staffing["peak"]}人、出勤候補{len(staffing["workers"])}匹。'
                      if action == session.expand_seats else '')
            if mode == 'fast' and action == session.expand_seats:
                demand += f'健康な担当可能猫{staffing["healthy"]}匹で休養交代と待機客・新客への対応を見込む。'
            if report:
                report(label.removesuffix('を購入').replace('を強化','の強化').replace('席を増設','席の増設'),
                       '購入', demand+f'費用{cost:g}、購入後の資金{c.funds-cost:g}で予備資金{buffer:g}を確保。{duration}')
            return f'{label}（{demand}費用{cost:g}、運営予備資金{buffer:g}を確保）', lambda action=action, rules=rules: action(rules)
    toy = next(row for row in cafe_seat_equipment.catalog() if row['id']=='toys')
    for key, seat in sorted(cafe_seat_equipment.seats(c).items()):
        if seat.equipment is None and c.funds-toy['cost']>=buffer and not cafe_seat_equipment.reason(c):
            if report:
                report(f'{key}のおもちゃセット', '購入', f'接客の関心を高める。費用{toy["cost"]:g}、購入後の資金{c.funds-toy["cost"]:g}で予備資金{buffer:g}を確保')
            return f'{key}に{toy["name"]}を購入（接客の関心を高め、{duration}、予備資金{buffer:g}を確保）', lambda key=key: session.purchase_seat_equipment(key, toy)
    selected = cafe_equipment.soundproof_rules()
    if remaining>1 and not cafe_equipment.soundproof_reason(c, selected) and c.funds-selected['cost']>=buffer:
        if report:
            report('休養スペースの防音改修', '購入', f'ストレス回復を強める。費用{selected["cost"]:g}、購入後の資金{c.funds-selected["cost"]:g}で予備資金{buffer:g}を確保')
        return f'休養スペースを防音改修（ストレス回復を強め、予備資金{buffer:g}を確保）', lambda: session.soundproof_rest_space(selected)

    workers = staffing['workers']
    basis = '前日の担当実績・好みの集中も考慮' if mode == 'fast' else '全来店客の接客量から1匹への集中上限を見積もる'
    predictions = {}
    for key, estimate in staffing['predictions'].items():
        fatigue, stress = estimate['fatigue'], estimate['stress']
        predictions[key] = (f'来店予定{staffing["arrivals"]}人・接客{estimate["actions"]}行動の目安。'
                            f'{basis}。出勤時の予測疲労{fatigue:g}・ストレス{stress:g}。{limits}し、必要人数まで出勤')
        if emit:
            emit(f'{c.day}日目の出勤予測: {name(key)} / 疲労 {fatigue:g} / ストレス {stress:g} / {"出勤" if key in workers else "休養"}')
    def report_workers(selected, reservation=False):
        if not report:
            return
        for key, cat in sorted(c.cats.items()):
            if c.activity(key)!='cafe':
                choice, reason = '不在', '在店していないため出勤対象外'
            elif cat.health_status!='healthy':
                choice, reason = '療養', '病気のため出勤対象外'
            else:
                choice = '出勤' if key in selected else '休養'
                reason = predictions.get(key, '担当不可のため休養')
                if reservation and key in selected:
                    reason += '。予約当日の休業を避け、最も負担の小さい健康な猫を配置'
            report(name(key), choice, reason, key)

    if not workers:
        if cafe_reservation.day_off_reason(c):
            healthy = [key for key, cat in c.cats.items() if c.activity(key)=='cafe' and cat.health_status=='healthy']
            workers = sorted(healthy, key=lambda key: (c.cats[key].fatigue+c.management['stress'][key], key))[:1]
            report_workers(workers, reservation=True)
            if set(workers)!=c.working_cats:
                return '予約当日の休業を避け、最も負担の小さい健康な猫を配置', lambda: session.set_shifts(workers)
            return '予約当日は営業を継続（全員療養時は接客できないまま結果を確認）', session.automatic_step
        report_workers(workers)
        if report:
            report('営業', '休業', '来店予定または予測条件を満たす出勤候補がないため負担を回復')
        return '来店予定または安全な出勤候補がないため休業（負担を回復）', session.day_off
    report_workers(workers)
    if set(workers)!=c.working_cats:
        return f'予測で出勤を設定: {", ".join(map(name, workers))}（{limits}）', lambda: session.set_shifts(workers)
    return f'予測で決めた出勤予定で営業開始（{duration}）', session.automatic_step
