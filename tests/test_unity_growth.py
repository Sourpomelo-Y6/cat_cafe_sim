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
    mastery_stage = 0

    def test_choices_retry_and_restore(self):
        options = ['play', 'contact', 'quiet'] if self.mastery_stage else ['service', 'rest', 'dispatch']
        kind = 'resolve_growth_mastery' if self.mastery_stage else 'resolve_growth'
        for choice in options:
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                    settings = starting_conditions()
                    settings['growth']['threshold'] = 1
                    session = create_game(Path(directory) / 'source', settings)
                    session.day_off()
                    cat_id = next(iter(session.core.growth['cats']))
                    if self.mastery_stage:
                        for row in session.core.growth['cats'].values():
                            row['specialization'] = 'service'
                            row['mastery_groups'] = dict(play=5, contact=5, quiet=5)
                            if self.mastery_stage == 2:
                                row['mastery'] = 'quiet' if choice != 'quiet' else 'play'
                                row['mastery_selected_day'] = session.core.day
                                row['second_mastery_groups'][choice] = settings['growth']['second_mastery_threshold']
                            elif self.mastery_stage == 3:
                                row['mastery'], row['second_mastery'] = [group for group in options if group != choice]
                                row['mastery_selected_day'] = row['second_mastery_selected_day'] = session.core.day
                                row['third_group_practice'] = dict(started_day=session.core.day, groups=dict.fromkeys(options, 0), mastery=None, selected_day=None)
                                row['third_group_practice']['groups'][choice] = settings['growth']['second_mastery_threshold']
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
                            self.assertEqual([r['choice'] for r in state['growth_choices'][0]['choices']], options)
                            self.assertTrue(next(r for r in state['growth_choices'][0]['choices'] if r['choice'] == choice)['can_select'])
                            self.assertEqual(post('start_business')[0], 422)
                            self.assertEqual(read(), state)
                            self.assertEqual(post(kind, cat_id=cat_id, choice='invalid')[0], 400)
                            self.assertEqual(post(kind, cat_id='unknown', choice=choice)[0], 422)
                            if not self.mastery_stage:
                                code, saved, _ = post('save_game')
                                self.assertEqual(code, 200, saved)
                            reference = copy.deepcopy(session)
                            getattr(reference, kind)(cat_id, choice)
                            code, result, command = post(kind, cat_id=cat_id, choice=choice)
                            self.assertEqual(code, 200, result)
                            self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                            settled = read()
                            self.assertEqual(post(kind, command=command)[:2], (code, result))
                            self.assertEqual(read(), settled)
                            self.assertEqual(len(settled['growth_choices']),len(state['growth_choices'])-1)
                            self.assertEqual(post(kind,cat_id=cat_id,choice=choice)[0],422)
                            self.assertEqual(read(),settled)
                            self.assertEqual(post('start_business')[0],422)
                            while read()['growth_choices']:
                                key=read()['growth_choices'][0]['cat_id']
                                self.assertEqual(post(kind,cat_id=key,choice=choice)[0],200)
                            self.assertEqual(post('start_business')[0],200)
                            if not self.mastery_stage:
                                self.assertEqual(post('load_game', save_id=saved['save_id'])[0], 200)
                                self.assertEqual(read()['growth_choices'],state['growth_choices'])
                                self.assertEqual(session.core.snapshot(), snapshot)
                            self.assertEqual(originals, {p: p.read_bytes() for p in originals})
                        finally:
                            server.shutdown()
                            thread.join()


class UnityMasteryTests(UnityGrowthTests):
    mastery_stage = 1

class UnitySecondMasteryTests(UnityGrowthTests):
    mastery_stage = 2

class UnityThirdMasteryTests(UnityGrowthTests):
    mastery_stage = 3



class UnityMasterySaveTests(unittest.TestCase):
    def test_real_practice_save_restore(self):
        from test_cafe_second_group_mastery import SecondGroupTests
        fixture = SecondGroupTests()
        fixture.setUp()
        try:
            session, cat_id = fixture.prepare()
            fixture.qualify(session, cat_id)
            with make_server(session, 0, Path(fixture.temp.name) / 'unity') as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base + '/state') as response:
                        return json.load(response)
                def post(kind, **extra):
                    state = read()
                    command = dict(kind=kind, request_id=__import__('uuid').uuid4().hex,
                                   instance_id=state['instance_id'], expected_revision=state['revision'], working_cats=[], **extra)
                    with urlopen(Request(base + '/commands', json.dumps(command).encode(), {'Content-Type':'application/json'})) as response:
                        return json.load(response)
                try:
                    waiting = read()['growth_choices']
                    self.assertEqual(waiting[0]['title'], '2つ目の得意な交流')
                    saved = post('save_game')
                    post('resolve_growth_mastery', cat_id=cat_id, choice='contact')
                    self.assertFalse(read()['growth_choices'])
                    post('load_game', save_id=saved['save_id'])
                    self.assertEqual(read()['growth_choices'], waiting)
                finally:
                    server.shutdown()
                    thread.join()
        finally:
            fixture.doCleanups()
