import copy
import json
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_cafe_customer_trust as trust_tests
from cat_cafe_sim.unity_state_server import make_server,state_view

class UnityCustomerTrustTests(unittest.TestCase):
    def test_read_only_projection_and_legacy(self):
        fixture=trust_tests.CustomerTrustTests();fixture.setUp()
        try:
            fixture.warning();session=fixture.s;before=session.core.snapshot();view=state_view(session)['customer_trust']
            self.assertEqual(before,session.core.snapshot());self.assertTrue(view['events'][0]['can_respond']);self.assertTrue(view['events'][0]['name'])
            session.core.customer_trust=None;self.assertIsNone(state_view(session)['customer_trust'])
        finally:fixture.doCleanups()
    def test_http_choices_popularity_and_save_restore(self):
        for choice in ('recover','ignore'):
            with self.subTest(choice=choice):
                fixture=trust_tests.CustomerTrustTests();fixture.setUp()
                try:
                    event=fixture.warning();session=fixture.s
                    with make_server(session,0,Path(fixture.temp.name)/'saves') as server:
                        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
                        def read():
                            with urlopen(base+'/state') as response:return json.load(response)
                        def post(kind='resolve_customer_trust',command=None,**extra):
                            state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                            try:
                                with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                            except HTTPError as ex:return ex.code,json.load(ex),command
                        try:
                            row=read()['customer_trust'];waiting=post('save_game')[1]['save_id'];before=session.core.management['popularity'];funds=session.core.funds
                            self.assertEqual(post('start_business')[0],422);self.assertEqual(post(choice='wrong',event_id=event['id'])[0],400);self.assertEqual(post(choice=choice,event_id='wrong')[0],422)
                            reference=copy.deepcopy(session);reference.resolve_customer_trust(event['id'],choice)
                            code,result,command=post(choice=choice,event_id=event['id']);self.assertEqual(code,200,result);self.assertEqual(session.core.snapshot(),reference.core.snapshot());self.assertEqual(post(command=command)[:2],(code,result))
                            self.assertEqual(session.core.funds,funds);self.assertEqual(session.core.management['popularity'],before-(row['popularity_loss'] if choice=='ignore' else 0))
                            final=read()['customer_trust'];self.assertFalse(final['events'][0]['can_respond']);self.assertEqual(post(choice=choice,event_id=event['id'])[0],422)
                            resolved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=waiting)[0],200);self.assertEqual(read()['customer_trust'],row)
                            self.assertEqual(post('load_game',save_id=resolved)[0],200);self.assertEqual(read()['customer_trust'],final);self.assertEqual(post('start_business')[0],200)
                        finally:server.shutdown();thread.join(5)
                finally:fixture.doCleanups()
