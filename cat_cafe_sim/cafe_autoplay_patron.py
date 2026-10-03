"""有力者向けの育成・休養。係数や派遣条件は変更せず通常操作を返す。"""
from .cafe_autoplay_staffing import plan
from .core import cafe_reservation


def roles(core):
    """未達の厳格型に必要な白猫を育成中・派遣待ちに分ける。"""
    members = (core.patron or {}).get('rules', {}).get('members', [])
    strict = next((row for row in members if row['id']=='patron_strict_visit'), None)
    if not strict or core.patron['members'][strict['id']] >= strict['target']:
        return [], []
    white = sorted(key for key, features in (core.cat_features or {}).items()
                   if 'white' in features and key in core.cats and core.activity(key)!='adopted')
    growth = (core.growth or {}).get('cats', {})
    trained = [key for key in white if growth.get(key, {}).get('specialization')=='service']
    if trained:
        # 条件を満たす派遣役が一匹いれば、残る白猫は通常の出勤判断に戻す。
        selected = min(trained, key=lambda key: (core.activity(key)!='cafe',
                        core.cats[key].health_status!='healthy',
                        core.cats[key].fatigue+core.management['stress'][key], key))
        return [], [selected]
    trainees = [key for key in white if growth.get(key, {}).get('specialization') is None]
    return trainees[:1], []


def dispatch_reason(core, cat_id):
    trainees, _ = roles(core)
    if cat_id in trainees:
        return '厳格型に必要な白猫を接客の得意分野へ育成するため在店'
    if core.management['stress'][cat_id] > 60:
        return 'ストレス60以下まで休養してから派遣'
    return ''


def prepare(player):
    session, core = player.session, player.session.core
    trainees, reserved = roles(core)
    # 有力者の安定・積極経営はともに安全側の接客上限を使う。
    staffing = plan(session, mode='clear', priority=trainees, resting=reserved)
    workers = staffing['workers']
    reservation = not workers and bool(cafe_reservation.day_off_reason(core))
    # 予約で休業できない場合も、安全な候補がなければ出勤なしで営業する。
    for key, cat in sorted(core.cats.items()):
        estimate = staffing['predictions'].get(key)
        if core.activity(key) != 'cafe':
            choice, reason = '不在', '在店していないため出勤対象外'
        elif cat.health_status != 'healthy':
            choice, reason = '療養', '病気のため出勤対象外'
        else:
            choice = '出勤' if key in workers else '休養'
            reason = (f'来店予定{staffing["arrivals"]}人。接客集中の上限から予測疲労'
                      f'{estimate["fatigue"]:g}・ストレス{estimate["stress"]:g}、ともに60以下を出勤条件にする'
                      if estimate else '接客を担当できる体力・状態がないため休養')
            if key in trainees:
                reason += '。厳格型に必要な白猫の接客育成を安全な範囲で優先'
            if key in reserved:
                reason += '。厳格型への派遣役を休養して準備'
        player._decision(player._name(key), choice, reason, key)
    if not workers and not reservation:
        player._decision('営業', '休業', '安全な出勤候補がいないため全員の負担を回復')
        return '有力者向けの休業（安全な出勤候補がないため回復）', session.day_off
    if set(workers) != core.working_cats:
        return '有力者向けの出勤を設定（接客負担の予測・白猫の育成・派遣役の休養）', lambda: session.set_shifts(workers)
    return '有力者向けの出勤予定で営業開始（予測疲労・ストレス60以下）', session.automatic_step
