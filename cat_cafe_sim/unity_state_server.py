"""Loopback, read-only state adapter for the Unity prototype."""
import argparse
import json
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


CONTENT_IDS = {f'cat-{name}': f'playtest-{name}' for name in ('mike', 'tama', 'sora', 'kohaku', 'mugi')}


def state_view(session):
    core = session.core
    cats = []
    for row in session.cat_choices():
        cat_id = row['cat_id']
        cats.append(dict(cat_id=cat_id, content_cat_id=CONTENT_IDS.get(cat_id, cat_id),
                         name=row['name'], stamina=row['stamina'],
                         max_stamina=core.config.max_stamina, working=row['working'],
                         health_status=row['health_status'], activity=core.activity(cat_id)))
    return dict(version=1, day=core.day, tick=core.tick, funds=core.funds, cats=cats)


def make_server(session, port=8190):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health':
                data, code = dict(version=1, service='cat-cafe-state', read_only=True), 200
            elif self.path == '/state':
                data, code = state_view(session), 200
            else:
                data, code = dict(error='not_found'), 404
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            print(f'Unity state: http://127.0.0.1:{server.server_port} (read-only)', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
