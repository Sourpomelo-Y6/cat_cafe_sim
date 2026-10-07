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
    for row in session.cat_choices():
        cat_id = row['cat_id']
        cats.append(dict(cat_id=cat_id, content_cat_id=CONTENT_IDS.get(cat_id, cat_id),
                         name=row['name'], stamina=row['stamina'],
                         max_stamina=core.config.max_stamina, working=row['working'],
                         fatigue=row['fatigue'], stress=row['stress'] or 0,
                         health_status=row['health_status'], activity=core.activity(cat_id),
                         health_label=health_text(row['health_status'], core.cats[cat_id].recovery_days_remaining),
                         activity_label=ACTIVITY_LABELS[core.activity(cat_id)], growth_details=growth_description(core, cat_id)))
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
    return dict(version=1, instance_id=instance_id, revision=revision, new_game_options=new_game_options(), objective=core.objective or "", objective_progress=objective_progress_view(session), next_goal=next_goal_view(session),
                can_set_shifts=core.can_set_shifts, day=core.day, tick=core.tick, funds=core.funds, cats=cats,
                closed=core.closed, required_action=required_action, intake_request=intake_view(session), opening_ticks=core.config.opening_ticks,
                phase='closed' if core.closed else 'preparation' if core.can_set_shifts else 'open',
                seats=[dict(seat_id=key, customer_id=seat.customer_id or '', cat_id=seat.cat_id or '',
                            customer_name=customer_name(seat.customer_id) if seat.customer_id else '') for key, seat in seats.items()],
                customers=customers, housing=housing_view(session), goal_result=goal_result_view(session), store_event=store_event_view(session), growth_choices=growth_view(session),
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
                if not isinstance(command, dict) or set(command) - {'save_id', 'choice', 'cat_id'} != {'request_id', 'instance_id', 'expected_revision', 'kind', 'working_cats'}:
                    raise ValueError('操作データの形式が不正です。')
                request_id = command['request_id']
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
                    raise ValueError('操作IDが不正です。')
                if command['kind'] not in ('set_shifts', 'start_business', 'advance_business', 'next_day', 'resolve_intake', 'resolve_store_event', 'resolve_growth', 'resolve_growth_mastery', 'resolve_growth_type_mastery', 'continue_goal', 'continue_patron', 'continue_bond_goal', 'advance_goal', 'purchase_housing', 'upgrade_housing', 'save_game', 'load_game', 'new_game') or type(command['expected_revision']) is not int:
                    raise ValueError('未対応の操作です。')
                if command['kind'] == 'new_game' and command.get('choice') not in ('popularity', 'patron', 'bond', 'free'):
                    raise ValueError('新規ゲームの目標を選んでください。')
                if command['kind'] == 'resolve_intake' and command.get('choice') not in ('accept', 'decline'):
                    raise ValueError('迎えるか見送るかを選んでください。')
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
