"""保存済みの営業記録から作る、読み取り専用の顧客名簿と当日の予定。"""
import re
from .core.cafe_preferences import FEATURES, preference_for

# IDとの対応は保存再開・既存ゲームで維持する。追加するときも順番を変更しない。
_NAMES = ('佐藤', '鈴木', '高橋', '田中', '伊藤', '渡辺', '山本', '中村', '小林', '加藤',
          '吉田', '山田', '佐々木', '山口', '松本', '井上', '木村', '林', '清水', '斎藤')


def number(customer_id):
    found = re.fullmatch(r'guest-([1-9][0-9]*)', customer_id)
    return int(found[1]) if found else None


def customer_name(customer_id):
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
    schedule = arrival_schedule(core)
    tomorrow = arrival_schedule(core, core.day + 1)
    all_customers = {f'guest-{i+1}' for i in range(len(core.config.arrival_ticks))}
    known = all_customers | set(core.visits) | core.returning_customers | {guest for _, guest in session.affinities}
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
        if visit:
            status = '待機中' if key in core.queue else '接客中' if visit.departure_reason is None else '退店済み'
        elif planned is not None:
            status = '来店なし（休業・終了）' if core.closed else '来店予定'
        else:
            status = '本日の予定なし'
        rows.append(dict(customer_id=key, name=customer_name(key), visits=count,
                         arrival_tick=planned, tomorrow_tick=tomorrow.get(key),
                         weekdays='・'.join(DAYS[d] for d in customer_days(core, index-1)) if key in all_customers and core.weekdays else '毎日' if key in all_customers else '—',
                         status=status, preference=preferred,
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
