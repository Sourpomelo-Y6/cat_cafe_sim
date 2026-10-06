import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import make_server
class UnityNewGameTests(unittest.TestCase):
    def test_modes_retry_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source')
            originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def read(path='/state'):
                    with urlopen(base+path) as response:return json.load(response)
                def post(kind,command=None,**extra):
                    state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                    try:
                        with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                    except HTTPError as ex:return ex.code,json.load(ex),command
                try:
                    before=session.core.snapshot();state=read()
                    self.assertEqual(before,session.core.snapshot());self.assertEqual(len(state['new_game_options']),4)
                    self.assertEqual(post('new_game',choice='invalid')[0],400);self.assertEqual(read(),state)
                    saved=post('save_game')[1]['save_id']
                    for mode in ('popularity','patron','bond','free'):
                        code,result,command=post('new_game',choice=mode);self.assertEqual(code,200,result)
                        state=read();self.assertEqual(state['objective'],mode);self.assertEqual(state['day'],1);self.assertEqual(state['tick'],0)
                        self.assertFalse(state['closed']);self.assertEqual(state['funds'],1000);self.assertEqual(len(state['cats']),5)
                        self.assertEqual(post('new_game',command=command)[:2],(code,result));self.assertEqual(read(),state)
                        self.assertEqual(post('start_business')[0],200)
                        self.assertEqual(post('advance_business')[0],200)
                        self.assertEqual(post('load_game',save_id=result['save_id'])[0],200);self.assertEqual(read()['objective'],mode)
                        self.assertEqual(read()['tick'],0)
                    self.assertEqual(len(read('/saves')['saves']),5)
                    self.assertEqual(post('load_game',save_id=saved)[0],200)
                    self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                finally:server.shutdown();thread.join()
