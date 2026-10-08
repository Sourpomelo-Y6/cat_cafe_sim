import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import state_view
from test_unity_dispatch_choices import api


class UnityDispatchTroubleTests(unittest.TestCase):
    def game(self, directory, chance=1, funds=3000, legacy=False):
        selected = starting_conditions('free')
        for key in ('store_events', 'intake_request', 'dispatch_unlocks'):
            selected.pop(key)
        selected['seat_count'] = 2
        selected['management']['starting_funds'] = funds
        selected['dispatch_trouble'].update(base_probability=chance, stress_probability=0)
        if legacy:
            selected.pop('dispatch_trouble')
        return create_game(Path(directory)/'source', selected)

    def depart(self, session):
        session.dispatch('cat-tama', session.core.dispatch_trouble['destination'])
        return session.core.activities['events'][f'dispatch-{session.core.day}-cat-tama']

    def test_projection_readonly_and_exact_python_response_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory)
            event = self.depart(session)
            before = session.core.snapshot()
            row = state_view(session)['dispatch_troubles'][0]
            self.assertEqual(session.core.snapshot(), before)
            self.assertEqual(row['status'], 'scheduled')
            self.assertTrue(all(not r['can_select'] for r in row['choices']))
            session.day_off()
            before = session.core.snapshot()
            row = state_view(session)['dispatch_troubles'][0]
            self.assertEqual(session.core.snapshot(), before)
            self.assertEqual(row['status'], 'waiting')
            self.assertEqual(row['activity_status'], 'missing')
            self.assertEqual(row['return_reward'], 0)
            for option in row['choices']:
                self.assertTrue(option['can_select'])
                reference = copy.deepcopy(session)
                reference.resolve_dispatch_trouble(event['id'], option['choice'])
                updated = reference.core.activities['events'][event['id']]
                self.assertEqual(option['funds_after'], reference.core.funds)
                self.assertEqual(option['cost'], updated['trouble']['cost'])
                self.assertEqual(option['remaining'], updated['remaining'])

    def test_search_http_save_resume_retry_and_return(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory)
            originals = {p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with api(session, Path(directory)/'saves') as (read, post):
                self.assertEqual(post('dispatch_general', cat_id='cat-tama', choice='mountain_lodge_visit')[0], 200)
                event_id = read()['dispatch_troubles'][0]['event_id']
                fixed = copy.deepcopy(session.core.activities['events'][event_id]['trouble'])
                departing = post('save_game')[1]['save_id']
                self.assertEqual(post('resolve_dispatch_trouble', event_id=event_id, choice='search')[0], 422)
                self.assertEqual(post('resolve_dispatch_trouble', choice='search')[0], 400)
                self.assertEqual(post('resolve_dispatch_trouble', event_id=event_id, choice='invalid')[0], 400)
                session.day_off()
                pending = post('save_game')[1]['save_id']
                self.assertEqual(post('set_shifts')[0], 422)
                self.assertEqual(post('receive_general', cat_id='cat-tama', choice=event_id)[0], 422)
                before = session.core.snapshot()
                self.assertEqual(post('resolve_dispatch_trouble', event_id='invalid', choice='search')[0], 422)
                self.assertEqual(post('resolve_dispatch_trouble', event_id=event_id, choice='search', working_cats=['cat-tama'])[0], 422)
                self.assertEqual(session.core.snapshot(), before)
                reference = copy.deepcopy(session)
                reference.resolve_dispatch_trouble(event_id, 'search')
                code, result, command = post('resolve_dispatch_trouble', event_id=event_id, choice='search')
                self.assertEqual(code, 200, result)
                self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                self.assertEqual(post('resolve_dispatch_trouble', command)[:2], (code, result))
                self.assertEqual(post('resolve_dispatch_trouble', dict(command, choice='wait'))[0], 409)
                self.assertEqual(post('resolve_dispatch_trouble', dict(command, request_id=uuid.uuid4().hex))[0], 409)
                self.assertEqual(post('resolve_dispatch_trouble', event_id=event_id, choice='search')[0], 422)
                answered_state = read()['dispatch_troubles'][0]
                self.assertEqual(answered_state['cost'], 100)
                self.assertEqual(answered_state['activity_status'], 'waiting')
                answered = post('save_game')[1]['save_id']
                funds = session.core.funds
                reference = copy.deepcopy(session)
                reference.resolve_activity(event_id)
                code, result, receive = post('receive_general', cat_id='cat-tama', choice=event_id)
                self.assertEqual(code, 200, result)
                self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                self.assertEqual(session.core.funds, funds)
                self.assertEqual(session.core.management['stress']['cat-tama'], 30)
                self.assertEqual(session.core.activity('cat-tama'), 'cafe')
                self.assertEqual(session.core.growth['cats']['cat-tama']['dispatch'], 0)
                self.assertEqual(post('receive_general', receive)[:2], (code, result))
                self.assertEqual(post('receive_general', cat_id='cat-tama', choice=event_id)[0], 422)
                received = post('save_game')[1]['save_id']
                for save_id, status, activity in ((departing, 'scheduled', 'travelling'), (pending, 'waiting', 'missing'), (answered, 'resolved', 'waiting'), (received, 'resolved', 'resolved')):
                    self.assertEqual(post('load_game', save_id=save_id)[0], 200)
                    row = read()['dispatch_troubles'][0]
                    self.assertEqual((row['status'], row['activity_status']), (status, activity))
                    trouble = session.core.activities['events'][event_id]['trouble']
                    self.assertEqual(trouble['draw'], fixed['draw'])
                    self.assertEqual(trouble['rules'], fixed['rules'])
                self.assertEqual(originals, {p:p.read_bytes() for p in originals})

    def test_wait_returns_after_fixed_days_without_search_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory)
            event = self.depart(session)
            session.day_off()
            with api(session, Path(directory)/'saves') as (read, post):
                funds = session.core.funds
                self.assertEqual(post('resolve_dispatch_trouble', event_id=event['id'], choice='wait')[0], 200)
                self.assertEqual(session.core.funds, funds)
                self.assertEqual(post('set_shifts')[0], 200)
                saved = post('save_game')[1]['save_id']
                session.day_off()
                self.assertEqual(read()['general_dispatch']['events'][0]['remaining'], 1)
                self.assertEqual(post('receive_general', cat_id='cat-tama', choice=event['id'])[0], 422)
                session.day_off()
                self.assertTrue(read()['general_dispatch']['events'][0]['can_select'])
                reference = copy.deepcopy(session)
                reference.resolve_activity(event['id'])
                self.assertEqual(post('receive_general', cat_id='cat-tama', choice=event['id'])[0], 200)
                self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                self.assertEqual(session.core.activities['events'][event['id']]['trouble']['cost'], 0)
                self.assertEqual(post('load_game', save_id=saved)[0], 200)
                self.assertEqual(session.core.activities['events'][event['id']]['remaining'], 2)
                self.assertEqual(read()['dispatch_troubles'][0]['choice'], 'wait')

    def test_search_requires_funds_remaining_after_payment(self):
        for initial, allowed in ((160, False), (161, True)):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as directory:
                session = self.game(directory, funds=initial)
                event = self.depart(session)
                session.day_off()
                row = state_view(session)['dispatch_troubles'][0]
                self.assertEqual(row['choices'][0]['can_select'], allowed)
                self.assertTrue(row['choices'][1]['can_select'])
                with api(session, Path(directory)/'saves') as (read, post):
                    before = session.core.snapshot()
                    code = post('resolve_dispatch_trouble', event_id=event['id'], choice='search')[0]
                    self.assertEqual(code, 200 if allowed else 422)
                    if not allowed:
                        self.assertEqual(session.core.snapshot(), before)
                        self.assertEqual(post('resolve_dispatch_trouble', event_id=event['id'], choice='wait')[0], 200)

    def test_not_triggered_and_legacy_games(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory, chance=0)
            event = self.depart(session)
            for _ in range(3):
                session.day_off()
            row = state_view(session)['dispatch_troubles'][0]
            self.assertEqual(row['status'], 'not_triggered')
            self.assertTrue(all(not r['can_select'] for r in row['choices']))
            self.assertGreater(row['return_reward'], 0)
            with api(session, Path(directory)/'saves') as (read, post):
                self.assertEqual(post('resolve_dispatch_trouble', event_id=event['id'], choice='wait')[0], 422)
                self.assertEqual(post('receive_general', cat_id='cat-tama', choice=event['id'])[0], 200)
            legacy = self.game(Path(directory)/'legacy', legacy=True)
            self.assertEqual(state_view(legacy)['dispatch_troubles'], [])
