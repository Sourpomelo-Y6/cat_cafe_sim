import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import make_server


class UnityGrowthTests(unittest.TestCase):
    def test_choices_retry_and_restore(self):
        for choice in ['service', 'rest', 'dispatch']:
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                    settings = starting_conditions()
                    settings['growth']['threshold'] = 1
                    session = create_game(Path(directory) / 'source', settings)
                    session.day_off()
                    cat_id = next(iter(session.core.growth['cats']))
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
                            self.assertGreater(len(state['growth_choices']), 1)
                            self.assertEqual(state['growth_choices'][0]['cat_id'], cat_id)
                            self.assertEqual([r['choice'] for r in state['growth_choices'][0]['choices']], ['service','rest','dispatch'])
                            self.assertTrue(all(r['can_select'] for r in state['growth_choices'][0]['choices']))
                            self.assertEqual(post('start_business')[0], 422)
                            self.assertEqual(read(), state)
                            self.assertEqual(post('resolve_growth', cat_id=cat_id, choice='invalid')[0], 400)
                            self.assertEqual(post('resolve_growth', cat_id='unknown', choice=choice)[0], 422)
                            code, saved, _ = post('save_game')
                            self.assertEqual(code, 200)
                            reference = copy.deepcopy(session)
                            reference.resolve_growth(cat_id, choice)
                            code, result, command = post('resolve_growth', cat_id=cat_id, choice=choice)
                            self.assertEqual(code, 200, result)
                            self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                            settled = read()
                            self.assertEqual(post('resolve_growth', command=command)[:2], (code, result))
                            self.assertEqual(read(), settled)
                            self.assertEqual(len(settled['growth_choices']),len(state['growth_choices'])-1)
                            self.assertEqual(post('resolve_growth',cat_id=cat_id,choice=choice)[0],422)
                            self.assertEqual(read(),settled)
                            self.assertEqual(post('start_business')[0],422)
                            while read()['growth_choices']:
                                key=read()['growth_choices'][0]['cat_id']
                                self.assertEqual(post('resolve_growth',cat_id=key,choice='rest')[0],200)
                            self.assertEqual(post('start_business')[0],200)
                            self.assertEqual(post('load_game', save_id=saved['save_id'])[0], 200)
                            self.assertEqual(read()['growth_choices'],state['growth_choices'])
                            self.assertEqual(session.core.snapshot(), snapshot)
                            self.assertEqual(originals, {p: p.read_bytes() for p in originals})
                        finally:
                            server.shutdown()
                            thread.join()
