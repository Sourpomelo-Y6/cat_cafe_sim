import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import make_server, state_view


class UnityGoalStagesTests(unittest.TestCase):
    def test_three_stages_retry_blockers_save_restore_and_final_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=starting_conditions()
            for key in ('intake_request', 'reservation', 'growth', 'regular_introduction', 'visiting_cat'):
                settings.pop(key)
            settings['store_events']['probability']=0
            settings['goal'].update(target=105, days=10, stages=[dict(target=110,days=12),dict(target=115,days=14)])
            session=create_game(Path(directory)/'source',settings)
            while not session.core.closed: session.automatic_step()
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base+'/state') as response:return json.load(response)
                def post(kind,command=None,**extra):
                    state=read()
                    command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                    try:
                        with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                    except HTTPError as ex:return ex.code,json.load(ex),command
                try:
                    for stage,target,days in ((2,110,12),(3,115,14)):
                        before=copy.deepcopy(session.core.snapshot());state=read();next_goal=state['next_goal']
                        self.assertEqual(session.core.snapshot(),before)
                        self.assertEqual((next_goal['stage'],next_goal['target'],next_goal['days']),(stage,target,days))
                        self.assertEqual(next_goal['started_day'],stage)
                        self.assertEqual(next_goal['deadline'],stage+days-1)
                        self.assertTrue(next_goal['can_advance'])
                        if stage==2:
                            with patch.object(type(session),'advance_goal',side_effect=ValueError('先に帰還イベントを確認してください。')):
                                blocked=read()['next_goal'];self.assertFalse(blocked['can_advance']);self.assertIn('帰還',blocked['reason'])
                                self.assertEqual(post('advance_goal')[0],422)
                            self.assertEqual(session.core.snapshot(),before)
                            self.assertEqual(post('continue_goal')[0],200)
                            self.assertIsNone(read()['goal_result']);self.assertEqual(read()['next_goal'],next_goal)
                        pending_save=post('save_game')[1]['save_id']
                        reference=copy.deepcopy(session);reference.advance_goal()
                        code,result,command=post('advance_goal');self.assertEqual(code,200,result)
                        self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                        self.assertEqual((read()['funds'],read()['goal_result'],read()['next_goal']),(state['funds'],None,None))
                        self.assertEqual(post('advance_goal',command)[:2],(code,result))
                        advanced=copy.deepcopy(session.core.snapshot())
                        self.assertEqual(post('advance_goal')[0],422)
                        self.assertEqual(session.core.snapshot(),advanced)
                        active_save=post('save_game')[1]['save_id']
                        self.assertEqual(post('load_game',save_id=pending_save)[0],200)
                        self.assertEqual(read()['next_goal'],next_goal)
                        self.assertEqual(post('load_game',save_id=active_save)[0],200)
                        self.assertEqual(session.core.snapshot(),advanced)
                        self.assertEqual(post('next_day')[0],200)
                        self.assertEqual(post('start_business')[0],200)
                        while not read()['closed']:
                            code,result,_=post('advance_business');self.assertEqual(code,200,result)
                        self.assertEqual(read()['goal_result']['status'],'cleared')
                    self.assertIsNone(read()['next_goal'])
                    self.assertIn('クリア時の成果',read()['goal_result']['details'])
                    final=post('save_game')[1]['save_id']
                    self.assertEqual(post('continue_goal')[0],200)
                    self.assertIsNone(read()['goal_result']);self.assertIsNone(read()['next_goal'])
                    self.assertEqual(post('load_game',save_id=final)[0],200)
                    self.assertIn('クリア時の成果',read()['goal_result']['details'])
                    self.assertEqual(post('advance_goal')[0],422)
                finally:server.shutdown();thread.join()

    def test_active_expired_and_other_modes_offer_no_next_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('popularity','patron','bond','free'):
                settings=starting_conditions(mode)
                if mode=='popularity':settings['goal'].update(days=1,target=600,stages=[dict(days=10,target=625),dict(days=10,target=650)])
                session=create_game(Path(directory)/mode,settings)
                self.assertIsNone(state_view(session)['next_goal'])
                if mode=='popularity':
                    session.day_off()
                    self.assertEqual(state_view(session)['goal_result']['status'],'expired')
                    self.assertIsNone(state_view(session)['next_goal'])
