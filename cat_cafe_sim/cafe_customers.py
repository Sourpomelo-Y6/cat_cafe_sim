"""保存済みの営業記録から作る、読み取り専用の顧客名簿と当日の予定。"""
import re
from .core.cafe_preferences import FEATURES, preference_for
from .core.cafe_advanced_customers import CUSTOMER_ID, NAME
from .core.cafe_expansion import EXTRA_CUSTOMER_ID, four_seat_purchase

# IDとの対応は保存再開・既存ゲームで維持する。追加するときも順番を変更しない。
_NAMES = ('佐藤', '鈴木', '高橋', '田中', '伊藤', '渡辺', '山本', '中村', '小林', '加藤',
          '吉田', '山田', '佐々木', '山口', '松本', '井上', '木村', '林', '清水', '斎藤')


def number(customer_id):
    found = re.fullmatch(r'guest-([1-9][0-9]*)', customer_id)
    return int(found[1]) if found else None


def customer_name(customer_id):
    if customer_id == CUSTOMER_ID:
        return NAME
    if customer_id == EXTRA_CUSTOMER_ID:
        return '増設で来店したお客さん'
    from .core.cafe_reservation import CUSTOMER_ID as RESERVATION_ID,NAME as RESERVATION_NAME
    if customer_id==RESERVATION_ID:return RESERVATION_NAME
    index = number(customer_id)
    if index is None:
        return customer_id
    return f'{_NAMES[index-1]}さん' if index <= len(_NAMES) else f'お客さん{index}'


def customer_label(customer_id):
    name = customer_name(customer_id)
    return f'{name}（{customer_id}）' if name != customer_id else customer_id


def preference(core, customer_id):
    data = core.customer_preferences
    if data is None:
        return None
    if core.advanced_customers is not None and customer_id == CUSTOMER_ID:
        return core.advanced_customers['feature']
    from .core.cafe_reservation import CUSTOMER_ID as RESERVATION_ID
    if core.reservation is not None and customer_id==RESERVATION_ID:return core.reservation['rules']['feature']
    if customer_id == EXTRA_CUSTOMER_ID and four_seat_purchase(core):
        return preference_for(core.seed, customer_id, data['rules']['pool'])
    existing = data['customers'].get(customer_id)
    if existing is not None:
        return existing
    index = number(customer_id)
    if index is not None and index <= len(core.config.arrival_ticks):
        return preference_for(core.seed, customer_id, data['rules']['pool'])
    return None


def directory(session):
    core = session.core
    from .core.cafe_weekdays import schedule as arrival_schedule, customer_days, DAYS
    from .core.cafe_customer_loyalty import row as loyalty_row, extra_weekday
    from .core.cafe_customer_discontent import row as discontent_row
    from .core.cafe_customer_satisfaction import latest as latest_satisfaction
    from .core.cafe_customer_trust import row as trust_row
    schedule = arrival_schedule(core)
    tomorrow = arrival_schedule(core, core.day + 1)
    all_customers = {f'guest-{i+1}' for i in range(len(core.config.arrival_ticks))}
    known = all_customers | set(core.visits) | core.returning_customers | {guest for _, guest in session.affinities}
    known |= set((core.customer_trust or {}).get('customers',{}))
    if core.advanced_customers is not None:
        known.add(CUSTOMER_ID)
    if four_seat_purchase(core):
        known.add(EXTRA_CUSTOMER_ID)
    if core.reservation is not None:
        from .core.cafe_reservation import CUSTOMER_ID as RESERVATION_ID
        known.add(RESERVATION_ID)
    rows = []
    for key in sorted(known, key=lambda key: (number(key) is None, number(key) or 0, key)):
        index = number(key)
        # 曜日導入後は実際の来店IDを集計。旧セーブは固定順序の来店数から復元。
        count = sum(int(key in day['customer_visits']) if core.weekdays is not None else
                    int(index is not None and index <= day['summary']['arrivals']) for day in core.day_results)
        count += int(key in core.visits)
        visit = core.visits.get(key)
        planned = schedule.get(key)
        preferred = preference(core, key)
        loyalty = loyalty_row(core, key)
        discontent = discontent_row(core, key)
        satisfaction = latest_satisfaction(core, key)
        trust = trust_row(core,key)
        if visit:
            status = '待機中' if key in core.queue else '接客中' if visit.departure_reason is None else '退店済み'
        elif planned is not None:
            status = '来店なし（休業・終了）' if core.closed else '来店予定'
        else:
            status = '本日の予定なし'
        if key == CUSTOMER_ID and core.advanced_customers is not None:
            from .core.cafe_advanced_customers import unlocked_day
            if unlocked_day(core) is None:
                status = '未解放（人気第1段階）'
        from .core.cafe_reservation import CUSTOMER_ID as RESERVATION_ID,second_cleared_day
        if key==RESERVATION_ID and core.reservation is not None:
            request=core.reservation['request']
            if second_cleared_day(core) is None:status='未解放（人気第2段階）'
            elif request is None:status='予約依頼の準備前'
            elif request['status']=='waiting':status='予約依頼への回答待ち'
            elif request['status']=='declined':status='予約を見送り'
            elif request['result'] is not None:status={'success':'条件達成','failure':'条件未達','unserved':'未接客'}[request['result']]
        if discontent and discontent['suspended_until'] is not None:
            status = f"来店停止（{discontent['suspended_until']}日目まで）"
        if trust and trust['status']=='recovery':status='信頼回復中'
        if trust and trust['status']=='waiting':status='信頼回復の回答待ち'
        if trust and trust['status']=='departed':status=f"永久離脱（{trust['departed_day']}日目）"
        tomorrow_discontent = discontent_row(core, key, core.day+1)
        weekday_text = '・'.join(DAYS[d] for d in customer_days(core, index-1)) if key in all_customers and core.weekdays else '毎日' if key in all_customers else '—'
        if loyalty and loyalty['regular_day'] is not None and weekday_text != '毎日':
            weekday_text += f"＋常連:{DAYS[extra_weekday(core,key)]}"
        rows.append(dict(customer_id=key, name=customer_name(key), visits=count,
                         arrival_tick=planned, tomorrow_tick=tomorrow.get(key),
                         weekdays=weekday_text,
                         status=status, preference=preferred,
                         loyalty=loyalty['score'] if loyalty else None,
                         regular_day=loyalty['regular_day'] if loyalty else None,
                         loyalty_target=core.customer_loyalty['rules']['threshold'] if core.customer_loyalty else None,
                         discontent=discontent['score'] if discontent else None,
                         discontent_target=core.customer_discontent['rules']['threshold'] if core.customer_discontent else None,
                         discontent_return=core.customer_discontent['rules']['return_score'] if core.customer_discontent else None,
                         suspended_until=discontent['suspended_until'] if discontent else None,
                         tomorrow_suspended_until=tomorrow_discontent['suspended_until'] if tomorrow_discontent else None,
                         satisfaction=satisfaction,
                         trust=trust,
                         preference_text=FEATURES[preferred][0]+'好き' if preferred else '未設定'))
    return rows


def cat_rows(session, customer_id):
    preferred = preference(session.core, customer_id)
    rows = []
    for cat in session.cat_choices(customer_id):
        features = (session.core.cat_features or {}).get(cat['cat_id'], [])
        matched = preferred is not None and preferred in features
        rows.append(dict(cat, activity=session.core.activity(cat['cat_id']), matches=matched,
                         match_text='好みに一致' if matched else '好み未設定' if preferred is None else '一致なし'))
    return rows
