import json
import tempfile
import threading
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import make_server, state_view


class UnityStateTests(unittest.TestCase):
    def test_read_only_http_and_live_session_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            before = session.core.snapshot()
            with make_server(session, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = f'http://127.0.0.1:{server.server_port}'
                    with urlopen(base + '/state') as response:
                        data = json.load(response)
                    self.assertEqual(len(data['cats']), 5)
                    mike = next(cat for cat in data['cats'] if cat['cat_id'] == 'cat-mike')
                    self.assertEqual(mike['name'], 'ミケ')
                    self.assertEqual(mike['content_cat_id'], 'playtest-mike')
                    self.assertEqual(before, session.core.snapshot())
                    with urlopen(base + '/health') as response:
                        self.assertTrue(json.load(response)['read_only'])
                    for request, code in [(base + '/missing', 404), (Request(base + '/state', data=b'{}'), 501)]:
                        with self.assertRaises(HTTPError) as caught:
                            urlopen(request)
                        self.assertEqual(caught.exception.code, code)
                finally:
                    server.shutdown()
                    thread.join()
            session.set_shifts(['cat-mike'])
            session.core.cats['cat-mike'].stamina = 73
            data = state_view(session)
            rows = {cat['cat_id']: cat for cat in data['cats']}
            self.assertEqual(rows['cat-mike']['stamina'], 73)
            self.assertTrue(rows['cat-mike']['working'])
            self.assertFalse(rows['cat-tama']['working'])
