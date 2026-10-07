import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.unity_state_server import make_server,state_view


class UnityPlayerTests(unittest.TestCase):
    def test_interaction_retry_read_only_midway_save_result_and_bond_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=starting_conditions('bond');settings['bond']=dict(target=1,affinity=.5)
            session=create_game(Path(directory)/'source',settings)
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
                    cat='cat-mugi';before=session.core.snapshot();self.assertIsNone(read()['player_interaction']);self.assertEqual(session.core.snapshot(),before)
                    initial=next(r for r in read()['cats'] if r['cat_id']==cat);self.assertTrue(initial['can_player_start']);self.assertEqual(initial['remaining_sets'],3)
                    code,result,command=post('player_begin',cat_id=cat);self.assertEqual(code,200,result)
                    self.assertEqual(post('player_begin',command)[:2],(code,result));self.assertEqual(read()['player_interaction']['remaining_sets'],2)
                    for kind,extra in (('player_begin',dict(cat_id=cat)),('player_step',dict(cat_id='cat-tama',choice='direct')),('player_step',dict(cat_id=cat,choice='switch',target_type='missing')),('start_business',{})):
                        before=session.core.snapshot();self.assertEqual(post(kind,**extra)[0],422);self.assertEqual(session.core.snapshot(),before)
                    self.assertEqual(post('player_step',cat_id=cat,choice='direct',target_type='voice')[0],400)
                    reference=copy.deepcopy(session);reference.player_command('switch','voice')
                    code,result,command=post('player_step',cat_id=cat,choice='switch',target_type='voice');self.assertEqual(code,200,result)
                    self.assertEqual(session.core.snapshot(),reference.core.snapshot());self.assertEqual(post('player_step',command)[:2],(code,result))
                    before=session.core.snapshot();view=read()['player_interaction'];self.assertEqual(session.core.snapshot(),before)
                    self.assertGreaterEqual(view['stamina_before'], view['stamina']);self.assertEqual(view['mode'],'声をかける');self.assertIn('切り替える',view['history'])
                    midway=post('save_game')[1]['save_id']
                    self.assertEqual(post('player_step',cat_id=cat,choice='direct')[0],200)
                    self.assertEqual(post('load_game',save_id=midway)[0],200);self.assertEqual(read()['player_interaction'],view)
                    self.assertEqual(post('player_step',cat_id=cat,choice='switch',target_type='teaser')[0],200)
                    self.assertEqual(post('player_step',cat_id=cat,choice='direct')[0],200)
                    self.assertEqual(post('player_finish',cat_id=cat)[0],200)
                    final=read();player=final['player_interaction'];self.assertFalse(player['active']);self.assertFalse(player['can_finish'])
                    self.assertEqual(player['stamina_before'],view['stamina_before']);self.assertGreater(player['affinity_after'],0);self.assertTrue(all(not r['can_select'] for r in player['actions']))
                    self.assertEqual(final['tick'],0);self.assertEqual(final['funds'],1000)
                    self.assertEqual(final['goal_result']['kind'],'continue_bond_goal');self.assertIn('1 / 1匹',final['objective_progress']['summary'])
                    saved=post('save_game')[1]['save_id'];self.assertEqual(post('continue_bond_goal')[0],200)
                    self.assertEqual(post('load_game',save_id=saved)[0],200);self.assertEqual(read()['player_interaction'],player)
                    self.assertEqual(post('player_finish',cat_id=cat)[0],422)
                    self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                finally:server.shutdown();thread.join()

    def test_valid_actions_limits_and_health_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source',starting_conditions('free'))
            for _ in range(3):
                session.play_with_player('cat-mugi')
                interaction=state_view(session)['player_interaction'];self.assertFalse(next(a for a in interaction['actions'] if a['choice']=='connect')['can_select'])
                session.player_command('switch','presence')
                self.assertFalse(next(a for a in state_view(session)['player_interaction']['actions'] if a['choice']=='intense')['can_select'])
                session.player_command(finish=True)
            rows=state_view(session)['cats'];self.assertTrue(all(not r['can_player_start'] for r in rows));self.assertIn('使い切りました',rows[0]['player_reason'])
            session=create_game(Path(directory)/'second',starting_conditions('free'))
            session.core.cats['cat-mugi'].stamina=0
            row=next(r for r in state_view(session)['cats'] if r['cat_id']=='cat-mugi');self.assertFalse(row['can_player_start']);self.assertIn('体力切れ',row['player_reason'])
