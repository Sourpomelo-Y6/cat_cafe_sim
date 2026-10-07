import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from test_unity_missing import missing_game
from cat_cafe_sim.unity_state_server import make_server,state_view

class UnityGameOverTests(unittest.TestCase):
    def test_both_reasons_are_read_only_projections(self):
        with tempfile.TemporaryDirectory() as directory:
            session=missing_game(Path(directory),cost=20000)
            self.assertIsNone(state_view(session)['game_over'])
            session.next_day();session.day_off();session.day_off()
            session.resolve_missing(state_view(session)['missing_cats'][0]['choice'])
            before=session.core.snapshot();view=state_view(session)
            self.assertEqual(view['game_over']['reason'],'funds')
            self.assertEqual(view['game_over']['day'],session.core.day)
            self.assertEqual(view['game_over']['popularity'],session.core.management['popularity'])
            self.assertEqual(session.core.snapshot(),before)
        with tempfile.TemporaryDirectory() as directory:
            from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
            settings=starting_conditions('free')
            settings['management'].update(starting_funds=10000,starting_popularity=1,popularity_loss=1000,stress_per_service_tick=100,runaway_threshold=100)
            settings['store_events']['probability']=0;settings.pop('intake_request',None);settings.pop('growth',None)
            session=create_game(Path(directory),settings);session.set_shifts(['cat-sora'])
            while not session.core.closed:session.automatic_step(auto_assign=True)
            self.assertEqual(state_view(session)['game_over']['reason'],'popularity')

    def test_ended_save_retry_load_and_new_game(self):
        with tempfile.TemporaryDirectory() as directory:
            session=missing_game(Path(directory)/'source',cost=20000)
            session.next_day();session.day_off();session.day_off();session.resolve_missing(state_view(session)['missing_cats'][0]['choice'])
            originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base+'/state') as response:return json.load(response)
                def post(kind,command=None,**extra):
                    state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                    try:
                        with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                    except HTTPError as ex:return ex.code,json.load(ex),command
                try:
                    ended=read();snapshot=session.core.snapshot()
                    for kind in ['set_shifts','start_business','advance_business','next_day']:
                        self.assertEqual(post(kind)[0],422);self.assertEqual(session.core.snapshot(),snapshot)
                    code,result,command=post('save_game');self.assertEqual(code,200,result)
                    self.assertEqual(post('save_game',command)[:2],(code,result));saved=result['save_id']
                    self.assertEqual(post('new_game',choice='free')[0],200);self.assertIsNone(read()['game_over'])
                    self.assertEqual(post('load_game',save_id=saved)[0],200)
                    restored=read()
                    for key in ['game_over','funds','cats']:self.assertEqual(restored[key],ended[key])
                    self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                finally:server.shutdown();thread.join()
