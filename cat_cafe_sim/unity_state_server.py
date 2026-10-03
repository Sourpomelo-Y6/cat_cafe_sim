"""Loopback state and shift-command adapter for the Unity prototype."""
import argparse
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
                         health_status=row['health_status'], activity=core.activity(cat_id)))
    return dict(version=1, instance_id=instance_id, revision=revision,
                can_set_shifts=core.can_set_shifts, day=core.day, tick=core.tick, funds=core.funds, cats=cats)


def make_server(session, port=8190):
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
                if command['kind'] != 'set_shifts' or type(command['expected_revision']) is not int:
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
                session.set_shifts(command['working_cats'])
                revision += 1
                data, code = dict(request_id=request_id, state=state_view(session, instance_id, revision)), 200
            except ValueError as ex:
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
            print(f'Unity state: http://127.0.0.1:{server.server_port} (state + shifts)', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
