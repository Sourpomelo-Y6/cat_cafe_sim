"""Loopback state, shifts and one-day business adapter for Unity."""
import argparse
import copy
import json
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


CONTENT_IDS = {f'cat-{name}': f'playtest-{name}' for name in ('mike', 'tama', 'sora', 'kohaku', 'mugi')}


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
    summary = core.summary()
    from .core.cafe_finance import values
    return dict(version=1, instance_id=instance_id, revision=revision,
                can_set_shifts=core.can_set_shifts, day=core.day, tick=core.tick, funds=core.funds, cats=cats,
                closed=core.closed, opening_ticks=core.config.opening_ticks,
                phase='closed' if core.closed else 'preparation' if core.can_set_shifts else 'open',
                seats=[dict(seat_id=key, customer_id=seat.customer_id or '', cat_id=seat.cat_id or '') for key, seat in seats.items()],
                waiting_count=len(core.queue), completed_interactions=summary['completed_interactions'],
                revenue=summary['revenue'], finance=values(summary) if core.closed else None)


def make_server(session, port=8190):
    # Normal automatic service persists relationship receipts. Keep these in memory
    # until the Unity save feature exists; never modify the loaded game's files.
    from .storage.cafe_saves import MemoryRelationships
    session.store = MemoryRelationships(session.store._read())
    instance_id = uuid.uuid4().hex
    revision = 0
    results = {}
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
                if not isinstance(command, dict) or set(command) != {'request_id', 'instance_id', 'expected_revision', 'kind', 'working_cats'}:
                    raise ValueError('操作データの形式が不正です。')
                request_id = command['request_id']
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
                    raise ValueError('操作IDが不正です。')
                if command['kind'] not in ('set_shifts', 'start_business', 'advance_business') or type(command['expected_revision']) is not int:
                    raise ValueError('未対応の操作です。')
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
                if command['kind'] == 'set_shifts':
                    candidate.set_shifts(command['working_cats'])
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
                data, code = dict(request_id=request_id, state=projected), 200
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
    args = parser.parse_args()
    from .cafe_new_game import create_game
    from .storage.cafe_saves import load_game
    with tempfile.TemporaryDirectory(prefix='cat-cafe-unity-') as directory:
        session = load_game(args.save)[0] if args.save else create_game(directory)
        with make_server(session, args.port) as server:
            print(f'Unity state: http://127.0.0.1:{server.server_port} (state + shifts + business)', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
