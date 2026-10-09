import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_operating_cost import rules as operating_rules
from cat_cafe_sim.storage.cafe_saves import load_game
from cat_cafe_sim import unity_autoplay
from cat_cafe_sim.unity_state_server import state_view
from test_unity_dispatch_choices import api
import test_cafe_autoplay as fixtures


class UnityAutoPlayTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AutoPlayTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.fixture.temp.name)

    def session(self,name='game',**kwargs):return self.fixture.session(name,days=kwargs.pop('days',20),target=kwargs.pop('target',200),stages=kwargs.pop('stages',False),**kwargs)

    def begin(self,post,objective='popularity',mode='basic',days=1):return post('start_autoplay',autoplay_objective=objective,autoplay_mode=mode,autoplay_days=days)

    def finish(self,read,post):
        for _ in range(150):
            if not read()['autoplay']['running']:return read()['autoplay']['report']
            code,data,_=post('step_autoplay');self.assertEqual(code,200,data)
        self.fail('Auto play did not stop')

    def test_projection_validation_and_start_are_read_only(self):
        s=self.session();before=copy.deepcopy(s.core.snapshot());view=state_view(s)['autoplay']
        self.assertTrue(view['can_start']);self.assertEqual([r['choice'] for r in view['modes']],['basic','clear','fast']);self.assertEqual(before,s.core.snapshot())
        with api(s,self.root/'saves') as (read,post):
            before=read()
            for days in (True,0,11,'2'):
                self.assertEqual(self.begin(post,days=days)[0],400);self.assertEqual(before,read())
            self.assertEqual(self.begin(post,mode='unknown')[0],400);self.assertEqual(before,read())
            self.assertEqual(self.begin(post,objective='bond')[0],422);self.assertEqual(before,read())
            core=copy.deepcopy(s.core.snapshot());code,data,command=self.begin(post,days=10);self.assertEqual(code,200,data);self.assertEqual(core,s.core.snapshot())
            started=read();self.assertEqual(post('start_autoplay',command=command)[:2],(code,data));self.assertEqual(started,read())
            for kind in ('save_game','start_business','new_game','set_auto_assignment'):
                extra=dict(choice='free' if kind=='new_game' else 'manual') if kind in ('new_game','set_auto_assignment') else {}
                self.assertEqual(post(kind,**extra)[0],422);self.assertEqual(started,read())
            self.assertEqual(post('stop_autoplay')[0],200)
        free=create_game(self.root/'free',starting_conditions('free'));self.assertFalse(state_view(free)['autoplay']['can_start'])

    def test_all_policies_match_python_operations_results_and_retry(self):
        for mode in ('basic','clear','fast'):
            with self.subTest(mode=mode):
                s=self.session(mode);originals={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()}
                with api(s,self.root/f'saves-{mode}') as (read,post):
                    ref=copy.deepcopy(s);player=AutoPlayer(ref,mode=mode,max_days=2,stop_on_goal=True)
                    api_ids=iter(uuid.UUID(int=i) for i in range(1,1000));ref_ids=iter(uuid.UUID(int=i) for i in range(1,1000))
                    self.assertEqual(self.begin(post,mode=mode,days=2)[0],200)
                    for _ in range(50):
                        if not read()['autoplay']['running']:break
                        with patch('cat_cafe_sim.core.human_cat_relationship.uuid4',side_effect=lambda:next(api_ids)):
                            code,data,command=post('step_autoplay')
                        self.assertEqual(code,200,data);count=read()['autoplay']['report']['operations']
                        with patch('cat_cafe_sim.core.human_cat_relationship.uuid4',side_effect=lambda:next(ref_ids)):
                            while player.operations<count:self.assertTrue(player.step())
                        self.assertEqual(s.core.snapshot(),ref.core.snapshot())
                        snapshot=read();self.assertEqual(post('step_autoplay',command=command)[:2],(code,data));self.assertEqual(read(),snapshot)
                    report=read()['autoplay']['report'];self.assertFalse(report['running']);self.assertEqual(report['reason'],'day_limit');self.assertEqual(report['days'],2)
                    self.assertFalse(player.step());self.assertEqual(report['operations'],player.result.operations);self.assertTrue(report['decisions']);self.assertIn('資金',report['summary'])
                self.assertEqual(originals,{p:p.read_bytes() for p in originals})

    def test_event_wait_stops_before_answer_and_returns_normal_operations(self):
        settings=starting_conditions('popularity');settings['intake_request']['day']=2
        for key in ('store_events','dispatch_unlocks'):settings.pop(key,None)
        s=create_game(self.root/'event',settings)
        with api(s,self.root/'event-saves') as (read,post):
            self.assertEqual(self.begin(post,days=10)[0],200);report=self.finish(read,post)
            self.assertEqual(report['reason'],'blocked');self.assertIn('受け入れ',report['message']);self.assertEqual(s.core.day,2);self.assertEqual(read()['intake_request']['status'],'waiting')
            before=read();self.assertEqual(self.begin(post)[0],422);self.assertEqual(read(),before)
            self.assertEqual(post('resolve_intake',choice='decline')[0],200);self.assertEqual(self.begin(post)[0],200);self.assertEqual(post('stop_autoplay')[0],200)

    def test_goal_expiry_and_game_over_stop_without_continuing(self):
        for kind in ('goal','expired','game_over'):
            with self.subTest(kind=kind):
                s=self.session(kind,target=105 if kind=='goal' else 200,days=1 if kind=='expired' else 20,stages=kind=='goal',funds=1 if kind=='game_over' else 1000)
                if kind=='game_over':s.core.initialize_operating_cost(dict(operating_rules(),base_cost=100000))
                with api(s,self.root/f'saves-{kind}') as (read,post):
                    self.assertEqual(self.begin(post,days=10)[0],200);report=self.finish(read,post)
                    self.assertEqual(report['reason'],dict(goal='goal_cleared',expired='expired',game_over='game_over')[kind]);self.assertEqual(report['days'],1)
                    self.assertFalse(read()['autoplay']['running']);self.assertEqual(len(s.core.goal.get('history',[])),0)

    def test_cancel_save_load_restores_report_manual_mode_and_rejects_corrupt_report(self):
        s=self.session();saves=self.root/'cancel-saves'
        with api(s,saves) as (read,post):
            self.assertEqual(post('set_auto_assignment',choice='manual')[0],200);self.assertEqual(self.begin(post,days=10)[0],200);self.assertTrue(read()['service_assignment']['auto_assign'])
            self.assertEqual(post('step_autoplay')[0],200);before=copy.deepcopy(s.core.snapshot());code,data,command=post('stop_autoplay');self.assertEqual(code,200,data);self.assertEqual(before,s.core.snapshot())
            report=read()['autoplay']['report'];self.assertEqual(report['reason'],'cancelled');self.assertFalse(read()['service_assignment']['auto_assign'])
            stopped=read();self.assertEqual(post('stop_autoplay',command=command)[:2],(code,data));self.assertEqual(read(),stopped);self.assertEqual(post('step_autoplay')[0],422)
            saved=post('save_game')[1]['save_id'];self.assertTrue((saves/saved/'autoplay.json').exists());snapshot=copy.deepcopy(s.core.snapshot())
            self.assertEqual(post('set_auto_assignment',choice='automatic')[0],200);self.assertEqual(post('load_game',save_id=saved)[0],200)
            self.assertEqual(read()['autoplay']['report'],report);self.assertEqual(s.core.snapshot(),snapshot);self.assertFalse(read()['service_assignment']['auto_assign'])
            restarted,flag=load_game(saves/saved/'cafe.json');restored=unity_autoplay.load_report(saves/saved/'autoplay.json');self.assertFalse(flag);self.assertEqual(state_view(restarted,auto_assign=flag,autoplay_run=restored)['autoplay']['report'],report)
            path=saves/saved/'autoplay.json';data=json.loads(path.read_text(encoding='utf-8'));data['mode']=[];path.write_text(json.dumps(data),encoding='utf-8');before=read();self.assertEqual(post('load_game',save_id=saved)[0],422);self.assertEqual(read(),before)
            self.assertEqual(post('new_game',choice='popularity')[0],200);self.assertIsNone(read()['autoplay']['report'])

    def test_bond_policy_can_continue_its_own_player_exchange(self):
        settings=starting_conditions('bond')
        for key in ('intake_request','store_events','dispatch_unlocks'):settings.pop(key,None)
        s=create_game(self.root/'bond',settings)
        with api(s,self.root/'bond-saves') as (read,post):
            self.assertEqual(self.begin(post,objective='bond',mode='clear',days=1)[0],200)
            for _ in range(3):
                self.assertEqual(post('step_autoplay')[0],200)
                if read()['player_interaction']['active']:break
            self.assertTrue(read()['player_interaction']['active']);count=read()['autoplay']['report']['operations']
            self.assertEqual(post('step_autoplay')[0],200);self.assertGreater(read()['autoplay']['report']['operations'],count)
            self.assertEqual(post('stop_autoplay')[0],200)


if __name__=='__main__':unittest.main()
