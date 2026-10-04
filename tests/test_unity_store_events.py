import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_store_events import draw, event_types
from cat_cafe_sim.unity_state_server import make_server


class UnityStoreEventsTests(unittest.TestCase):
    def test_choices_retry_and_restore(self):
        for kind, choices in [('trouble', ['repair', 'patch', 'close']), ('support', ['full', 'small', 'decline'])]:
            for choice in choices:
                with self.subTest(kind=kind, choice=choice), tempfile.TemporaryDirectory() as directory:
                    settings = starting_conditions()
                    settings['store_events']['probability'] = 1
                    types = event_types(settings['store_events'])
                    seed = next(s for s in range(1000) if types[int(draw(s, 1, 'type') * len(types))] == kind)
                    session = create_game(Path(directory) / 'source', settings, seed=seed)
                    originals = {p: p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
                    with make_server(session, 0, Path(directory) / 'saves') as server:
                        thread = threading.Thread(target=server.serve_forever, daemon=True)
                        thread.start()
                        base = f'http://127.0.0.1:{server.server_port}'
                        counter = 0

                        def read():
                            with urlopen(base + '/state') as response:
                                return json.load(response)

                        def post(kind, command=None, **extra):
                            nonlocal counter
                            counter += 1
                            state = read()
                            command = command or dict(kind=kind, request_id=str(counter), instance_id=state['instance_id'],
                                                      expected_revision=state['revision'], working_cats=[], **extra)
                            try:
                                with urlopen(Request(base + '/commands', json.dumps(command).encode(), {'Content-Type': 'application/json'})) as response:
                                    return response.status, json.load(response), command
                            except HTTPError as ex:
                                return ex.code, json.load(ex), command

                        try:
                            snapshot = session.core.snapshot()
                            state = read()
                            self.assertEqual(session.core.snapshot(), snapshot)
                            self.assertEqual(state['store_event']['kind'], kind)
                            self.assertEqual([r['choice'] for r in state['store_event']['choices']], choices)
                            self.assertTrue(all(r['can_select'] for r in state['store_event']['choices']))
                            self.assertEqual(post('start_business')[0], 422)
                            self.assertEqual(read(), state)
                            self.assertEqual(post('resolve_store_event', choice='invalid')[0], 400)
                            self.assertEqual(post('resolve_store_event', choice='full' if kind == 'trouble' else 'close')[0], 422)
                            code, saved, _ = post('save_game')
                            self.assertEqual(code, 200)
                            reference = copy.deepcopy(session)
                            if choice == 'close':
                                reference.day_off()
                            else:
                                reference.resolve_store_event(choice)
                            code, result, command = post('resolve_store_event', choice=choice)
                            self.assertEqual(code, 200, result)
                            self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                            settled = read()
                            self.assertEqual(post('resolve_store_event', command=command)[:2], (code, result))
                            self.assertEqual(read(), settled)
                            if choice != 'close':
                                self.assertIsNone(settled['store_event'])
                                self.assertEqual(post('resolve_store_event', choice=choice)[0], 422)
                                self.assertEqual(post('start_business')[0], 200)
                            self.assertEqual(post('load_game', save_id=saved['save_id'])[0], 200)
                            self.assertEqual(read()['store_event']['kind'], kind)
                            self.assertEqual(session.core.snapshot(), snapshot)
                            self.assertEqual(originals, {p: p.read_bytes() for p in originals})
                        finally:
                            server.shutdown()
                            thread.join()
