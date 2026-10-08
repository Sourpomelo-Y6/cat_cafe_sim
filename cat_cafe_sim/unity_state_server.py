"""Loopback state, shifts and one-day business adapter for Unity."""
import argparse
import copy
import json
import tempfile
import uuid
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


CONTENT_IDS = {f'cat-{name}': f'playtest-{name}' for name in ('mike', 'tama', 'sora', 'kohaku', 'mugi')}


def intake_view(session):
    from .core.cafe_intake_request import pending, require_response
    from .core.cafe_housing import status as housing_status, admission_reason
    from .core.cafe_preferences import feature_text
    from .core.cafe_traits import description
    from .core.human_cat_types import Personality
    from .storage.cafe_saves import check_link
    core = session.core
    data = core.intake_request
    if not data:
        return None
    rule = data['rules']
    row = rule['candidate']
    response_reason = ''
    if pending(core):
        try:
            check_link(session)
            if session.pending:
                raise ValueError('先に接客結果の保存を再試行してください。')
            require_response(core)
        except ValueError as ex:
            response_reason = str(ex)
    accept_reason = response_reason or admission_reason(core) or (
        '受け入れ後に資金が残る必要があります。' if core.funds <= row['cost'] else '')
    personality = Personality.from_dict(row['personality'])
    return dict(cat_id=rule['cat_id'], name=row['name'], day=rule['day'], status=data['status'],
                cost=row['cost'], personality=next((name for name, value in session.presets.items()
                                                   if value == personality), 'カスタム'),
                features=feature_text(row.get('features', [])),
                trait='\n'.join(f'{label}：{value}' for label, value in description(row.get('trait'))),
                housing=housing_status(core), response_reason=response_reason, accept_reason=accept_reason,
                can_decline=pending(core) and not response_reason,
                can_accept=pending(core) and not accept_reason)


def customer_trust_view(session):
    from .cafe_customers import customer_name
    data = session.core.customer_trust
    if data is None:
        return None
    rows = []
    for event in data['events'].values():
        reason = ''
        if event['status'] == 'waiting':
            try:
                copy.deepcopy(session).resolve_customer_trust(event['id'], 'recover')
            except ValueError as ex:
                reason = str(ex)
        rows.append(dict(event_id=event['id'], customer_id=event['customer_id'], name=customer_name(event['customer_id']),
                         day=event['day'], suspensions=event['suspensions'], status=event['status'], outcome=event['outcome'] or '',
                         choice=event['choice'] or '', resolved_day=event['resolved_day'] or 0,
                         reason=reason, can_respond=event['status'] == 'waiting' and not reason))
    return dict(popularity_loss=data['rules']['popularity_loss'], events=rows)


def reservation_view(session):
    from .core.cafe_reservation import CUSTOMER_ID
    from .cafe_customers import customer_name, customer_description
    data = session.core.reservation
    if data is None:
        return None
    row = data['request']
    rules = data['rules']
    reason = ''
    if row and row['status'] == 'waiting':
        try:
            copy.deepcopy(session).resolve_reservation('decline')
        except ValueError as ex:
            reason = str(ex)
    can_respond = bool(row and row['status'] == 'waiting' and not reason)
    return dict(event_id=row['id'] if row else '', status=row['status'] if row else 'untriggered',
                customer_id=CUSTOMER_ID, name=customer_name(CUSTOMER_ID), description=customer_description(CUSTOMER_ID),
                offered_day=row['offered_day'] if row else 0, visit_day=row['visit_day'] if row else 0,
                resolved_day=(row['resolved_day'] or 0) if row else 0, result=(row['result'] or '') if row else '',
                open_up_count=rules['open_up_count'], arrival_tick=rules['arrival_tick'],
                bonus=rules['bonus'], popularity_bonus=rules['popularity_bonus'],
                reason=reason, can_accept=can_respond, can_decline=can_respond)


def items_view(session):
    from .core.cafe_items import inventory, rewards, effect_text, unavailable_reason, current, after_value, change_text, stat
    from .core.cafe_item_shop import catalog, reason as purchase_reason
    from .core.cafe_item_sales import prices, reason as sell_reason
    from .core.cafe_activities import ACTIVITY_LABELS
    core = session.core
    problem = ''
    try:
        session._ready()
    except ValueError as ex:
        problem = str(ex)
    owned = inventory(core)
    sale_prices = prices()
    shop = []
    for row in catalog():
        reason = problem or purchase_reason(core,row)
        shop.append(dict(choice=row['item']['id'],name=row['item']['name'],effect=effect_text(row['item']),cost=row['cost'],
                         count=sum(item==row['item'] for item in owned.values()),funds_after=core.funds-row['cost'],
                         ends_game=core.management is not None and core.funds==row['cost'],reason=reason,can_select=not reason))
    groups = {}
    for source,item in owned.items():
        key = json.dumps(item,sort_keys=True,ensure_ascii=False)
        groups.setdefault(key,[]).append(source)
    holdings = []
    for sources in groups.values():
        source = sources[0]
        item = owned[source]
        price = sale_prices.get(item['id'])
        reason = problem or sell_reason(core,source) or ('売却価格が設定されていません。' if price is None else '')
        targets = []
        for cat_id in core.cats:
            use_reason = problem or unavailable_reason(core,source,cat_id)
            changes = ''
            if (stat(item) not in ('stress','both') or core.management is not None) and (stat(item) not in ('fatigue','both') or core.shift_rules is not None):
                before = current(core,item,cat_id)
                changes = change_text(item,before,after_value(item,before))
            targets.append(dict(cat_id=cat_id,name=session.profiles[cat_id]['name'],activity=ACTIVITY_LABELS[core.activity(cat_id)],
                                changes=changes,reason=use_reason,can_select=not use_reason))
        holdings.append(dict(choice=source,item_id=item['id'],name=item['name'],effect=effect_text(item),count=len(sources),
                             price=price or 0,funds_after=core.funds+(price or 0),reason=reason,can_sell=not reason,targets=targets))
    available = rewards(core)
    history = []
    for row in core.item_purchases:
        history.append(f"{row['day']}日目 購入：{row['item']['name']} / 費用 {row['cost']:g}")
    for row in core.item_uses:
        item = available[row['source']]['item']
        history.append(f"{row['day']}日目 使用：{item['name']} / {session.profiles[row['cat_id']]['name']} / "+change_text(item,row['before'],row['after']))
    for row in core.item_sales:
        history.append(f"{row['day']}日目 売却：{available[row['source']]['item']['name']} / 収入 {row['price']:g}")
    return dict(shop=shop,owned=holdings,history='\n'.join(history),count=len(owned))


def dispatch_introductions_view(session):
    from .core.cafe_dispatch_introduction import introductions, response_reason, admission_reason
    from .core.cafe_housing import status as housing_status
    from .core.cafe_preferences import feature_text
    from .core.cafe_traits import description
    from .core.human_cat_types import Personality
    from .storage.cafe_saves import check_link
    core = session.core
    result = []
    for event in introductions(core):
        data = event['introduction']
        row = data['candidate']
        problem = ''
        if data['status'] == 'waiting':
            try:
                check_link(session)
                if session.pending:
                    raise ValueError('先に接客結果の保存を再試行してください。')
            except ValueError as ex:
                problem = str(ex)
            problem = problem or response_reason(core,event['id'])
        admission = problem or (admission_reason(core,event['id']) if data['status']=='waiting' else '')
        personality = Personality.from_dict(row['personality'])
        result.append(dict(event_id=event['id'],cat_id=data['cat_id'],content_cat_id=CONTENT_IDS.get(data['cat_id'],data['cat_id']),
                           name=row['name'],status=data['status'],destination=event['destination']['name'],
                           sender_name=session.profiles[event['cat_id']]['name'],presented_day=data['presented_day'] or 0,resolved_day=data['resolved_day'] or 0,
                           cost=row['cost'],funds_after=core.funds-row['cost'],housing=housing_status(core),
                           personality=next((name for name,value in session.presets.items() if value==personality),'カスタム'),features=feature_text(row.get('features',[])),
                           trait='\n'.join(f'{label}：{value}' for label,value in description(row.get('trait'))),
                           preferences='\n'.join(f'好み：{kind.name} {value:g}' for kind,value in zip(session.interaction_config.types,personality.type_preferences)),
                           response_reason=problem,accept_reason=admission,
                           can_decline=data['status']=='waiting' and not problem,can_accept=data['status']=='waiting' and not admission))
    return result


def regular_introduction_view(session):
    from .core.cafe_regular_introduction import response_reason, admission_reason
    from .core.cafe_housing import status as housing_status
    from .core.cafe_preferences import feature_text
    from .core.cafe_traits import description
    from .core.human_cat_types import Personality
    from .storage.cafe_saves import check_link
    from .cafe_customers import customer_name
    core = session.core
    data = core.regular_introduction
    if not data:
        return None
    rule = data['rules']
    row = rule['candidate']
    problem = ''
    if data['status'] == 'waiting':
        try:
            check_link(session)
            if session.pending:
                raise ValueError('先に接客結果の保存を再試行してください。')
        except ValueError as ex:
            problem = str(ex)
        problem = problem or response_reason(core)
    admission = problem or (admission_reason(core) if data['status'] == 'waiting' else '')
    personality = Personality.from_dict(row['personality'])
    return dict(cat_id=rule['cat_id'], content_cat_id=CONTENT_IDS.get(rule['cat_id'], rule['cat_id']),
                name=row['name'], status=data['status'], customer_id=data['customer_id'] or '',
                customer_name=customer_name(data['customer_id']) if data['customer_id'] else '',
                presented_day=data['presented_day'] or 0, resolved_day=data['resolved_day'] or 0,
                threshold=core.customer_loyalty['rules']['threshold'],
                cost=row['cost'], funds_after=core.funds-row['cost'], housing=housing_status(core),
                personality=next((name for name, value in session.presets.items() if value == personality), 'カスタム'),
                features=feature_text(row.get('features', [])),
                trait='\n'.join(f'{label}：{value}' for label, value in description(row.get('trait'))),
                preferences='\n'.join(f'好み：{kind.name} {value:g}' for kind, value in zip(session.interaction_config.types, personality.type_preferences)),
                response_reason=problem, accept_reason=admission,
                can_decline=data['status'] == 'waiting' and not problem,
                can_accept=data['status'] == 'waiting' and not admission)


def visiting_cat_view(session):
    from .core.cafe_visiting_cat import progress, response_reason, daily_reason, admission_reason
    from .core.cafe_housing import status as housing_status
    from .core.cafe_preferences import feature_text
    from .core.cafe_traits import description
    from .core.human_cat_types import Personality
    core = session.core
    data = core.visiting_cat
    if not data:
        return None
    rule = data['rules']
    row = rule['candidate']
    problem = ''
    try:
        session._ready()
    except ValueError as ex:
        problem = str(ex)
    problem = problem or response_reason(core)
    daily = problem or daily_reason(core)
    admission = problem or admission_reason(core)
    personality = Personality.from_dict(row['personality'])
    return dict(cat_id=rule['cat_id'], content_cat_id=CONTENT_IDS.get(rule['cat_id'], rule['cat_id']),
                name=row['name'], status=data['status'], progress=progress(core), required=rule['interactions_required'],
                presented_day=data['presented_day'] or 0, accepted_day=data['accepted_day'] or 0,
                cost=row['cost'], funds_after=core.funds-row['cost'], housing=housing_status(core),
                personality=next((name for name, value in session.presets.items() if value == personality), 'カスタム'),
                features=feature_text(row.get('features', [])),
                trait='\n'.join(f'{label}：{value}' for label, value in description(row.get('trait'))),
                history='\n'.join(f"{action['day']}日目：" + ('交流した' if action['choice'] == 'interact' else '今日は見送った') for action in data['actions']),
                reason=problem, daily_reason=daily, accept_reason=admission,
                can_interact=data['status'] == 'visiting' and not daily,
                can_skip=data['status'] in ('visiting', 'ready') and not daily,
                can_accept=data['status'] == 'ready' and not admission)


def housing_view(session):
    from .core.cafe_housing import count, capacity, daily_cost, reason, upgrade_rules, upgrade_reason
    from .core.cafe_operating_cost import estimate
    core = session.core
    data = core.housing
    stage = 2 if data and data.get('upgrade') else 1 if data and data['purchase'] else 0
    selected = upgrade_rules() if stage == 1 else data['rules'] if data else None
    kind = 'upgrade_housing' if stage == 1 else 'purchase_housing' if data and stage == 0 else ''
    problem = ''
    try:
        session._ready(for_housing=True)
    except ValueError as ex:
        problem = str(ex)
    problem = problem or (upgrade_reason(core, upgrade_rules()) if stage else reason(core))
    limit = capacity(core)
    current_daily = daily_cost(core)
    operating = estimate(core)
    return dict(configured=data is not None, count=count(core), capacity=limit or 0,
                free=max(0, limit-count(core)) if limit is not None else 0, stage=stage, kind=kind,
                next_capacity=limit+selected['capacity_bonus'] if kind else limit or 0,
                cost=selected['cost'] if kind else 0, funds_after=core.funds-(selected['cost'] if kind else 0),
                daily_cost=current_daily, next_daily_cost=selected['daily_cost'] if kind else current_daily,
                operating_cost=operating, next_operating_cost=operating-current_daily+selected['daily_cost'] if kind else operating,
                can_expand=bool(kind) and not problem, reason=problem)


def objective_progress_view(session, mode=None):
    from .core.cafe_objective import MODES
    from .core.cafe_goal import current_rules, current_start
    from .core.cafe_bond_goal import qualifying
    from .core.cafe_player import state as player_state
    core = session.core
    mode = mode or core.objective or ('popularity' if core.goal and not core.goal.get('tracking_only') else 'free')
    label = MODES[mode]
    data = {'popularity': core.goal, 'patron': core.patron, 'bond': core.bond_goal}.get(mode)
    status = data['status'] if data else 'active'
    suffix = '（達成・継続中）' if data and data['continued'] and status == 'cleared' else '（結果確認待ち）' if data and status != 'active' and not data['continued'] else ''
    if mode == 'popularity' and data:
        selected = current_rules(data)
        deadline = current_start(data) + selected['days'] - 1
        remaining = max(0, deadline - core.day + (0 if core.closed else 1))
        summary = f"第{len(data.get('history', []))+1}段階　人気 {core.management['popularity']:g} / {selected['target']:g}　残り{remaining}日"
        details = f"{summary}\n期限：{deadline}日目の閉店まで"
        if status == 'expired':
            details += '\n期限内未達・継続営業' if data['continued'] else '\n期限内未達'
    elif mode == 'patron' and data:
        rows = [f"{data['rules']['name']}：{data['satisfaction']:g} / {data['rules']['target']:g}"]
        rows += [f"{r['name']}：{data['members'][r['id']]:g} / {r['target']:g}" for r in data['rules'].get('members', [])]
        summary = '　'.join(row.split('：')[1] for row in rows)
        details = '全員の満足度を目標まで高めます。\n' + '\n'.join(rows)
    elif mode == 'bond' and data:
        selected = data['rules']
        summary = f"好感度{selected['affinity']:g}以上の在籍猫　{len(qualifying(core))} / {selected['target']}匹"
        affinity = player_state(core)['affinity']
        details = summary + '\n' + '\n'.join(f"{row['name']}：{affinity[row['cat_id']]:g} / {selected['affinity']:g}" for row in session.cat_choices() if core.activity(row['cat_id']) != 'adopted')
    else:
        summary = '期限なし・自由に営業'
        details = '自由営業にはクリア条件や期限はありません。'
    return dict(mode=mode, label=label, status=status, summary=summary+suffix, details=details+suffix)


def adoption_view(session):
    from .cafe_customers import customer_name
    core = session.core
    enabled = bool(core.adoption and core.adoption['enabled'])
    problem = ''
    try:
        copy.deepcopy(session).configure_adoption(not enabled)
    except ValueError as ex:
        problem = str(ex)
    events = []
    for event in (core.adoption or {}).get('events', {}).values():
        reasons = {}
        for choice in ('accept', 'decline'):
            reason = ''
            if event['status'] == 'waiting':
                try:
                    copy.deepcopy(session).resolve_adoption(event['id'], choice)
                except ValueError as ex:
                    reason = str(ex)
            reasons[choice] = reason
        events.append(dict(event_id=event['id'], cat_id=event['cat_id'],
                           name=session.profiles.get(event['cat_id'], {}).get('name', event['cat_id']),
                           customer_id=event['customer_id'], customer_name=customer_name(event['customer_id']),
                           day=event['day'], status=event['status'], choice=event['choice'] or '',
                           guest_affinity=event['guest_affinity'], player_affinity=event['player_affinity'], threshold=event['threshold'],
                           can_accept=event['status']=='waiting' and not reasons['accept'],
                           can_decline=event['status']=='waiting' and not reasons['decline'],
                           accept_reason=reasons['accept'], decline_reason=reasons['decline']))
    return dict(enabled=enabled, can_configure=not problem, reason=problem, events=events)


def expansion_view(session):
    from .core.cafe_expansion import rules, next_step, reason, purchases
    from .core.cafe_operating_cost import estimate
    core = session.core
    selected = rules()
    step = next_step(core,selected)
    count = len(core.seats) if hasattr(core,'seats') else 1
    problem = ''
    try:
        session._ready()
    except ValueError as ex:
        problem = str(ex)
    problem = problem or reason(core,selected)
    next_count = step['to_seats'] if step else count
    cost = step['cost'] if step else 0
    lines = [f'現在の席数：{count}席 / 上限：8席']
    if step:
        lines.extend([f'次の増設：{count} → {next_count}席',f'増設費用：{cost:g}',
                      f'資金：{core.funds:g} → {core.funds-cost:g}',
                      f'日次運営費：{estimate(core):g} → {estimate(core,next_count):g}'])
    else:
        lines.append('現在追加できる席はありません。')
    lines.extend(['\n増設条件', '営業準備中・必要な確認への回答済み・増設後に資金が残ること。',
                  '3席：初回の増設 / 4～5席：人気目標の第1段階達成後',
                  '6～8席：人気目標の第2段階達成後',
                  '\n新しい席は購入直後から使えます。飼育できる猫の上限は変わりません。',
                  '増設当日から、休業日も日次運営費を精算します。',
                  '4席以降の増設に対応する追加の来店客は、購入翌日から来店します。', '\n増設履歴'])
    history = purchases(core)
    lines.extend([f"{row['day']}日目：{row['seats']}席へ増設 / 費用 {row['cost']:g}" for row in history] or ['増設の記録はありません。'])
    return dict(seats=count,max_seats=8,next_seats=next_count,has_next=step is not None,cost=cost,
                funds_after=core.funds-cost,operating_cost=estimate(core),next_operating_cost=estimate(core,next_count),
                can_expand=not problem,reason=problem,details='\n'.join(lines))


def day_off_view(session):
    from .cafe_health_text import health_text
    from .core.cafe_activities import ACTIVITY_LABELS
    core = session.core
    result = dict(can_select=False, reason='', cost=0, funds_after=core.funds,
                  day_after=core.day, ends_game=False, details='')
    try:
        candidate = copy.deepcopy(session)
        candidate.day_off()
    except ValueError as ex:
        result['reason'] = str(ex)
        return result
    after = candidate.core
    ended = (after.management or {}).get('game_over')
    lines = ['来客・接客はありません。日次運営費は発生します。',
             f'日程：{core.day}日目 → {after.day}日目',
             f'資金：{core.funds:g} → {after.funds:g} / 今回の支出：{core.funds-after.funds:g}']
    if ended:
        lines.append('休業の精算で営業が終了します。翌日には進みません。')
    else:
        lines.append('休業後は翌日の準備へ進みます。目標の期限・派遣・療養の日程も進み、確認待ちが発生する場合があります。')
    from .core.cafe_store_events import waiting
    event = waiting(core)
    if event and event['type']=='trouble':
        lines.append('店舗トラブルには休業で対応します。')
    for cat_id, cat in core.cats.items():
        next_cat = after.cats[cat_id]
        lines.append(f"\n{session.profiles[cat_id]['name']} / {ACTIVITY_LABELS[core.activity(cat_id)]} → {ACTIVITY_LABELS[after.activity(cat_id)]}"
                     +f'\n体力 {cat.stamina:g} → {next_cat.stamina:g} / 疲労 {cat.fatigue:g} → {next_cat.fatigue:g}'
                     +(f" / ストレス {core.management['stress'][cat_id]:g} → {after.management['stress'][cat_id]:g}" if core.management else '')
                     +f'\n健康：{health_text(cat.health_status,cat.recovery_days_remaining)} → {health_text(next_cat.health_status,next_cat.recovery_days_remaining)}')
    result.update(can_select=True, cost=core.funds-after.funds, funds_after=after.funds,
                  day_after=after.day, ends_game=bool(ended), details='\n'.join(lines))
    return result


def missing_rest_view(session):
    core = session.core
    if not any(e['status'] == 'missing' for e in (core.management or {}).get('events', {}).values()):
        return None
    reason = ''
    after = core.funds
    try:
        session._ready()
        candidate = copy.deepcopy(session)
        candidate.day_off()
        after = candidate.core.funds
    except ValueError as ex:
        reason = str(ex)
    return dict(can_rest=not reason, reason=reason, cost=core.funds-after, funds_after=after)


def missing_cats_view(session):
    core = session.core
    data = core.management
    rows = []
    for event in (data or {}).get('events', {}).values():
        reason = ''
        waiting = event['status'] == 'waiting'
        if waiting:
            try:
                copy.deepcopy(session).resolve_missing(event['id'])
            except ValueError as ex:
                reason = str(ex)
        revealed = event['status'] != 'missing'
        cost = event['cost'] if event['status'] == 'resolved' else data['rules']['kitten_cost'] if revealed and event['kitten'] else 0
        rows.append(dict(choice=event['id'], cat_id=event['cat_id'],
                         name=session.profiles.get(event['cat_id'], {}).get('name', event['cat_id']),
                         status=event['status'], departed_day=event['departed_day'], remaining=event['remaining'],
                         resolved_day=event['resolved_day'] or 0, kitten=revealed and event['kitten'], cost=cost,
                         funds_after=core.funds-cost if waiting else core.funds,
                         return_stress=data['rules']['return_stress'], max_stamina=core.config.max_stamina,
                         can_resolve=waiting and not reason, reason=reason))
    return rows


def patron_dispatch_view(session):
    from .core.cafe_patron import destinations
    from .core.cafe_activities import dispatch_reason, reward
    from .core.cafe_traits import dispatch_terms
    from .core.cafe_dispatch_match import terms as welcome_terms, description as welcome_description
    from .core.cafe_patron_members import terms as member_terms, description as member_description
    core = session.core
    rules = destinations(core)
    problem = ''
    try:
        session._ready()
    except ValueError as ex:
        problem = str(ex)
    options = []
    for cat_id in core.cats:
        for row in rules:
            reason = problem or dispatch_reason(core, cat_id, row)
            benefits = dispatch_terms(core, cat_id, row['reward'])
            welcome = welcome_terms(core, cat_id, row) or {}
            member = member_terms(core, cat_id, row['id'])
            gain = member['gain'] if member else core.patron['rules']['gain'] + welcome.get('satisfaction_bonus', 0)
            options.append(dict(cat_id=cat_id, choice=row['id'], label=row['name'], days=row['days'],
                                reward=benefits['reward']+welcome.get('reward_bonus', 0), satisfaction=gain,
                                detail=f"健康・体力あり・疲労{row['max_fatigue']:g}以下 / 店内に席数分の猫を残します。\n"
                                       + (member_description(core, cat_id, row['id']) if member else welcome_description(core, cat_id, row))
                                       + f"\n帰還時のストレス ＋{benefits['stress']:g}", reason=reason, can_select=not reason))
    events = []
    ids = {row['id'] for row in rules}
    for event in (core.activities or {}).get('events', {}).values():
        if event['destination']['id'] not in ids:
            continue
        reason = ''
        waiting = event['status'] == 'waiting'
        if waiting:
            try:
                copy.deepcopy(session).resolve_activity(event['id'])
            except ValueError as ex:
                reason = str(ex)
        gain = event['patron_match']['gain'] if 'patron_match' in event else core.patron['rules']['gain'] + event.get('welcome_match', {}).get('satisfaction_bonus', 0)
        events.append(dict(choice=event['id'], cat_id=event['cat_id'], label=session.profiles[event['cat_id']]['name']+' / '+event['destination']['name'],
                           status=event['status'], remaining=event['remaining'], reward=reward(core,event), satisfaction=gain,
                           reason=reason, can_select=waiting and not reason))
    return dict(options=options, events=events)


def dispatch_troubles_view(session):
    from .core.cafe_activities import reward, ACTIVITY_LABELS
    result = []
    core = session.core
    for event in (core.activities or {}).get('events',{}).values():
        data = event.get('trouble')
        if data is None:
            continue
        rules = data['rules']
        choices = []
        for choice, label in (('search','捜索して連れ戻す'),('wait','帰還を待つ（費用なし）')):
            cost = rules['search_cost'] if choice == 'search' else 0
            reason = '' if data['status'] == 'waiting' else '回答済みです。' if data['status'] == 'resolved' else 'トラブルは発生していません。'
            funds_after = core.funds-cost
            remaining = 0 if choice == 'search' else event['remaining']
            if not reason:
                try:
                    candidate = copy.deepcopy(session)
                    candidate.resolve_dispatch_trouble(event['id'],choice)
                    funds_after = candidate.core.funds
                    remaining = candidate.core.activities['events'][event['id']]['remaining']
                except ValueError as ex:
                    reason = str(ex)
            description = ('捜索後、すぐに帰還確認へ進めます。' if choice == 'search' else
                           f"費用なしで待ちます。家出した日から{rules['missing_days']}日後の閉店で帰還確認へ進めます。")
            description += '\n猫が店へ戻るには、派遣・帰還画面で帰還を確認してください。'
            choices.append(dict(choice=choice,label=label,cost=cost,funds_after=funds_after,remaining=remaining,
                                description=description,reason=reason,can_select=not reason))
        cat = core.cats[event['cat_id']]
        description = f"出発時のトラブル発生確率：{data['probability']*100:g}% / 出発時のストレス：{data['stress']:g}"
        if data['missing_day'] is not None:
            description += f"\n\n{data['missing_day']}日目、派遣中に猫が驚いて宿の周囲へ出ていきました。派遣は中断し、報酬は0です。"
            description += f"\n捜索費：{rules['search_cost']:g} / 支払い後に資金が残る必要があります。"
            description += f"\n費用なしで待つ場合：家出した日から{rules['missing_days']}日後に帰還確認。帰還まで接客・交流・別の派遣には参加できません。"
            description += f"\n帰還を確認するとストレスは{rules['return_stress']:g}になります。人気低下や子猫の引き渡し費用はありません。"
        else:
            description += '\n\n' + ('派遣1日目の閉店で発生を判定します。' if data['status']=='scheduled' else 'トラブルは発生しませんでした。通常の派遣・帰還として進められます。')
        description += f"\n\n現在の猫：{ACTIVITY_LABELS[core.activity(event['cat_id'])]} / 疲労 {cat.fatigue:g} / ストレス {core.management['stress'][event['cat_id']]:g}"
        description += '\n' + ('帰還・報酬の確認済みです。' if event['status']=='resolved' else '帰還確認待ちです。' if event['status']=='waiting' else f"帰還まで、あと{event['remaining']}回の閉店です。")
        description += f"\n現在の帰還報酬：{reward(core,event):g} / 現在の資金：{core.funds:g}"
        result.append(dict(event_id=event['id'],cat_id=event['cat_id'],label=session.profiles[event['cat_id']]['name']+' / '+event['destination']['name'],
                           status=data['status'],activity_status=event['status'],description=description,missing_day=data['missing_day'],
                           choice_day=data['choice_day'],choice=data['choice'],cost=data['cost'],return_reward=reward(core,event),choices=choices))
    return result


def dispatch_choices_view(session):
    from .core.cafe_activities import reward
    result = []
    for event in (session.core.activities or {}).get('events', {}).values():
        data = event.get('encounter')
        if not data:
            continue
        choices = []
        for row in data['rules']['choices']:
            reason = 'まだ発生していません。' if data['status'] == 'scheduled' else '回答済みです。' if data['status'] == 'resolved' else ''
            preview = None
            return_reward = reward(session.core,event)
            if not reason:
                try:
                    candidate = copy.deepcopy(session)
                    candidate.resolve_dispatch_choice(event['id'],row['id'])
                    updated = candidate.core.activities['events'][event['id']]
                    preview = updated['encounter']['changes']
                    return_reward = reward(candidate.core,updated)
                except ValueError as ex:
                    reason = str(ex)
            choices.append(dict(choice=row['id'],label=row['label'],reward_delta=row['reward'],fatigue=row['fatigue'],stress=row['stress'],
                                reason=reason,can_select=not reason,return_reward=return_reward,changes=preview))
        selected = next((r['label'] for r in data['rules']['choices'] if r['id'] == data['choice']), '')
        result.append(dict(event_id=event['id'],cat_id=event['cat_id'],label=session.profiles[event['cat_id']]['name']+' / '+event['destination']['name'],
                           title=data['rules']['title'],status=data['status'],occurred_day=data['occurred_day'],resolved_day=data['resolved_day'],
                           selected_label=selected,choices=choices,changes=data['changes'],return_reward=reward(session.core,event),
                           has_stress=session.core.management is not None))
    return result


def general_return_reason(session, event):
    from .core.cafe_dispatch_encounters import pending as encounter_pending
    from .core.cafe_dispatch_trouble import pending as trouble_pending
    if encounter_pending(event):
        return '「派遣中の選択イベント」から回答してください。'
    if trouble_pending(event):
        return '「山あいの宿のトラブル」から対応を選んでください。'
    if event['status'] != 'waiting':
        return 'まだ帰還していません。' if event['status'] != 'resolved' else '受け取り済みです。'
    try:
        copy.deepcopy(session).resolve_activity(event['id'])
    except ValueError as ex:
        return str(ex)
    return ''


def general_dispatch_view(session):
    from .core.cafe_activities import destinations, dispatch_reason, reward
    from .core.cafe_traits import dispatch_terms
    from .core.cafe_dispatch_match import description, terms
    from .core.cafe_items import for_destination, rewards
    from .core.cafe_dispatch_encounters import pending as encounter_pending
    from .core.cafe_dispatch_trouble import pending as trouble_pending
    core = session.core
    problem = ''
    try:
        session._ready()
    except ValueError as ex:
        problem = str(ex)
    options = []
    for cat_id in core.cats:
        for row in destinations(core):
            reason = problem or dispatch_reason(core, cat_id, row)
            benefits = dispatch_terms(core, cat_id, row['reward'])
            welcome = terms(core, cat_id, row) or {}
            item = for_destination(row)
            detail = f"健康・体力あり・疲労{row['max_fatigue']:g}以下 / 店内に席数分の猫を残します。\n"
            detail += description(core, cat_id, row) + f"\n帰還時のストレス ＋{benefits['stress']:g}"
            if row.get('required_trait_name'):
                detail += ' / 必要特性：' + row['required_trait_name']
            if item:
                detail += '\n用品報酬：' + item['name']

            options.append(dict(cat_id=cat_id, choice=row['id'], label=session.profiles[cat_id]['name']+' / '+row['name'],
                                days=row['days'], reward=benefits['reward']+welcome.get('reward_bonus',0),
                                detail=detail, reason=reason, can_select=not reason))
    events = []
    ids = {r['id'] for r in destinations(core)}
    owned = rewards(core)
    for event in (core.activities or {}).get('events',{}).values():
        if event['destination']['id'] not in ids:
            continue
        item = event.get('item_reward')
        detail = ('用品報酬：'+item['name']+('（受取済み）' if event['id'] in owned else '（未受取）')) if item else '用品報酬なし'
        if event.get('encounter'):
            detail += '\n派遣イベント：'+event['encounter']['rules']['title']+' / '+{'scheduled':'発生前','waiting':'回答待ち','resolved':'回答済み'}[event['encounter']['status']]
        reason = general_return_reason(session,event)
        events.append(dict(choice=event['id'],cat_id=event['cat_id'],label=session.profiles[event['cat_id']]['name']+' / '+event['destination']['name'],
                           status=event['status'],remaining=event['remaining'],reward=reward(core,event),detail=detail,
                           needs_response=event['status'] in ('waiting','missing') or encounter_pending(event) or trouble_pending(event),
                           reason=reason,can_select=not reason))
    return dict(options=options,events=events)


def player_interaction_view(session):
    from .core.cafe_player import current, remaining
    from .core.human_cat_relationship import verify_relationship
    from .human_cat_gui import ACTION_NAMES, REACTION_NAMES, END_NAMES
    interaction = current(session.core)
    active = interaction is not None
    log = (session.core.player_bond or {}).get('last')
    if not active:
        interaction = verify_relationship(log) if log else None
    if interaction is None:
        return None
    problem = ''
    if active:
        try:
            copy.deepcopy(session).player_command(finish=True)
        except ValueError as ex:
            problem = str(ex)
    summary = interaction.summary()
    valid = interaction.valid_actions() if active and not problem else ()
    targets = [dict(choice=key, label=row.name) for key, row in interaction.type_map.items() if key != interaction.state['mode']]
    last = interaction.records[-1] if interaction.records else {}
    event_image_key = ('simultaneous' if last.get('open_up_source') and last.get('connect_source')
                       else 'open_up' if last.get('open_up_source') else '')
    if event_image_key:
        event_image_key = interaction.state['mode'] + '__' + event_image_key
    history = []
    for row in interaction.records:
        action = ACTION_NAMES[row['action']]
        if row['target_type']:
            action += ' → ' + interaction.type_map[row['target_type']].name
        after = row['after']
        delta = sum(row['affinity_breakdown'].values())
        history.append(f"{row['tick']+1}：{action} / {REACTION_NAMES[row['reaction']]}\n体力 {after['stamina']:g} / 好感度 {delta:+g}")
    return dict(session_id=interaction.session_id, cat_id=interaction.cat_id,
                name=session.profiles.get(interaction.cat_id, {}).get('name', interaction.cat_id),
                active=active, remaining_ticks=interaction.state['remaining_ticks'], remaining_sets=remaining(session.core),
                mode=interaction.type_map[interaction.state['mode']].name,
                scene_key=('pause' if interaction.records and interaction.records[-1]['action'] == 'pause'
                           else interaction.state['mode']),
                image_key=(interaction.state['mode'] + '__' + interaction.records[-1]['action']
                           if interaction.records else interaction.state['mode']),
                event_image_key=event_image_key,
                content_cat_id=CONTENT_IDS.get(interaction.cat_id, interaction.cat_id),
                affinity_before=summary['affinity_before'], affinity_after=summary['affinity_after'],
                affinity_delta=summary['affinity_delta'], stamina_before=interaction.initial_stamina, stamina=summary['stamina'],
                engagement=summary['engagement'], tension=summary['tension'], history='\n\n'.join(history),
                can_finish=active and not problem, reason=problem if active else END_NAMES[interaction.state['end_reason']],
                actions=[dict(choice=key, label=label, can_select=key in valid) for key, label in ACTION_NAMES.items()],
                targets=targets)


def next_goal_view(session):
    from .core.cafe_goal import next_rules
    core = session.core
    data = core.goal
    if not data or data['status'] != 'cleared' or next_rules(data) is None:
        return None
    selected = next_rules(data)
    problem = ''
    try:
        copy.deepcopy(session).advance_goal()
    except ValueError as ex:
        problem = str(ex)
    start = core.day + int(core.closed)
    return dict(stage=len(data.get('history', []))+2, target=selected['target'], days=selected['days'],
                started_day=start, deadline=start+selected['days']-1, can_advance=not problem, reason=problem)


def goal_result_view(session):
    from .core.cafe_goal import pending, current_rules, current_start
    from .core.cafe_patron import pending as patron_pending
    from .core.cafe_bond_goal import pending as bond_pending
    core = session.core
    kind = next((kind for kind, waiting in (('continue_patron', patron_pending), ('continue_bond_goal', bond_pending), ('continue_goal', pending)) if waiting(core)), None)
    if not kind:
        return None
    problem = ''
    try:
        getattr(copy.deepcopy(session), kind)()
    except ValueError as ex:
        problem = str(ex)
    mode = {'continue_patron': 'patron', 'continue_bond_goal': 'bond', 'continue_goal': 'popularity'}[kind]
    data = {'popularity': core.goal, 'patron': core.patron, 'bond': core.bond_goal}[mode]
    progress = objective_progress_view(session, mode)
    title = '人気目標を達成しました' if mode == 'popularity' else '有力者の満足度目標を達成しました' if mode == 'patron' else '好感度目標を達成しました'
    if data['status'] == 'expired':
        title = '人気目標の期限を迎えました'
    details = progress['details'] if progress['mode'] == mode else ''
    details += f"\n結果：{'達成' if data['status'] == 'cleared' else '期限内未達'}\n結果確定：{data['resolved_day']}日目"
    captured = (core.clear_results or {}).get(mode)
    if captured:
        details += f"\n\nクリア時の成果\n所持金：{captured['funds']:g}　人気：{captured['popularity']:g}\n在籍猫：{captured['cats']}匹　累計売上：{captured['revenue']:g}"
    else:
        details += f"\n所持金：{core.funds:g}"
    details += '\n\n「継続営業」で結果を確認し、猫や資金を引き継いで遊べます。'
    result = dict(kind=kind, title=title, details=details, status=data['status'], resolved_day=data['resolved_day'], funds=core.funds, can_continue=not problem, reason=problem)
    if mode == 'popularity':
        selected = current_rules(data)
        result.update(stage=len(data.get('history', []))+1, started_day=current_start(data), deadline=current_start(data)+selected['days']-1, target=selected['target'], popularity=core.management['popularity'])
    return result



def store_event_view(session):
    from .core.cafe_store_events import waiting, LABELS
    event = waiting(session.core)
    if not event:
        return None
    rules = session.core.store_events['rules']
    trouble = event['type'] == 'trouble'
    rows = [('repair', '修理する'), ('patch', '応急処置する'), ('close', '休業して翌日へ')] if trouble else [
        ('full', '支援する'), ('small', '少額支援する'), ('decline', '見送る')]
    choices = []
    for choice, label in rows:
        reason = ''
        try:
            candidate = copy.deepcopy(session)
            if choice == 'close':
                candidate.day_off()
            else:
                candidate.resolve_store_event(choice)
        except ValueError as ex:
            reason = str(ex)
        if trouble:
            detail = (f"閉店時の運営費に {rules['trouble_cost']:g} を追加し、全席で営業します。" if choice == 'repair' else
                      f"追加費用なし。今日は {min(rules['trouble_seat_loss'],len(session.core.seats))} 席を使用停止します。" if choice == 'patch' else
                      '来客なしで猫を休ませ、翌日へ進みます。日次運営費は発生します。')
        elif choice == 'decline':
            detail = '資金と人気は変化しません。'
        else:
            prefix = 'support_' + choice
            detail = f"資金 {rules[prefix+'_cost']:g} を使い、閉店時に人気＋{rules[prefix+'_popularity']:g}。"
        choices.append(dict(choice=choice, label=label, detail=detail, can_select=not reason, reason=reason))
    return dict(kind=event['type'], title=LABELS[event['type']], day=session.core.day,
                funds=session.core.funds, choices=choices)


def growth_view(session):
    from .core.cafe_growth import pending, SPECIALIZATIONS, LABELS, total
    core = session.core
    result = []
    for cat_id in pending(core):
        row = core.growth['cats'][cat_id]
        rules = core.growth['rules']
        details = {
            'service': f"接客終了時、消費した体力の{rules['service_stamina_refund']*100:g}%を回復します。",
            'rest': f"在店休養時の疲労回復＋{rules['rest_recovery_bonus']:g}。",
            'dispatch': f"派遣報酬を{rules['dispatch_reward_multiplier']:g}倍にします。"}
        choices = []
        for choice in SPECIALIZATIONS:
            reason = ''
            try:
                copy.deepcopy(session).resolve_growth(cat_id, choice)
            except ValueError as ex:
                reason = str(ex)
            choices.append(dict(choice=choice, label=LABELS[choice]+'を得意にする',
                                detail=details[choice], can_select=not reason, reason=reason))
        result.append(dict(cat_id=cat_id, name=session.profiles.get(cat_id, {}).get('name', cat_id),
                           kind='resolve_growth', title='得意分野', experience=total(row), threshold=rules['threshold'], service=row['service'],
                           rest=row['rest'], dispatch=row['dispatch'], choices=choices))
    from .core.cafe_growth import mastery_pending, mastery_choices, MASTERY_GROUPS, GROUP_LABELS, learned_groups
    for cat_id in mastery_pending(core):
        row = core.growth['cats'][cat_id]
        rules = core.growth['rules']
        stage = 3 if row.get('second_mastery') else 2 if row['mastery'] else 1
        counts = (row['third_group_practice']['groups'] if stage == 3 else
                  row['second_mastery_groups'] if stage == 2 else row['mastery_groups'])
        eligible = mastery_choices(core, cat_id)
        choices = []
        for choice in MASTERY_GROUPS:
            reason = ''
            try:
                copy.deepcopy(session).resolve_growth_mastery(cat_id, choice)
            except ValueError as ex:
                reason = str(ex)
            if choice not in eligible:
                reason = '習得済みです。' if choice in learned_groups(row) else 'この分類の接客実績が不足しています。'
            choices.append(dict(choice=choice, label=GROUP_LABELS[choice],
                                detail=f"この分類の通常行動による関心増加×{rules['mastery_engagement_multiplier']:g}。",
                                can_select=not reason, reason=reason))
        result.append(dict(cat_id=cat_id, name=session.profiles.get(cat_id, {}).get('name', cat_id),
                           kind='resolve_growth_mastery', title=('得意な交流' if stage == 1 else f'{stage}つ目の得意な交流'),
                           experience=sum(counts.values()), threshold=rules['mastery_threshold'] if stage == 1 else rules['second_mastery_threshold'],
                           play=counts['play'], contact=counts['contact'], quiet=counts['quiet'],
                           learned='・'.join(GROUP_LABELS[group] for group in learned_groups(row)), choices=choices))
    from .core.cafe_growth import type_mastery_pending, type_mastery_stage, TYPE_GROUPS, type_label, learned_types
    for cat_id in type_mastery_pending(core):
        row = core.growth['cats'][cat_id]
        rules = core.growth['rules']
        stage = type_mastery_stage(core, cat_id)
        extra = stage in ('second', 'second_group_second', 'third_group_second')
        if stage.startswith('third_group'):
            practice = row['third_group_practice']['individual']
            group = row['third_group_practice']['mastery']
            if extra: practice = practice['second']
            counts = practice['actions']
            title = '3つ目の分類の' + ('追加の' if extra else '') + '得意な行動'
        elif stage.startswith('second_group'):
            practice = row['second_group_type_practice']
            group = row['second_mastery']
            if extra: practice = practice['second']
            counts = practice['actions']
            title = '2つ目の分類の' + ('追加の' if extra else '') + '得意な行動'
        else:
            counts = row['second_type_mastery_actions'] if extra else row['type_mastery_actions']
            group = row['mastery']
            title = '2つ目の得意な行動' if extra else '得意な行動'
        choices = []
        for choice, action_group in TYPE_GROUPS.items():
            if action_group != group: continue
            reason = ''
            try:
                copy.deepcopy(session).resolve_growth_type_mastery(cat_id, choice)
            except ValueError as ex:
                reason = str(ex)
            if choice in learned_types(row): reason = '習得済みです。'
            elif counts[choice] <= 0: reason = 'この行動の接客実績がありません。'
            choices.append(dict(choice=choice, label=type_label(choice),
                                detail=f"成功接客の実績：{counts[choice]:g}回", can_select=not reason, reason=reason))
        result.append(dict(cat_id=cat_id, name=session.profiles.get(cat_id, {}).get('name', cat_id),
                           kind='resolve_growth_type_mastery', title=title, group=GROUP_LABELS[group],
                           experience=sum(counts.values()), threshold=rules['second_type_mastery_threshold' if extra else 'type_mastery_threshold'],
                           effect=f"選んだ行動の通常の関心増加を、分類の効果に追加で{rules['type_mastery_engagement_multiplier']:g}倍にします。",
                           learned='・'.join(type_label(key) for key in learned_types(row)), choices=choices))
    return result


def new_game_options():
    from .cafe_new_game import starting_conditions
    from .core.cafe_objective import MODES
    result=[]
    for mode,label in MODES.items():
        settings=starting_conditions(mode)
        if mode=='popularity':
            goal=settings['goal']; stages=[goal]+goal.get('stages',[])
            detail=' → '.join(f"{row['days']}日以内に人気{row['target']:g}" for row in stages)
        elif mode=='patron': detail=f"有力者の満足度を{settings['patron']['target']:g}まで高めます。"
        elif mode=='bond': detail=f"猫{settings['bond']['target']}匹との好感度をそれぞれ{settings['bond']['affinity']:g}まで高めます。"
        else: detail='期限のある人気目標を設定せず、自由に営業します。'
        result.append(dict(choice=mode,label=label,detail=detail,
                           conditions=f"初期猫：{len(settings['profiles']['cats'])}匹 / 席：{settings['seat_count']}席 / 資金：{settings['management']['starting_funds']:g}"))
    return result


def state_view(session, instance_id='', revision=0):
    core = session.core
    cats = []
    from .core.cafe_growth import description as growth_description
    from .cafe_health_text import health_text
    from .core.cafe_activities import ACTIVITY_LABELS
    from .core.cafe_player import state as player_state, remaining, unavailable_reason
    bond = player_state(core)
    begin_problem = ''
    try:
        session._ready()
    except ValueError as ex:
        begin_problem = str(ex)
    for row in session.cat_choices():
        cat_id = row['cat_id']
        player_reason = begin_problem or unavailable_reason(core, cat_id)
        cats.append(dict(cat_id=cat_id, content_cat_id=CONTENT_IDS.get(cat_id, cat_id),
                         name=row['name'], stamina=row['stamina'],
                         max_stamina=core.config.max_stamina, working=row['working'],
                         fatigue=row['fatigue'], stress=row['stress'] or 0,
                         health_status=row['health_status'], activity=core.activity(cat_id),
                         health_label=health_text(row['health_status'], core.cats[cat_id].recovery_days_remaining),
                         activity_label=ACTIVITY_LABELS[core.activity(cat_id)], growth_details=growth_description(core, cat_id),
                         affinity=bond['affinity'][cat_id], remaining_sets=remaining(core),
                         can_player_start=not player_reason, player_reason=player_reason))
    seats = getattr(core, 'seats', {core.seat.id: core.seat})
    from .cafe_customers import customer_name
    customers = []
    for visit in core.visits.values():
        seat_id = next((key for key, seat in seats.items() if seat.customer_id == visit.id), '')
        customers.append(dict(customer_id=visit.id, name=customer_name(visit.id), seat_id=seat_id,
                              status='seated' if seat_id else 'departed' if visit.departure_reason else 'waiting'))
    summary = core.summary()
    required_action = ''
    try:
        session._ready()
    except ValueError as ex:
        required_action = str(ex)
    from .core.cafe_finance import values
    ended = (core.management or {}).get('game_over')
    game_over = dict(reason=ended['reason'], day=ended['day'], popularity=core.management['popularity']) if ended else None
    return dict(version=1, game_over=game_over, instance_id=instance_id, revision=revision, new_game_options=new_game_options(), objective=core.objective or "", objective_progress=objective_progress_view(session), next_goal=next_goal_view(session),
                can_set_shifts=core.can_set_shifts, day=core.day, tick=core.tick, funds=core.funds, cats=cats,
                closed=core.closed, required_action=required_action, day_off=day_off_view(session), expansion=expansion_view(session), items=items_view(session), intake_request=intake_view(session), customer_trust=customer_trust_view(session), reservation=reservation_view(session), regular_introduction=regular_introduction_view(session), dispatch_introductions=dispatch_introductions_view(session), visiting_cat=visiting_cat_view(session), opening_ticks=core.config.opening_ticks,
                phase='closed' if core.closed else 'preparation' if core.can_set_shifts else 'open',
                seats=[dict(seat_id=key, customer_id=seat.customer_id or '', cat_id=seat.cat_id or '',
                            customer_name=customer_name(seat.customer_id) if seat.customer_id else '') for key, seat in seats.items()],
                customers=customers, housing=housing_view(session), goal_result=goal_result_view(session), store_event=store_event_view(session), growth_choices=growth_view(session), player_interaction=player_interaction_view(session), patron_dispatch=patron_dispatch_view(session), general_dispatch=general_dispatch_view(session), dispatch_choices=dispatch_choices_view(session), dispatch_troubles=dispatch_troubles_view(session), missing_cats=missing_cats_view(session), missing_rest=missing_rest_view(session), adoption=adoption_view(session),
                waiting_count=len(core.queue), completed_interactions=summary['completed_interactions'],
                revenue=summary['revenue'], finance=values(summary) if core.closed else None)


def make_server(session, port=8190, saves_directory=None):
    # Normal automatic service persists relationship receipts. Keep these in memory
    # between snapshot exports; never modify the loaded game's files.
    from .storage.cafe_saves import MemoryRelationships
    session.store = MemoryRelationships(session.store._read())
    instance_id = uuid.uuid4().hex
    revision = 0
    results = {}
    save_root = Path(saves_directory or Path(__file__).resolve().parents[1] / 'saves/unity').resolve()

    def save_path(save_id):
        if not isinstance(save_id, str) or not re.fullmatch(r'[a-f0-9]{32}', save_id):
            raise ValueError('保存データの指定が不正です。')
        path = (save_root / save_id).resolve()
        if path.parent != save_root:
            raise ValueError('保存先の外側は読み込めません。')
        return path

    def saved_games():
        rows = []
        if save_root.exists():
            for folder in save_root.iterdir():
                try:
                    path = save_path(folder.name)
                    if not (path / 'cafe.json').is_file():
                        continue
                    row = json.loads((path / 'info.json').read_text(encoding='utf-8'))
                    if row.get('save_id') == folder.name and isinstance(row.get('created_at'), str) and isinstance(row.get('label'), str):
                        rows.append(row)
                except (OSError, ValueError, AttributeError):
                    continue
        return sorted(rows, key=lambda row: row.get('created_at', ''), reverse=True)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/health':
                data, code = dict(version=1, service='cat-cafe-state', read_only=False), 200
            elif self.path == '/state':
                data, code = state_view(session, instance_id, revision), 200
            elif self.path == '/saves':
                data, code = dict(saves=saved_games()), 200
            else:
                data, code = dict(error='not_found'), 404
            self.reply(data, code)

        def do_POST(self):
            nonlocal revision
            if self.path != '/commands':
                self.reply(dict(error='not_found'), 404)
                return
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('JSON形式で操作を送信してください。')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('操作データのサイズが不正です。')
                command = json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(command, dict) or set(command) - {'save_id', 'choice', 'cat_id', 'target_type', 'event_id'} != {'request_id', 'instance_id', 'expected_revision', 'kind', 'working_cats'}:
                    raise ValueError('操作データの形式が不正です。')
                request_id = command['request_id']
                if command.get('kind') == 'resolve_customer_trust' and (command.get('choice') not in ('recover', 'ignore') or not isinstance(command.get('event_id'), str) or not command['event_id']):
                    raise ValueError('信頼回復のイベントと対応方針を指定してください。')
                if command.get('kind') in ('purchase_item','use_item','sell_item') and (not isinstance(command.get('choice'),str) or not command['choice']):
                    raise ValueError('購入する用品または所持品を指定してください。')
                if command.get('kind') == 'use_item' and (not isinstance(command.get('cat_id'),str) or not command['cat_id']):
                    raise ValueError('用品を使う猫を指定してください。')
                if command.get('kind') == 'resolve_dispatch_introduction' and (command.get('choice') not in ('accept','decline') or not isinstance(command.get('event_id'),str) or not command['event_id']):
                    raise ValueError('派遣先の猫紹介記録と迎える／見送るを指定してください。')
                if command.get('kind') == 'resolve_dispatch_trouble' and (command.get('choice') not in ('search','wait') or not isinstance(command.get('event_id'),str) or not command['event_id']):
                    raise ValueError('宿のトラブル記録と捜索する／帰還を待つを指定してください。')
                if command.get('kind') == 'resolve_dispatch_choice' and (not isinstance(command.get('choice'), str) or not command['choice'] or not isinstance(command.get('event_id'), str) or not command['event_id']):
                    raise ValueError('派遣中イベントの記録と選択肢を指定してください。')
                if command.get('kind') == 'resolve_reservation' and (command.get('choice') not in ('accept', 'decline') or not isinstance(command.get('event_id'), str) or not command['event_id']):
                    raise ValueError('予約の依頼と引き受ける／辞退するを指定してください。')
                if command.get('kind') == 'resolve_regular_introduction' and (command.get('choice') not in ('accept', 'decline') or not isinstance(command.get('cat_id'), str) or not command['cat_id']):
                    raise ValueError('常連紹介の猫と迎える／見送るを指定してください。')
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
                    raise ValueError('操作IDが不正です。')
                if command['kind'] not in ('set_shifts', 'start_business', 'advance_business', 'next_day', 'resolve_intake', 'resolve_customer_trust', 'resolve_reservation', 'resolve_regular_introduction', 'resolve_visiting_cat', 'resolve_store_event', 'resolve_growth', 'resolve_growth_mastery', 'resolve_growth_type_mastery', 'continue_goal', 'continue_patron', 'continue_bond_goal', 'advance_goal', 'purchase_item', 'use_item', 'sell_item', 'resolve_dispatch_introduction', 'resolve_dispatch_trouble', 'resolve_dispatch_choice', 'dispatch_general', 'receive_general', 'dispatch_patron', 'receive_patron', 'resolve_missing', 'rest_for_missing', 'day_off', 'expand_seats', 'configure_adoption', 'resolve_adoption', 'player_begin', 'player_step', 'player_finish', 'purchase_housing', 'upgrade_housing', 'save_game', 'load_game', 'new_game') or type(command['expected_revision']) is not int:
                    raise ValueError('未対応の操作です。')
                if command['kind'] in ('dispatch_general', 'receive_general', 'dispatch_patron', 'receive_patron', 'resolve_missing') and (not isinstance(command.get('choice'), str) or not command['choice'] or not isinstance(command.get('cat_id'), str) or not command['cat_id']):
                    raise ValueError('派遣する猫と派遣先・帰還記録を指定してください。')
                if command['kind'] == 'configure_adoption' and command.get('choice') not in ('on', 'off'):
                    raise ValueError('譲渡イベントのON/OFFを指定してください。')
                if command['kind'] == 'resolve_adoption' and (command.get('choice') not in ('accept', 'decline') or not isinstance(command.get('event_id'), str) or not command['event_id'] or not isinstance(command.get('cat_id'), str) or not command['cat_id']):
                    raise ValueError('譲渡の猫・申し出・選択を指定してください。')
                if command['kind'] == 'new_game' and command.get('choice') not in ('popularity', 'patron', 'bond', 'free'):
                    raise ValueError('新規ゲームの目標を選んでください。')
                if command['kind'] == 'resolve_intake' and command.get('choice') not in ('accept', 'decline'):
                    raise ValueError('迎えるか見送るかを選んでください。')
                if command['kind'] == 'resolve_visiting_cat' and (command.get('choice') not in ('interact', 'skip', 'accept') or not isinstance(command.get('cat_id'), str) or not command['cat_id']):
                    raise ValueError('店先の猫と交流する／今日は見送る／迎えるを選んでください。')
                if command['kind'] == 'resolve_store_event' and command.get('choice') not in ('repair', 'patch', 'close', 'full', 'small', 'decline'):
                    raise ValueError('店舗イベントの選択肢が不正です。')
                if command['kind'] == 'resolve_growth' and (command.get('choice') not in ('service', 'rest', 'dispatch') or not isinstance(command.get('cat_id'), str) or not command['cat_id']):
                    raise ValueError('成長できる猫と得意分野を指定してください。')
                if command['kind'] == 'resolve_growth_mastery' and (command.get('choice') not in ('play', 'contact', 'quiet') or not isinstance(command.get('cat_id'), str) or not command['cat_id']):
                    raise ValueError('熟練できる猫と得意な交流を指定してください。')
                if command['kind'] == 'resolve_growth_type_mastery':
                    from .core.cafe_growth import TYPE_GROUPS
                    if command.get('choice') not in TYPE_GROUPS or not isinstance(command.get('cat_id'), str) or not command['cat_id']:
                        raise ValueError('熟練できる猫と得意な行動を指定してください。')
                if command['kind'] in ('player_begin', 'player_step', 'player_finish'):
                    if not isinstance(command.get('cat_id'), str) or not command['cat_id']:
                        raise ValueError('交流する猫を指定してください。')
                    if not isinstance(command.get('target_type', ''), str):
                        raise ValueError('切り替え先を指定してください。')
                    if command['kind'] == 'player_step':
                        from .human_cat_gui import ACTION_NAMES
                        if command.get('choice') not in ACTION_NAMES:
                            raise ValueError('交流の行動を選んでください。')
                        if command['choice'] != 'switch' and command.get('target_type'):
                            raise ValueError('切り替え以外には種類を指定しないでください。')
                if not isinstance(command['working_cats'], list) or any(not isinstance(key, str) for key in command['working_cats']):
                    raise ValueError('出勤猫の指定が不正です。')
            except (ValueError, UnicodeError) as ex:
                self.reply(dict(error=str(ex)), 400)
                return
            if request_id in results:
                previous, data, code = results[request_id]
                self.reply(data if previous == command else dict(error='操作IDが別の操作で使用済みです。'), code if previous == command else 409)
                return
            if command['instance_id'] != instance_id or command['expected_revision'] != revision:
                self.reply(dict(error='状態が更新されています。再取得してください。'), 409)
                return
            if len(results) >= 10000:
                self.reply(dict(error='操作履歴が上限です。サーバーを再起動してください。'), 503)
                return
            try:
                candidate = copy.deepcopy(session)
                saved_id = ''
                if command['kind'] == 'set_shifts':
                    candidate.set_shifts(command['working_cats'])
                elif command['kind'] in ('save_game', 'load_game', 'new_game'):
                    if command['working_cats']:
                        raise ValueError('保存・再開には出勤猫を指定しないでください。')
                    from .storage.cafe_saves import save_game, load_game
                    from .storage.relationships import RelationshipStore
                    if command['kind'] == 'load_game':
                        candidate = load_game(save_path(command.get('save_id')) / 'cafe.json')[0]
                        candidate.store = MemoryRelationships(candidate.store._read())
                    else:
                        if command['kind'] == 'new_game':
                            from .cafe_new_game import create_game, starting_conditions
                            with tempfile.TemporaryDirectory() as directory:
                                candidate=create_game(directory, starting_conditions(command['choice']))
                                candidate.store=MemoryRelationships(candidate.store._read())
                        saved_id = uuid.uuid4().hex
                        path = save_path(saved_id)
                        path.mkdir(parents=True, exist_ok=False)
                        info = dict(save_id=saved_id, created_at=datetime.now(timezone.utc).isoformat(),
                                    objective_label=objective_progress_view(candidate)['label'],
                                    phase='closed' if candidate.core.closed else 'preparation' if candidate.core.can_set_shifts else 'open',
                                    label=f'{candidate.core.day}日目 / 時刻 {candidate.core.tick} / 資金 {candidate.core.funds:g}'
                                    + (' / 閉店' if candidate.core.closed else ''))
                        RelationshipStore(path / 'info.json')._write(info)
                        data_store = candidate.store._read()
                        candidate.store = RelationshipStore(path / 'relationships.json')
                        candidate.store._write(data_store)
                        save_game(candidate, path / 'cafe.json', auto_assign=True)
                        candidate.store = MemoryRelationships(candidate.store._read())
                elif command['kind'] == 'resolve_store_event':
                    if command['working_cats']:
                        raise ValueError('イベント回答には出勤猫を指定しないでください。')
                    event = store_event_view(candidate)
                    option = next((row for row in event['choices'] if row['choice'] == command['choice']), None) if event else None
                    if option is None:
                        raise ValueError('現在の店舗イベントに対応する選択肢ではありません。')
                    if not option['can_select']:
                        raise ValueError(option['reason'])
                    if command['choice'] == 'close':
                        candidate.day_off()
                    else:
                        candidate.resolve_store_event(command['choice'])
                elif command['kind'] == 'resolve_growth':
                    if command['working_cats']:
                        raise ValueError('成長選択には出勤猫を指定しないでください。')
                    candidate.resolve_growth(command['cat_id'], command['choice'])
                elif command['kind'] == 'resolve_growth_mastery':
                    if command['working_cats']:
                        raise ValueError('交流選択には出勤猫を指定しないでください。')
                    candidate.resolve_growth_mastery(command['cat_id'], command['choice'])
                elif command['kind'] == 'resolve_growth_type_mastery':
                    if command['working_cats']:
                        raise ValueError('行動選択には出勤猫を指定しないでください。')
                    candidate.resolve_growth_type_mastery(command['cat_id'], command['choice'])
                elif command['kind'] in ('configure_adoption', 'resolve_adoption'):
                    if command['working_cats']:
                        raise ValueError('譲渡操作には出勤猫を指定しないでください。')
                    if command['kind'] == 'configure_adoption':
                        candidate.configure_adoption(command['choice'] == 'on')
                    else:
                        event = (candidate.core.adoption or {}).get('events', {}).get(command['event_id'])
                        if event is None or event['cat_id'] != command['cat_id'] or event['status'] != 'waiting':
                            raise ValueError('回答待ちの譲渡申し出を選んでください。')
                        candidate.resolve_adoption(event['id'], command['choice'])
                elif command['kind'] == 'expand_seats':
                    if command['working_cats'] or command.get('cat_id') or command.get('choice') or command.get('event_id'):
                        raise ValueError('席の増設には猫や選択肢を指定しないでください。')
                    candidate.expand_seats()
                elif command['kind'] == 'day_off':
                    if command['working_cats'] or command.get('cat_id') or command.get('choice') or command.get('event_id'):
                        raise ValueError('休業には猫や選択肢を指定しないでください。')
                    candidate.day_off()
                elif command['kind'] == 'rest_for_missing':
                    if command['working_cats']:
                        raise ValueError('休業には出勤猫を指定しないでください。')
                    available = missing_rest_view(candidate)
                    if available is None or not available['can_rest']:
                        raise ValueError(available['reason'] if available else '家出中の猫がいる準備中に選んでください。')
                    candidate.day_off()
                elif command['kind'] == 'resolve_missing':
                    if command['working_cats']:
                        raise ValueError('帰還確認には出勤猫を指定しないでください。')
                    event = (candidate.core.management or {}).get('events', {}).get(command['choice'])
                    if event is None or event['cat_id'] != command['cat_id'] or event['status'] != 'waiting':
                        raise ValueError('家出した猫の帰還待ち記録を選んでください。')
                    candidate.resolve_missing(event['id'])
                elif command['kind'] in ('purchase_item','use_item','sell_item'):
                    if command['working_cats']:
                        raise ValueError('用品操作には出勤猫を指定しないでください。')
                    if command['kind'] == 'purchase_item':
                        from .core.cafe_item_shop import catalog
                        selected = next((r for r in catalog() if r['item']['id']==command['choice']),None)
                        if selected is None:
                            raise ValueError('購入一覧にある用品を選んでください。')
                        candidate.purchase_item(selected)
                    elif command['kind'] == 'use_item':
                        candidate.use_item(command['choice'],command['cat_id'])
                    else:
                        from .core.cafe_items import inventory
                        from .core.cafe_item_sales import prices
                        item = inventory(candidate.core).get(command['choice'])
                        if item is None or item['id'] not in prices():
                            raise ValueError('売却できる所持品を選んでください。')
                        candidate.sell_item(command['choice'])
                elif command['kind'] == 'resolve_dispatch_introduction':
                    if command['working_cats']:
                        raise ValueError('派遣先の猫紹介回答には出勤猫を指定しないでください。')
                    event = (candidate.core.activities or {}).get('events',{}).get(command['event_id'])
                    if event is None or event.get('introduction',{}).get('status') != 'waiting':
                        raise ValueError('回答待ちの派遣先の猫紹介を選んでください。')
                    candidate.resolve_dispatch_introduction(event['id'],command['choice'])
                elif command['kind'] == 'resolve_dispatch_trouble':
                    if command['working_cats']:
                        raise ValueError('宿のトラブル回答には出勤猫を指定しないでください。')
                    event = (candidate.core.activities or {}).get('events',{}).get(command['event_id'])
                    if event is None or event.get('trouble',{}).get('status') != 'waiting':
                        raise ValueError('回答待ちの宿のトラブルを選んでください。')
                    candidate.resolve_dispatch_trouble(event['id'],command['choice'])
                elif command['kind'] == 'resolve_dispatch_choice':
                    if command['working_cats']:
                        raise ValueError('派遣イベントの回答には出勤猫を指定しないでください。')
                    event = (candidate.core.activities or {}).get('events',{}).get(command['event_id'])
                    if event is None or event.get('encounter',{}).get('status') != 'waiting':
                        raise ValueError('回答待ちの派遣イベントを選んでください。')
                    candidate.resolve_dispatch_choice(event['id'],command['choice'])
                elif command['kind'] in ('dispatch_general', 'receive_general'):
                    if command['working_cats']:
                        raise ValueError('派遣操作には出勤猫を指定しないでください。')
                    from .core.cafe_activities import destinations
                    rules = destinations(candidate.core)
                    if command['kind'] == 'dispatch_general':
                        selected = next((row for row in rules if row['id'] == command['choice']), None)
                        if selected is None:
                            raise ValueError('現在の一般派遣先を選んでください。')
                        candidate.dispatch(command['cat_id'], selected)
                    else:
                        event = (candidate.core.activities or {}).get('events',{}).get(command['choice'])
                        if event is None or event['cat_id'] != command['cat_id'] or event['destination']['id'] not in {r['id'] for r in rules}:
                            raise ValueError('一般派遣の帰還記録を選んでください。')
                        reason = general_return_reason(candidate,event)
                        if reason:
                            raise ValueError(reason)
                        candidate.resolve_activity(event['id'])
                elif command['kind'] in ('dispatch_patron', 'receive_patron'):
                    if command['working_cats']:
                        raise ValueError('派遣操作には出勤猫を指定しないでください。')
                    from .core.cafe_patron import destinations
                    rules = destinations(candidate.core)
                    if command['kind'] == 'dispatch_patron':
                        selected = next((row for row in rules if row['id'] == command['choice']), None)
                        if selected is None:
                            raise ValueError('現在の有力者の派遣先を選んでください。')
                        candidate.dispatch(command['cat_id'], selected)
                    else:
                        event = (candidate.core.activities or {}).get('events', {}).get(command['choice'])
                        if event is None or event['cat_id'] != command['cat_id'] or event['destination']['id'] not in {row['id'] for row in rules} or event['status'] != 'waiting':
                            raise ValueError('帰還待ちの有力者訪問を選んでください。')
                        candidate.resolve_activity(event['id'])
                elif command['kind'] in ('player_begin', 'player_step', 'player_finish'):
                    if command['working_cats']:
                        raise ValueError('猫との交流には出勤猫の指定を付けないでください。')
                    if command['kind'] == 'player_begin':
                        candidate.play_with_player(command['cat_id'])
                    else:
                        from .core.cafe_player import current
                        interaction = current(candidate.core)
                        if interaction is None or interaction.cat_id != command['cat_id']:
                            raise ValueError('進行中の交流の猫を指定してください。')
                        candidate.player_command(command.get('choice'), command.get('target_type') or None,
                                                 finish=command['kind']=='player_finish')
                elif command['kind'] in ('continue_goal', 'continue_patron', 'continue_bond_goal', 'advance_goal'):
                    if command['working_cats']:
                        raise ValueError('継続営業には出勤猫の指定を付けないでください。')
                    getattr(candidate, command['kind'])()
                elif command['kind'] in ('purchase_housing', 'upgrade_housing'):
                    if command['working_cats']:
                        raise ValueError('飼育スペースの拡張には出勤猫の指定を付けないでください。')
                    if command['kind'] == 'purchase_housing':
                        candidate.purchase_housing()
                    else:
                        candidate.upgrade_housing()
                elif command['kind'] == 'resolve_customer_trust':
                    event = (candidate.core.customer_trust or {}).get('events', {}).get(command['event_id'])
                    if command['working_cats'] or not event or event['status'] != 'waiting':
                        raise ValueError('回答待ちの信頼回復イベントを選んでください。')
                    candidate.resolve_customer_trust(event['id'], command['choice'])
                elif command['kind'] == 'resolve_reservation':
                    row = (candidate.core.reservation or {}).get('request')
                    if command['working_cats'] or not row or row['id'] != command['event_id'] or row['status'] != 'waiting':
                        raise ValueError('回答待ちの予約を選んでください。')
                    candidate.resolve_reservation(command['choice'])
                elif command['kind'] == 'resolve_regular_introduction':
                    data = candidate.core.regular_introduction
                    if command['working_cats'] or not data or data['rules']['cat_id'] != command['cat_id'] or data['status'] != 'waiting':
                        raise ValueError('回答待ちの常連からの猫紹介を選んでください。')
                    candidate.resolve_regular_introduction(command['choice'])
                elif command['kind'] == 'resolve_visiting_cat':
                    data = candidate.core.visiting_cat
                    if command['working_cats'] or not data or data['rules']['cat_id'] != command['cat_id'] or data['status'] not in ('visiting', 'ready'):
                        raise ValueError('店先に通う猫を選んでください。')
                    candidate.resolve_visiting_cat(command['choice'])
                elif command['kind'] == 'resolve_intake':
                    if command['working_cats']:
                        raise ValueError('受け入れ依頼への回答には出勤猫の指定を付けないでください。')
                    candidate.resolve_intake_request(command['choice'])
                elif command['kind'] == 'next_day':
                    if command['working_cats']:
                        raise ValueError('翌日への操作には出勤猫の指定を付けないでください。')
                    candidate.next_day()
                else:
                    if command['working_cats']:
                        raise ValueError('営業操作には出勤猫の指定を付けないでください。')
                    if candidate.core.closed:
                        raise ValueError('営業は終了しています。閉店結果を確認してください。')
                    if command['kind'] == 'start_business':
                        if not candidate.core.can_set_shifts:
                            raise ValueError('営業はすでに開始しています。')
                        if not candidate.core.working_cats:
                            raise ValueError('出勤する猫を1匹以上選んでください。')
                    elif candidate.core.can_set_shifts:
                        raise ValueError('先に営業を開始してください。')
                    if not candidate.automatic_step(auto_assign=True):
                        raise ValueError('営業を進められません。')
                # Commit only a completely successful operation (including receipts).
                projected = state_view(candidate, instance_id, revision + 1)
                session.__dict__.update(candidate.__dict__)
                revision += 1
                data, code = dict(request_id=request_id, save_id=saved_id, state=projected), 200
            except (ValueError, OSError) as ex:
                data, code = dict(request_id=request_id, error=str(ex)), 422
            results[request_id] = (command, data, code)
            self.reply(data, code)

        def log_message(self, format, *args):
            pass
    return HTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', type=Path, help='Existing cafe.json (loaded once, never overwritten)')
    parser.add_argument('--port', type=int, default=8190)
    parser.add_argument('--saves-directory', type=Path, help='Unity snapshot directory (default: saves/unity)')
    args = parser.parse_args()
    from .cafe_new_game import create_game
    from .storage.cafe_saves import load_game
    with tempfile.TemporaryDirectory(prefix='cat-cafe-unity-') as directory:
        session = load_game(args.save)[0] if args.save else create_game(directory)
        with make_server(session, args.port, args.saves_directory) as server:
            print(f'Unity state: http://127.0.0.1:{server.server_port} (state + shifts + business + saves)', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
