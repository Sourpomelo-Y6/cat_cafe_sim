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
    waiting = []
    if player.mode == 'fast':
        from .core.cafe_patron import destinations
        for destination in destinations(core):
            member = next((row for row in core.patron['rules'].get('members', [])
                           if row['id'] == destination['id']), None)
            if member and core.patron['members'][member['id']] < member['target']:
                cat = matching_wait_cat(core, destination)
                if cat is not None:
                    waiting.append(cat)
        reserved = list(dict.fromkeys([*reserved, *waiting]))
    # 両方針とも安全側の接客上限を使い、積極経営は希望一致の派遣待ちも休養する。
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
            if key in waiting:
                reason += '。希望に一致する有力者への派遣待ちとして休養'
            elif key in reserved:
                reason += '。厳格型への派遣役を休養して準備'
        player._decision(player._name(key), choice, reason, key)
    if not workers and not reservation:
        player._decision('営業', '休業', '安全な出勤候補がいないため全員の負担を回復')
        return '有力者向けの休業（安全な出勤候補がないため回復）', session.day_off
    if set(workers) != core.working_cats:
        return '有力者向けの出勤を設定（接客負担の予測・白猫の育成・派遣役の休養）', lambda: session.set_shifts(workers)
    return '有力者向けの出勤予定で営業開始（予測疲労・ストレス60以下）', session.automatic_step


def recruit_for_conditions(player):
    """未達の有力者の希望で不足する特徴を、公開された保護猫候補から補う。"""
    if player.mode != 'fast':
        return None
    from .core import cafe_housing
    from .cafe_autoplay_strategy import reserve
    session, core = player.session, player.session.core
    needed = {condition['feature'] for member in core.patron['rules'].get('members', [])
              if core.patron['members'][member['id']] < member['target']
              for condition in member['conditions'] if 'feature' in condition}
    present = {feature for key in core.cats if core.activity(key) != 'adopted'
               for feature in (core.cat_features or {}).get(key, [])}
    missing = needed-present
    if not missing or cafe_housing.admission_reason(core) or core.funds <= reserve(core):
        return None
    if core.recruitment is None:
        player._decision('保護猫', '候補を確認', '有力者の希望に不足する特徴を通常の候補から探す')
        return '有力者の希望に合う保護猫の候補を確認', session.open_recruitment
    candidates = [(row['cost'], key, row) for key, row in core.recruitment['candidates'].items()
                  if key not in core.cats and key not in core.recruitment['accepted']
                  and missing.intersection(row.get('features', []))
                  and core.funds > row['cost'] and core.funds-row['cost'] >= reserve(core)]
    if not candidates:
        return None
    _, key, row = min(candidates, key=lambda item: (item[0], item[1]))
    player._decision(row['name'], '受け入れ',
                     f"有力者の希望に不足する特徴を補う。費用{row['cost']:g}、運営予備資金{reserve(core):g}を確保", key)
    return f"有力者の希望のため{row['name']}を受け入れ", lambda: session.recruit_cat(key)


def matching_wait_cat(core, destination):
    """一致する猫が一時的に派遣できない場合の休養役。育成役は待たない。"""
    from .core import cafe_activities, cafe_patron_members
    from .core.cafe_traits import trait
    trainees, _ = roles(core)
    matching = [key for key in core.cats if core.activity(key) == 'cafe' and key not in trainees
                and (cafe_patron_members.terms(core, key, destination['id']) or {}).get('matched')
                and ('required_trait' not in destination
                     or (trait(core, key) or {}).get('id') == destination['required_trait'])]
    if not matching or any(not cafe_activities.dispatch_reason(core, key, destination)
                           and not dispatch_reason(core, key) for key in matching):
        return None
    return min(matching, key=lambda key: (core.cats[key].health_status != 'healthy',
                                         core.cats[key].fatigue, core.management['stress'][key], key))
