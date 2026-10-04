import json
import tempfile
import threading
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import make_server, state_view


class UnityStateTests(unittest.TestCase):
    def test_one_day_business_matches_existing_session_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            reference = create_game(directory)
            files = {path: path.read_bytes() for path in session.checkpoint_path.parent.iterdir()}
            with make_server(session, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base + '/state') as response:
                        return json.load(response)
                def post(state, kind, request_id, working_cats=None):
                    command = dict(request_id=request_id, instance_id=state['instance_id'], expected_revision=state['revision'],
                                   kind=kind, working_cats=working_cats or [])
                    request = Request(base + '/commands', json.dumps(command).encode(), {'Content-Type': 'application/json'})
                    try:
                        with urlopen(request) as response:
                            return response.status, json.load(response)
                    except HTTPError as ex:
                        return ex.code, json.load(ex)
                try:
                    initial = read()
                    self.assertEqual(post(initial, 'advance_business', 'early')[0], 422)
                    _, response = post(initial, 'set_shifts', 'all-rest')
                    rest = response['state']
                    self.assertEqual(post(rest, 'start_business', 'no-workers')[0], 422)
                    _, response = post(rest, 'set_shifts', 'all-work', list(session.core.cats))
                    initial = response['state']
                    code, response = post(initial, 'start_business', 'start')
                    self.assertEqual(code, 200)
                    self.assertEqual(response['state']['tick'], 1)
                    self.assertFalse(response['state']['can_set_shifts'])
                    self.assertEqual(post(initial, 'start_business', 'start'), (code, response))
                    state = response['state']
                    snapshot = session.core.snapshot()
                    # If automatic assignment has happened before an error, discard
                    # the entire candidate instead of leaving a half-applied step.
                    with patch.object(type(session.policy), 'choose', side_effect=ValueError('policy failed')):
                        self.assertEqual(post(state, 'advance_business', 'failure')[0], 422)
                    self.assertEqual(session.core.snapshot(), snapshot)
                    self.assertEqual(read()['revision'], state['revision'])
                    self.assertEqual(post(state, 'start_business', 'twice')[0], 422)
                    occupied = False
                    while not state['closed']:
                        code, response = post(state, 'advance_business', f"tick-{state['tick']}")
                        self.assertEqual(code, 200, response)
                        state = response['state']
                        for seat in state['seats']:
                            if seat['customer_id']:
                                customer = next(row for row in state['customers'] if row['customer_id'] == seat['customer_id'])
                                self.assertEqual(customer['status'], 'seated')
                                self.assertEqual(customer['seat_id'], seat['seat_id'])
                                self.assertEqual(customer['name'], seat['customer_name'])
                        occupied |= any(seat['customer_id'] for seat in state['seats'])
                    while not reference.core.closed:
                        reference.automatic_step(auto_assign=True)
                    self.assertTrue(occupied)
                    self.assertEqual(state['tick'], session.core.config.opening_ticks)
                    self.assertGreater(state['completed_interactions'], 0)
                    self.assertTrue(all(customer['status'] == 'departed' for customer in state['customers']))
                    self.assertEqual(session.core.summary(), reference.core.summary())
                    self.assertEqual(state['finance']['closing_funds'], state['funds'])
                    self.assertEqual(state['finance']['net_cash_flow'], state['finance']['total_income'] - state['finance']['total_expenses'])
                    after = session.core.snapshot()
                    self.assertEqual(post(state, 'advance_business', 'after-close')[0], 422)
                    self.assertEqual(after, session.core.snapshot())
                    self.assertEqual(files, {path: path.read_bytes() for path in files})
                finally:
                    server.shutdown()
                    thread.join()

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
