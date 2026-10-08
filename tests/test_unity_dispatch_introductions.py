import copy
import unittest
import uuid
from pathlib import Path

import test_cafe_dispatch_introduction as fixtures
import test_cafe_photo_introduction as photo_fixtures
from cat_cafe_sim.unity_state_server import state_view
from cat_cafe_sim.core.cafe_activities import income
from test_unity_dispatch_choices import api


class UnityDispatchIntroductionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DispatchIntroductionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_projection_readonly_funds_housing_and_legacy(self):
        fixture = self.fixture
        session = fixture.game()
        event_id = fixture.depart(session)
        before = session.core.snapshot()
        row = state_view(session)['dispatch_introductions'][0]
        self.assertEqual(session.core.snapshot(), before)
        self.assertEqual(row['status'], 'scheduled')
        self.assertFalse(row['can_accept'])
        self.assertFalse(row['can_decline'])
        candidate = session.core.activities['events'][event_id]['introduction']
        self.assertEqual(row['cat_id'], candidate['cat_id'])
        self.assertEqual(row['name'], candidate['candidate']['name'])
        self.assertTrue(row['features'])
        self.assertTrue(row['preferences'])
        fixture.receive(session, event_id)
        before = session.core.snapshot()
        row = state_view(session)['dispatch_introductions'][0]
        self.assertEqual(session.core.snapshot(), before)
        self.assertTrue(row['can_accept'])
        self.assertTrue(row['can_decline'])
        session.core.funds = row['cost']
        row = state_view(session)['dispatch_introductions'][0]
        self.assertFalse(row['can_accept'])
        self.assertTrue(row['can_decline'])
        self.assertIn('資金', row['accept_reason'])
        full = fixture.game()
        full.open_recruitment()
        full.recruit_cat('rescue-1')
        full_id = fixture.depart(full)
        fixture.receive(full, full_id)
        row = state_view(full)['dispatch_introductions'][0]
        self.assertFalse(row['can_accept'])
        self.assertTrue(row['can_decline'])
        self.assertTrue(row['accept_reason'])
        with api(full, Path(fixture.temp.name)/'full-saves') as (read, post):
            before = full.core.snapshot()
            self.assertEqual(post('resolve_dispatch_introduction', event_id=full_id, choice='accept')[0], 422)
            self.assertEqual(full.core.snapshot(), before)
            self.assertEqual(post('resolve_dispatch_introduction', event_id=full_id, choice='decline')[0], 200)
        legacy = fixture.game(legacy=True)
        old_id = fixture.depart(legacy)
        fixture.receive(legacy, old_id)
        self.assertEqual(state_view(legacy)['dispatch_introductions'], [])

    def test_http_accept_save_retry_registration_and_fixed_candidate(self):
        fixture = self.fixture
        session = fixture.game()
        originals = {p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
        with api(session, Path(fixture.temp.name)/'saves') as (read, post):
            self.assertEqual(post('dispatch_general', cat_id='cat-mike', choice='shopping_street_event')[0], 200)
            offered = read()['dispatch_introductions'][0]
            event_id = offered['event_id']
            departing = post('save_game')[1]['save_id']
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='accept')[0], 422)
            self.assertEqual(post('resolve_dispatch_introduction', choice='accept')[0], 400)
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='invalid')[0], 400)
            fixture.receive(session, event_id)
            waiting_state = read()['dispatch_introductions'][0]
            waiting = post('save_game')[1]['save_id']
            self.assertEqual(post('set_shifts')[0], 422)
            before = session.core.snapshot()
            self.assertEqual(post('resolve_dispatch_introduction', event_id='invalid', choice='accept')[0], 422)
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='accept', working_cats=['cat-mike'])[0], 422)
            self.assertEqual(session.core.snapshot(), before)
            reference = copy.deepcopy(session)
            reference.resolve_dispatch_introduction(event_id, 'accept')
            code, result, command = post('resolve_dispatch_introduction', event_id=event_id, choice='accept')
            self.assertEqual(code, 200, result)
            self.assertEqual(session.core.snapshot(), reference.core.snapshot())
            self.assertEqual(session.store._read(), reference.store._read())
            self.assertEqual(session.profiles, reference.profiles)
            self.assertEqual(session.core.funds, before['funds']-offered['cost'])
            self.assertIn(offered['cat_id'], session.profiles)
            self.assertNotIn(offered['cat_id'], session.core.working_cats)
            self.assertEqual(post('resolve_dispatch_introduction', command)[:2], (code, result))
            self.assertEqual(post('resolve_dispatch_introduction', dict(command, choice='decline'))[0], 409)
            self.assertEqual(post('resolve_dispatch_introduction', dict(command, request_id=uuid.uuid4().hex))[0], 409)
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='accept')[0], 422)
            answered = post('save_game')[1]['save_id']
            joined = session.core.snapshot()
            self.assertEqual(post('set_shifts')[0], 200)
            self.assertEqual(post('load_game', save_id=departing)[0], 200)
            self.assertEqual(read()['dispatch_introductions'][0]['name'], offered['name'])
            self.assertEqual(read()['dispatch_introductions'][0]['cat_id'], offered['cat_id'])
            self.assertEqual(post('load_game', save_id=waiting)[0], 200)
            self.assertEqual(read()['dispatch_introductions'][0], waiting_state)
            self.assertEqual(post('load_game', save_id=answered)[0], 200)
            self.assertEqual(session.core.snapshot(), joined)
            self.assertFalse(read()['dispatch_introductions'][0]['can_accept'])
            self.assertEqual(originals, {p:p.read_bytes() for p in originals})

    def test_intake_and_multiple_introductions_can_be_answered_independently(self):
        fixture = self.fixture
        session = fixture.game(intake=True)
        session.open_recruitment()
        session.recruit_cat('rescue-1')
        session.purchase_housing()
        first = fixture.depart(session)
        second = fixture.depart(session, 'rescue-1')
        session.day_off()
        session.resolve_dispatch_choice(first, 'decline')
        session.resolve_dispatch_choice(second, 'decline')
        session.day_off()
        session.resolve_activity(first)
        session.resolve_activity(second)
        with api(session, Path(fixture.temp.name)/'saves') as (read, post):
            rows = read()['dispatch_introductions']
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r['can_accept'] and r['can_decline'] for r in rows))
            self.assertEqual(post('resolve_dispatch_introduction', event_id=first, choice='accept')[0], 200)
            self.assertEqual(post('set_shifts')[0], 422)
            self.assertEqual(post('resolve_intake', choice='accept')[0], 200)
            before = session.core.snapshot()
            dispatch_income = income(session.core)
            self.assertEqual(post('resolve_dispatch_introduction', event_id=second, choice='decline')[0], 200)
            self.assertEqual(session.core.funds, before['funds'])
            self.assertEqual(session.core.management['popularity'], before['management']['popularity'])
            self.assertEqual(income(session.core), dispatch_income)
            self.assertNotIn(rows[1]['cat_id'], session.core.cats)
            self.assertEqual(len(session.core.cats), 8)
            self.assertEqual(post('set_shifts')[0], 200)

    def test_closed_return_defers_answer_until_next_preparation(self):
        fixture = self.fixture
        session = fixture.game()
        event_id = fixture.depart(session)
        while not session.core.closed:
            session.automatic_step()
        session.resolve_dispatch_choice(event_id, 'decline')
        session.next_day()
        while not session.core.closed:
            session.automatic_step()
        session.resolve_activity(event_id)
        with api(session, Path(fixture.temp.name)/'saves') as (read, post):
            self.assertEqual(read()['dispatch_introductions'][0]['status'], 'scheduled')
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='decline')[0], 422)
            self.assertEqual(post('next_day')[0], 200)
            self.assertEqual(read()['dispatch_introductions'][0]['status'], 'waiting')
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='decline')[0], 200)

    def test_photo_studio_candidate_is_supported(self):
        fixture = photo_fixtures.PhotoIntroductionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        session = fixture.game()
        event_id = fixture.depart(session)
        fixture.receive(session, event_id)
        with api(session, Path(fixture.temp.name)/'saves') as (read, post):
            row = read()['dispatch_introductions'][0]
            self.assertIn('撮影', row['destination'])
            self.assertTrue(row['can_accept'])
            reference = copy.deepcopy(session)
            reference.resolve_dispatch_introduction(event_id, 'accept')
            self.assertEqual(post('resolve_dispatch_introduction', event_id=event_id, choice='accept')[0], 200)
            self.assertEqual(session.core.snapshot(), reference.core.snapshot())
            self.assertEqual(session.profiles[row['cat_id']], reference.profiles[row['cat_id']])
