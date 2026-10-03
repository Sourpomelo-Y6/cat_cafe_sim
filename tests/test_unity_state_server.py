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
                        self.assertFalse(json.load(response)['read_only'])
                    for request, code in [(base + '/missing', 404), (Request(base + '/state', data=b'{}'), 404)]:
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

    def test_shift_commands_retry_conflict_and_rule_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            files = {path: path.read_bytes() for path in session.checkpoint_path.parent.iterdir()}
            with make_server(session, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def post(command):
                    request = Request(base + '/commands', json.dumps(command).encode(), {'Content-Type': 'application/json'})
                    try:
                        with urlopen(request) as response:
                            return response.status, json.load(response)
                    except HTTPError as ex:
                        return ex.code, json.load(ex)
                try:
                    with urlopen(base + '/state') as response:
                        state = json.load(response)
                    command = dict(request_id='first', instance_id=state['instance_id'], expected_revision=0,
                                   kind='set_shifts', working_cats=['cat-mike'])
                    code, result = post(command)
                    self.assertEqual(code, 200)
                    self.assertEqual(result['state']['revision'], 1)
                    after = session.core.snapshot()
                    self.assertEqual(post(command), (code, result))
                    self.assertEqual(after, session.core.snapshot())
                    self.assertEqual(post(dict(command, working_cats=[]))[0], 409)
                    self.assertEqual(post(dict(command, request_id='stale'))[0], 409)
                    self.assertEqual(post(dict(command, request_id='restart', expected_revision=1, instance_id='old'))[0], 409)
                    for cats in [['missing'], ['cat-mike', 'cat-mike']]:
                        invalid = dict(command, request_id=str(cats), expected_revision=1, working_cats=cats)
                        self.assertEqual(post(invalid)[0], 422)
                        self.assertEqual(after, session.core.snapshot())
                    self.assertEqual(post(dict(command, request_id='rest', expected_revision=1, working_cats=[]))[0], 200)
                    self.assertEqual(session.core.working_cats, set())
                    session.core.tick = 1
                    blocked = dict(command, request_id='late', expected_revision=2)
                    self.assertEqual(post(blocked)[0], 422)
                    self.assertEqual(session.core.working_cats, set())
                    self.assertEqual(post({})[0], 400)
                    self.assertEqual(files, {path: path.read_bytes() for path in files})
                finally:
                    server.shutdown()
                    thread.join()
