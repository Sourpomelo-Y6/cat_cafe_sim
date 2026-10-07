import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import state_view, make_server


class UnityObjectiveTests(unittest.TestCase):
    def test_four_modes_read_only_and_saved_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('popularity', 'patron', 'bond', 'free'):
                session = create_game(Path(directory)/mode, starting_conditions(mode))
                before = copy.deepcopy(session.core.snapshot())
                files = {p: p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
                progress = state_view(session)['objective_progress']
                self.assertEqual(progress['mode'], mode)
                self.assertEqual(progress['status'], 'active')
                if mode == 'popularity':
                    self.assertIn('残り20日', progress['summary'])
                    session.core.closed = True
                    self.assertIn('残り19日', state_view(session)['objective_progress']['summary'])
                    session.core.closed = False
                elif mode == 'patron':
                    for row in session.core.patron['rules'].get('members', []):
                        self.assertIn(row['name'], progress['details'])
                    self.assertIn('全員', progress['details'])
                elif mode == 'bond':
                    self.assertIn('0 / 6匹', progress['summary'])
                    self.assertIn('ムギ：0 / 80', progress['details'])
                    from cat_cafe_sim.core.cafe_player import state as player_state
                    session.core.player_bond = player_state(session.core)
                    session.core.player_bond['affinity']['cat-mugi'] = 80
                    self.assertIn('1 / 6匹', state_view(session)['objective_progress']['summary'])
                    session.core.player_bond = None
                else:
                    self.assertIn('クリア条件や期限はありません', progress['details'])
                    self.assertIsNone(state_view(session)['goal_result'])
                self.assertEqual(session.core.snapshot(), before)
                self.assertEqual(files, {p: p.read_bytes() for p in files})

    def test_real_patron_and_bond_clear_continue_retry_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode, kind in (('patron', 'continue_patron'), ('bond', 'continue_bond_goal')):
                settings = starting_conditions(mode)
                settings.pop('intake_request')
                settings['store_events']['probability'] = 0
                if mode == 'patron':
                    settings['patron'].pop('members')
                    settings['patron']['target'] = settings['patron']['gain']
                else:
                    settings['bond'] = dict(target=1, affinity=.5)
                session = create_game(Path(directory)/mode, settings)
                if mode == 'patron':
                    key = next(iter(session.core.cats))
                    session.dispatch(key, session.core.patron['rules']['destination'])
                    session.day_off(); session.day_off()
                    session.resolve_activity(f'dispatch-1-{key}')
                else:
                    session.play_with_player('cat-mugi')
                    session.player_command('direct'); session.player_command(finish=True)
                captured = copy.deepcopy(session.core.clear_results[mode])
                with make_server(session, 0, Path(directory)/(mode+'-saves')) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                    base = f'http://127.0.0.1:{server.server_port}'
                    def read():
                        with urlopen(base+'/state') as response: return json.load(response)
                    def post(kind, command=None, **extra):
                        state = read()
                        command = command or dict(kind=kind, request_id=uuid.uuid4().hex, instance_id=state['instance_id'], expected_revision=state['revision'], working_cats=[], **extra)
                        with urlopen(Request(base+'/commands', json.dumps(command).encode(), {'Content-Type': 'application/json'})) as response: return json.load(response), command
                    try:
                        before = session.core.snapshot()
                        result = read()['goal_result']
                        self.assertEqual(session.core.snapshot(), before)
                        self.assertEqual(result['kind'], kind)
                        self.assertTrue(result['can_continue'])
                        self.assertIn('クリア時の成果', result['details'])
                        saved = post('save_game')[0]['save_id']
                        reply, command = post(kind)
                        self.assertIsNone(read()['goal_result'])
                        self.assertEqual(post(kind, command)[0], reply)
                        self.assertEqual(session.core.clear_results[mode], captured)
                        post('load_game', save_id=saved)
                        self.assertEqual(read()['goal_result'], result)
                        post(kind)
                        self.assertIn('達成・継続中', read()['objective_progress']['summary'])
                    finally:
                        server.shutdown(); thread.join()
