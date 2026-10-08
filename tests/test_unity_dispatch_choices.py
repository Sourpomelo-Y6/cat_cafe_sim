import copy
import json
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_activities import destinations, reward
from cat_cafe_sim.unity_state_server import make_server, state_view


@contextmanager
def api(session, directory):
    with make_server(session, 0, directory) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def read():
            with urlopen(base+'/state') as response:
                return json.load(response)

        def post(kind, command=None, **extra):
            state = read()
            if command is None:
                command = dict(kind=kind, request_id=uuid.uuid4().hex, instance_id=state['instance_id'],
                               expected_revision=state['revision'], working_cats=[])
                command.update(extra)
            try:
                with urlopen(Request(base+'/commands', json.dumps(command).encode(), {'Content-Type':'application/json'})) as response:
                    return response.status, json.load(response), command
            except HTTPError as error:
                return error.code, json.load(error), command
        try:
            yield read, post
        finally:
            server.shutdown()
            thread.join()


class UnityDispatchChoiceTests(unittest.TestCase):
    def game(self, directory):
        selected = starting_conditions('free')
        for key in ('dispatch_unlocks', 'store_events', 'intake_request'):
            selected.pop(key)
        return create_game(Path(directory)/'source', selected)

    def depart(self, session, destination_id='shopping_street_event'):
        rules = next(r for r in destinations(session.core) if r['id']==destination_id)
        option = next(r for r in state_view(session)['general_dispatch']['options'] if r['choice']==destination_id and r['can_select'])
        session.dispatch(option['cat_id'], rules)
        return next(reversed(session.core.activities['events'].values()))

    def test_projection_matches_python_choices_and_clamped_effects_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory)
            event = self.depart(session)
            row = state_view(session)['dispatch_choices'][0]
            self.assertEqual(row['status'], 'scheduled')
            self.assertTrue(all(not r['can_select'] for r in row['choices']))
            session.day_off()
            cat_id = event['cat_id']
            session.core.cats[cat_id].fatigue = 95
            session.core.management['stress'][cat_id] = 98
            before = session.core.snapshot()
            row = state_view(session)['dispatch_choices'][0]
            self.assertEqual(session.core.snapshot(), before)
            self.assertEqual([r['choice'] for r in row['choices']], [r['id'] for r in event['encounter']['rules']['choices']])
            for option in row['choices']:
                self.assertTrue(option['can_select'])
                reference = copy.deepcopy(session)
                reference.resolve_dispatch_choice(event['id'], option['choice'])
                updated = reference.core.activities['events'][event['id']]
                self.assertEqual(option['changes'], updated['encounter']['changes'])
                self.assertEqual(option['return_reward'], reward(reference.core, updated))
            self.assertEqual(row['choices'][0]['changes']['fatigue_after'], 100)
            self.assertEqual(row['choices'][0]['changes']['stress_after'], 100)

    def test_http_answer_resume_retry_and_return(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory)
            originals = {p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with api(session, Path(directory)/'saves') as (read, post):
                destination = next(r for r in read()['general_dispatch']['options'] if r['choice']=='shopping_street_event' and r['can_select'])
                self.assertEqual(post('dispatch_general', cat_id=destination['cat_id'], choice=destination['choice'])[0], 200)
                event = read()['dispatch_choices'][0]
                self.assertEqual(post('resolve_dispatch_choice', event_id=event['event_id'], choice='accept')[0], 422)
                self.assertEqual(post('resolve_dispatch_choice', choice='accept')[0], 400)
                session.day_off()
                waiting = post('save_game')[1]['save_id']
                self.assertEqual(post('set_shifts')[0], 422)
                before = session.core.snapshot()
                self.assertEqual(post('resolve_dispatch_choice', event_id=event['event_id'], choice='invalid')[0], 422)
                self.assertEqual(post('resolve_dispatch_choice', event_id='not-an-event', choice='accept')[0], 422)
                self.assertEqual(post('resolve_dispatch_choice', event_id=event['event_id'], choice='accept', working_cats=[destination['cat_id']])[0], 422)
                self.assertEqual(session.core.snapshot(), before)
                reference = copy.deepcopy(session)
                reference.resolve_dispatch_choice(event['event_id'], 'accept')
                funds = session.core.funds
                code, result, command = post('resolve_dispatch_choice', event_id=event['event_id'], choice='accept')
                self.assertEqual(code, 200, result)
                self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                self.assertEqual(session.core.funds, funds)
                self.assertEqual(post('resolve_dispatch_choice', command)[:2], (code, result))
                self.assertEqual(post('resolve_dispatch_choice', dict(command, choice='decline'))[0], 409)
                stale = dict(command, request_id=uuid.uuid4().hex)
                self.assertEqual(post('resolve_dispatch_choice', stale)[0], 409)
                self.assertEqual(post('resolve_dispatch_choice', event_id=event['event_id'], choice='accept')[0], 422)
                answered_state = read()['dispatch_choices'][0]
                self.assertEqual(answered_state['status'], 'resolved')
                self.assertTrue(all(not r['can_select'] for r in answered_state['choices']))
                answered = post('save_game')[1]['save_id']
                self.assertEqual(post('set_shifts')[0], 200)
                session.day_off()
                return_row = read()['general_dispatch']['events'][0]
                self.assertTrue(return_row['can_select'])
                reference = copy.deepcopy(session)
                reference.resolve_activity(event['event_id'])
                self.assertEqual(post('receive_general', cat_id=destination['cat_id'], choice=event['event_id'])[0], 200)
                self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                self.assertEqual(post('load_game', save_id=answered)[0], 200)
                self.assertEqual(read()['dispatch_choices'][0], answered_state)
                self.assertEqual(post('load_game', save_id=waiting)[0], 200)
                self.assertEqual(read()['dispatch_choices'][0]['status'], 'waiting')
                self.assertTrue(read()['dispatch_choices'][0]['choices'][0]['can_select'])
                self.assertEqual(post('resolve_dispatch_choice', stale)[0], 409)
                self.assertEqual(originals, {p:p.read_bytes() for p in originals})

    def test_relief_choices_and_multiple_pending_events(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.game(directory)
            first = self.depart(session)
            second = self.depart(session, 'out_of_town_visit')
            session.day_off()
            before = session.core.snapshot()
            rows = state_view(session)['dispatch_choices']
            self.assertEqual(session.core.snapshot(), before)
            self.assertEqual(len(rows), 2)
            option = next(r for r in rows[1]['choices'] if r['choice']=='rest')
            self.assertEqual(option['reward_delta'], -50)
            self.assertEqual(option['changes']['fatigue_after'], 0)
            self.assertGreaterEqual(option['changes']['stress_after'], 0)
            with api(session, Path(directory)/'saves') as (read, post):
                self.assertEqual(post('resolve_dispatch_choice', event_id=first['id'], choice='decline')[0], 200)
                self.assertEqual(post('set_shifts')[0], 422)
                self.assertEqual(post('resolve_dispatch_choice', event_id=second['id'], choice='rest')[0], 200)
                self.assertEqual(post('set_shifts')[0], 200)
                self.assertTrue(all(r['status']=='resolved' for r in read()['dispatch_choices']))
