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


def state_view(session, instance_id='', revision=0):
    core = session.core
    cats = []
    for row in session.cat_choices():
        cat_id = row['cat_id']
        cats.append(dict(cat_id=cat_id, content_cat_id=CONTENT_IDS.get(cat_id, cat_id),
                         name=row['name'], stamina=row['stamina'],
                         max_stamina=core.config.max_stamina, working=row['working'],
                         fatigue=row['fatigue'], stress=row['stress'] or 0,
                         health_status=row['health_status'], activity=core.activity(cat_id)))
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
    return dict(version=1, instance_id=instance_id, revision=revision,
                can_set_shifts=core.can_set_shifts, day=core.day, tick=core.tick, funds=core.funds, cats=cats,
                closed=core.closed, required_action=required_action, intake_request=intake_view(session), opening_ticks=core.config.opening_ticks,
                phase='closed' if core.closed else 'preparation' if core.can_set_shifts else 'open',
                seats=[dict(seat_id=key, customer_id=seat.customer_id or '', cat_id=seat.cat_id or '',
                            customer_name=customer_name(seat.customer_id) if seat.customer_id else '') for key, seat in seats.items()],
                customers=customers, housing=housing_view(session),
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
                if not isinstance(command, dict) or set(command) - {'save_id', 'choice'} != {'request_id', 'instance_id', 'expected_revision', 'kind', 'working_cats'}:
                    raise ValueError('操作データの形式が不正です。')
                request_id = command['request_id']
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
                    raise ValueError('操作IDが不正です。')
                if command['kind'] not in ('set_shifts', 'start_business', 'advance_business', 'next_day', 'resolve_intake', 'purchase_housing', 'upgrade_housing', 'save_game', 'load_game') or type(command['expected_revision']) is not int:
                    raise ValueError('未対応の操作です。')
                if command['kind'] == 'resolve_intake' and command.get('choice') not in ('accept', 'decline'):
                    raise ValueError('迎えるか見送るかを選んでください。')
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
                elif command['kind'] in ('save_game', 'load_game'):
                    if command['working_cats']:
                        raise ValueError('保存・再開には出勤猫を指定しないでください。')
                    from .storage.cafe_saves import save_game, load_game
                    from .storage.relationships import RelationshipStore
                    if command['kind'] == 'load_game':
                        candidate = load_game(save_path(command.get('save_id')) / 'cafe.json')[0]
                        candidate.store = MemoryRelationships(candidate.store._read())
                    else:
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
