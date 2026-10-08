import copy
import json
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import test_cafe_regular_introduction as regular_tests
from cat_cafe_sim.unity_state_server import make_server, state_view


class UnityRegularIntroductionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = regular_tests.RegularIntroductionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_projection_legacy_funds_and_housing(self):
        fixture = self.fixture
        session = fixture.game()
        before = session.core.snapshot()
        row = state_view(session)['regular_introduction']
        self.assertEqual(session.core.snapshot(), before)
        self.assertEqual(row['status'], 'untriggered')
        self.assertFalse(row['can_decline'])
        fixture.offered(session)
        before = session.core.snapshot()
        row = state_view(session)['regular_introduction']
        self.assertEqual(session.core.snapshot(), before)
        self.assertTrue(row['can_accept'])
        self.assertTrue(row['can_decline'])
        self.assertTrue(row['customer_name'])
        self.assertTrue(row['preferences'])
        self.assertIsNone(state_view(fixture.game(legacy=True))['regular_introduction'])
        for kwargs, reason in [(dict(full=True), '飼育'), (dict(expensive=True), '資金')]:
            blocked = fixture.offered(fixture.game(**kwargs))
            row = state_view(blocked)['regular_introduction']
            self.assertFalse(row['can_accept'])
            self.assertTrue(row['can_decline'])
            self.assertIn(reason, row['accept_reason'])

    def test_http_accept_decline_save_restore_and_duplicate_guards(self):
        for choice in ('accept', 'decline'):
            with self.subTest(choice=choice):
                session = self.fixture.offered(self.fixture.game(intake=True))
                originals = {p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir() if p.is_file()}
                with make_server(session, 0, Path(self.fixture.temp.name)/uuid.uuid4().hex) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    base = f'http://127.0.0.1:{server.server_port}'
                    def read():
                        with urlopen(base+'/state') as response:
                            return json.load(response)
                    def post(kind='resolve_regular_introduction', command=None, **extra):
                        state = read()
                        command = command or dict(kind=kind, request_id=uuid.uuid4().hex, instance_id=state['instance_id'], expected_revision=state['revision'], working_cats=[], **extra)
                        try:
                            with urlopen(Request(base+'/commands', json.dumps(command).encode(), {'Content-Type':'application/json'})) as response:
                                return response.status, json.load(response), command
                        except HTTPError as ex:
                            return ex.code, json.load(ex), command
                    try:
                        row = read()['regular_introduction']
                        cat_id = row['cat_id']
                        self.assertTrue(row['can_decline'])
                        self.assertEqual(read()['intake_request']['status'], 'waiting')
                        self.assertEqual(post(choice='wrong', cat_id=cat_id)[0], 400)
                        self.assertEqual(post(choice=choice, cat_id='wrong')[0], 422)
                        self.assertEqual(post('start_business')[0], 422)
                        waiting_save = post('save_game')[1]['save_id']
                        before_funds = session.core.funds
                        before_count = len(session.core.cats)
                        reference = copy.deepcopy(session)
                        reference.resolve_regular_introduction(choice)
                        code, result, command = post(choice=choice, cat_id=cat_id)
                        self.assertEqual(code, 200, result)
                        self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                        self.assertEqual(post(command=command)[:2], (code, result))
                        self.assertEqual(session.core.funds, before_funds-(row['cost'] if choice=='accept' else 0))
                        self.assertEqual(len(session.core.cats), before_count+(choice=='accept'))
                        final = read()['regular_introduction']
                        self.assertEqual(final['status'], 'accepted' if choice=='accept' else 'declined')
                        self.assertFalse(final['can_accept'])
                        self.assertEqual(post(choice=choice, cat_id=cat_id)[0], 422)
                        resolved_save = post('save_game')[1]['save_id']
                        self.assertEqual(post('load_game', save_id=waiting_save)[0], 200)
                        self.assertEqual(read()['regular_introduction'], row)
                        self.assertEqual(post('load_game', save_id=resolved_save)[0], 200)
                        self.assertEqual(read()['regular_introduction'], final)
                        self.assertEqual(post('resolve_intake', choice='decline')[0], 200)
                        self.assertEqual(post('start_business')[0], 200)
                        self.assertEqual({p:p.read_bytes() for p in originals}, originals)
                    finally:
                        server.shutdown()
                        thread.join(5)
