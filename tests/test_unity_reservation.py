import copy
import json
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_cafe_reservation as reservation_tests
from cat_cafe_sim.unity_state_server import make_server,state_view

class UnityReservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=reservation_tests.ReservationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def test_read_only_projection_and_legacy(self):
        session=self.fixture.game();before=session.core.snapshot();row=state_view(session)['reservation']
        self.assertEqual(before,session.core.snapshot());self.assertEqual(row['status'],'untriggered');self.assertFalse(row['can_accept'])
        self.fixture.unlock(session);before=session.core.snapshot();row=state_view(session)['reservation']
        self.assertEqual(before,session.core.snapshot());self.assertTrue(row['can_accept']);self.assertTrue(row['can_decline'])
        self.assertEqual(row['visit_day'],session.core.day+1);self.assertEqual(row['bonus'],session.core.reservation['rules']['bonus'])
        session.core.reservation=None;self.assertIsNone(state_view(session)['reservation'])
    def test_http_choices_retries_save_and_next_day(self):
        for choice in ('accept','decline'):
            with self.subTest(choice=choice):
                session=self.fixture.unlock(self.fixture.game());originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir() if p.is_file()}
                with make_server(session,0,Path(self.fixture.temp.name)/uuid.uuid4().hex) as server:
                    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
                    def read():
                        with urlopen(base+'/state') as response:return json.load(response)
                    def post(kind='resolve_reservation',command=None,**extra):
                        state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                        try:
                            with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                        except HTTPError as ex:return ex.code,json.load(ex),command
                    try:
                        row=read()['reservation'];self.assertEqual(post('start_business')[0],422)
                        self.assertEqual(post(choice='wrong',event_id=row['event_id'])[0],400);self.assertEqual(post(choice=choice,event_id='wrong')[0],422)
                        waiting=post('save_game')[1]['save_id'];before_funds=session.core.funds;reference=copy.deepcopy(session);reference.resolve_reservation(choice)
                        code,result,command=post(choice=choice,event_id=row['event_id']);self.assertEqual(code,200,result);self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                        self.assertEqual(post(command=command)[:2],(code,result));self.assertEqual(session.core.funds,before_funds)
                        final=read()['reservation'];self.assertFalse(final['can_accept']);self.assertEqual(post(choice=choice,event_id=row['event_id'])[0],422)
                        resolved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=waiting)[0],200);self.assertEqual(read()['reservation'],row)
                        self.assertEqual(post('load_game',save_id=resolved)[0],200);self.assertEqual(read()['reservation'],final);self.assertEqual(post('start_business')[0],200)
                        self.assertEqual({p:p.read_bytes() for p in originals},originals)
                    finally:server.shutdown();thread.join(5)
