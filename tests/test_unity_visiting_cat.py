import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import make_server, state_view


def game(directory, legacy=False, full=False):
    selected = starting_conditions('popularity')
    selected['management'].update(starting_funds=10000, stress_per_service_tick=0)
    selected['store_events']['probability'] = 0
    selected['growth']['threshold'] = 1000
    selected['goal'].update(target=105, stages=[dict(days=30, target=250), dict(days=30, target=300)])
    for name in ('customer_discontent', 'customer_trust', 'intake_request', 'regular_introduction'):
        selected.pop(name)
    if legacy:
        selected.pop('visiting_cat')
    if full:
        selected['profiles']['cats']['sixth'] = copy.deepcopy(selected['profiles']['cats']['cat-mugi'])
    return create_game(Path(directory), selected)


def offer(session):
    while not session.core.closed:
        session.automatic_step()
    session.advance_goal()
    session.next_day()


class UnityVisitingCatTests(unittest.TestCase):
    def test_projection_is_read_only_and_legacy_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            session = game(Path(directory)/'game')
            before = session.core.snapshot()
            view = state_view(session)['visiting_cat']
            self.assertEqual(session.core.snapshot(), before)
            self.assertEqual(view['status'], 'untriggered')
            self.assertFalse(view['can_interact'])
            offer(session)
            before = session.core.snapshot()
            view = state_view(session)['visiting_cat']
            self.assertEqual(session.core.snapshot(), before)
            self.assertTrue(view['can_interact'])
            self.assertTrue(view['can_skip'])
            self.assertFalse(view['can_accept'])
            self.assertEqual(view['content_cat_id'], 'visiting-cat-1')
            self.assertIsNone(state_view(game(Path(directory)/'legacy', True))['visiting_cat'])

    def test_http_daily_progress_confirmed_join_retries_and_save_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            session = game(Path(directory)/'source')
            offer(session)
            originals = {path: path.read_bytes() for path in session.checkpoint_path.parent.iterdir() if path.is_file()}
            with make_server(session, 0, Path(directory)/'saves') as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base+'/state') as response:
                        return json.load(response)
                def post(kind='resolve_visiting_cat', command=None, **extra):
                    state = read()
                    command = command or dict(kind=kind, request_id=uuid.uuid4().hex, instance_id=state['instance_id'], expected_revision=state['revision'], working_cats=[], **extra)
                    try:
                        with urlopen(Request(base+'/commands', json.dumps(command).encode(), {'Content-Type':'application/json'})) as response:
                            return response.status, json.load(response), command
                    except HTTPError as ex:
                        return ex.code, json.load(ex), command
                try:
                    cat_id = read()['visiting_cat']['cat_id']
                    self.assertEqual(post(choice='wrong', cat_id=cat_id)[0], 400)
                    self.assertEqual(post(choice='interact', cat_id='wrong')[0], 422)
                    self.assertEqual(post(choice='accept', cat_id=cat_id)[0], 422)
                    code, result, command = post(choice='skip', cat_id=cat_id)
                    self.assertEqual(code, 200, result)
                    self.assertEqual(post(command=command)[:2], (code, result))
                    self.assertEqual(read()['visiting_cat']['progress'], 0)
                    self.assertFalse(read()['visiting_cat']['can_interact'])
                    self.assertEqual(post(choice='interact', cat_id=cat_id)[0], 422)
                    session.day_off()
                    for index in range(3):
                        reference = copy.deepcopy(session)
                        reference.resolve_visiting_cat('interact')
                        code, result, command = post(choice='interact', cat_id=cat_id)
                        self.assertEqual(code, 200, result)
                        self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                        self.assertEqual(post(command=command)[:2], (code, result))
                        if index < 2:
                            session.day_off()
                    view = read()['visiting_cat']
                    self.assertEqual(view['status'], 'ready')
                    self.assertTrue(view['can_accept'])
                    ready_save = post('save_game')[1]['save_id']
                    before_funds = read()['funds']
                    before_count = len(read()['cats'])
                    code, result, command = post(choice='accept', cat_id=cat_id)
                    self.assertEqual(code, 200, result)
                    self.assertEqual(post(command=command)[:2], (code, result))
                    final = read()
                    self.assertEqual(final['funds'], before_funds-view['cost'])
                    self.assertEqual(len(final['cats']), before_count+1)
                    self.assertEqual(final['visiting_cat']['status'], 'accepted')
                    self.assertFalse(final['visiting_cat']['can_accept'])
                    joined = next(cat for cat in final['cats'] if cat['cat_id'] == cat_id)
                    self.assertFalse(joined['working'])
                    self.assertEqual(joined['health_status'], 'healthy')
                    self.assertEqual(post(choice='accept', cat_id=cat_id)[0], 422)
                    joined_save = post('save_game')[1]['save_id']
                    self.assertEqual(post('load_game', save_id=ready_save)[0], 200)
                    self.assertEqual(read()['visiting_cat'], view)
                    self.assertEqual(post('load_game', save_id=joined_save)[0], 200)
                    self.assertEqual(read()['visiting_cat'], final['visiting_cat'])
                    self.assertEqual({path: path.read_bytes() for path in originals}, originals)
                finally:
                    server.shutdown()
                    thread.join(5)

    def test_funds_housing_and_operating_phase_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            session = game(Path(directory)/'game')
            offer(session)
            for index in range(3):
                session.resolve_visiting_cat('interact')
                if index < 2:
                    session.day_off()
            cost = session.core.visiting_cat['rules']['candidate']['cost']
            session.core.funds = cost
            view = state_view(session)['visiting_cat']
            self.assertFalse(view['can_accept'])
            self.assertIn('資金', view['accept_reason'])
            session.core.funds = 10000
            session.automatic_step()
            view = state_view(session)['visiting_cat']
            self.assertFalse(view['can_accept'])
            self.assertFalse(view['can_skip'])
            self.assertIn('営業準備', view['reason'])
            full = game(Path(directory)/'full', full=True)
            offer(full)
            for index in range(3):
                full.resolve_visiting_cat('interact')
                if index < 2:
                    full.day_off()
            view = state_view(full)['visiting_cat']
            self.assertFalse(view['can_accept'])
            self.assertIn('飼育', view['accept_reason'])
