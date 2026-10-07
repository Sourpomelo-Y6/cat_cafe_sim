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


class UnityDispatchTests(unittest.TestCase):
    def test_conditions_and_projection_do_not_change_game(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory),starting_conditions('patron'))
            before=session.core.snapshot()
            rows=state_view(session)['patron_dispatch']['options']
            self.assertEqual(session.core.snapshot(),before)
            sora={r['choice']:r for r in rows if r['cat_id']=='cat-sora'}
            self.assertEqual(len(sora),3)
            self.assertEqual(sora['patron_visit']['reward'],220)
            self.assertEqual(sora['patron_visit']['satisfaction'],30)
            self.assertEqual(sora['patron_moody_visit']['satisfaction'],20)
            self.assertEqual(sora['patron_strict_visit']['satisfaction'],0)
            self.assertTrue(sora['patron_strict_visit']['can_select'])
            session.core.cats['cat-sora'].fatigue=41
            self.assertFalse(next(r for r in state_view(session)['patron_dispatch']['options'] if r['cat_id']=='cat-sora')['can_select'])
            other=create_game(Path(directory)/'free',starting_conditions('free'))
            self.assertEqual(state_view(other)['patron_dispatch']['options'],[])

    def test_retry_return_and_save_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source',starting_conditions('patron'))
            originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base+'/state') as response:return json.load(response)
                def post(kind,command=None,**extra):
                    state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                    try:
                        with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                    except HTTPError as ex:return ex.code,json.load(ex),command
                try:
                    before=session.core.snapshot();self.assertEqual(post('dispatch_patron',cat_id='cat-sora',choice='invalid')[0],422);self.assertEqual(session.core.snapshot(),before)
                    self.assertEqual(post('dispatch_patron',cat_id='cat-sora')[0],400)
                    reference=copy.deepcopy(session)
                    from cat_cafe_sim.core.cafe_patron import destinations
                    reference.dispatch('cat-sora',destinations(reference.core)[0])
                    code,result,command=post('dispatch_patron',cat_id='cat-sora',choice='patron_visit');self.assertEqual(code,200,result)
                    self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                    self.assertEqual(post('dispatch_patron',command)[:2],(code,result))
                    event=read()['patron_dispatch']['events'][0];self.assertEqual(event['remaining'],2);self.assertFalse(event['can_select'])
                    self.assertEqual(post('receive_patron',cat_id='cat-sora',choice=event['choice'])[0],422)
                    saved=post('save_game')[1]['save_id'];session.day_off()
                    self.assertEqual(read()['patron_dispatch']['events'][0]['remaining'],1)
                    self.assertEqual(post('load_game',save_id=saved)[0],200)
                    self.assertEqual(read()['patron_dispatch']['events'][0],event)
                    session.day_off();session.day_off()
                    event=read()['patron_dispatch']['events'][0];self.assertTrue(event['can_select'])
                    waiting=post('save_game')[1]['save_id'];funds=session.core.funds
                    code,result,command=post('receive_patron',cat_id='cat-sora',choice=event['choice']);self.assertEqual(code,200,result)
                    self.assertEqual(session.core.funds,funds+220);self.assertEqual(session.core.patron['satisfaction'],30)
                    self.assertEqual(session.core.activity('cat-sora'),'cafe');self.assertNotIn('cat-sora',session.core.working_cats)
                    self.assertEqual(post('receive_patron',command)[:2],(code,result))
                    self.assertEqual(post('receive_patron',cat_id='cat-sora',choice=event['choice'])[0],422)
                    resolved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=waiting)[0],200)
                    self.assertTrue(read()['patron_dispatch']['events'][0]['can_select'])
                    self.assertEqual(post('load_game',save_id=resolved)[0],200)
                    self.assertFalse(read()['patron_dispatch']['events'][0]['can_select']);self.assertEqual(session.core.patron['satisfaction'],30)
                    self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                finally:server.shutdown();thread.join()
