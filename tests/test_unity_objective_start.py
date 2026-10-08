import copy
import unittest
from pathlib import Path
import test_cafe_popularity_challenge as fixtures
import test_cafe_goal as legacy_fixtures
from test_unity_dispatch_choices import api
from cat_cafe_sim.unity_state_server import state_view,objective_start_view


class UnityObjectiveStartTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PopularityChallengeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.root=Path(self.fixture.temp.name)

    def test_read_only_options_and_existing_modes(self):
        for mode in ('free','bond','patron','popularity'):
            s=self.fixture.game(mode);before=copy.deepcopy(s.core.snapshot());files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
            view=objective_start_view(s);self.assertEqual(view,objective_start_view(s));self.assertEqual(before,s.core.snapshot());self.assertEqual(files,{p:p.read_bytes() for p in files})
            rows={r['choice']:r for r in view['rows']}
            self.assertEqual(rows['popularity']['can_start'],mode!='popularity');self.assertEqual(rows['bond']['can_start'],mode!='bond');self.assertEqual(rows['patron']['can_start'],mode!='patron')
            self.assertIn('期限なし',rows['bond']['details'] if mode!='bond' else rows['patron']['details'])
            if mode!='popularity':self.assertIn('人気650（25日間）',rows['popularity']['details'])

    def test_http_all_starts_retry_progress_and_save_reload(self):
        for choice in ('popularity','bond','patron'):
            with self.subTest(choice=choice):
                s=self.fixture.game();files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
                with api(s,self.root/choice) as (read,post):
                    original=read();code,result,command=post('start_objective',choice=choice);self.assertEqual(code,200);after=result['state'];self.assertEqual(after['funds'],original['funds']);self.assertEqual(after['objective'],'free');self.assertEqual(after['cats'],original['cats'])
                    row=next(r for r in after['objective_start']['rows'] if r['choice']==choice);self.assertTrue(row['started']);self.assertFalse(row['can_start']);self.assertIn('開始日：1日目',row['details']);self.assertIn(row['details'].split('\n')[0],after['objective_progress']['details'])
                    self.assertEqual(post('start_objective',command)[0],200);self.assertEqual(read(),after);before=copy.deepcopy(s.core.snapshot());self.assertEqual(post('start_objective',choice=choice)[0],422);self.assertEqual(before,s.core.snapshot())
                    saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200);restored=read();self.assertEqual(restored['objective_start'],after['objective_start']);self.assertEqual(restored['objective_progress'],after['objective_progress'])
                self.assertEqual(files,{p:p.read_bytes() for p in files})

    def test_other_objectives_are_preserved_and_legacy(self):
        for mode in ('bond','patron'):
            s=self.fixture.game(mode);prior=copy.deepcopy(s.core.bond_goal if mode=='bond' else s.core.patron);funds=s.core.funds
            with api(s,self.root/mode) as (read,post):
                self.assertEqual(post('start_objective',choice='popularity')[0],200);self.assertEqual(prior,s.core.bond_goal if mode=='bond' else s.core.patron);self.assertEqual(funds,s.core.funds);self.assertIn('人気3段階',read()['objective_progress']['details']);self.assertEqual(s.core.goal['rules']['cap'],650)
        fixture=legacy_fixtures.CafeGoalTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=fixture.session()
        with api(s,self.root/'legacy') as (read,post):
            self.assertTrue(next(r for r in read()['objective_start']['rows'] if r['choice']=='popularity')['can_start']);self.assertEqual(post('start_objective',choice='popularity')[0],200);self.assertIn('stages',s.core.goal['rules'])

    def test_invalid_commands_preparation_and_pending_event(self):
        s=self.fixture.game()
        with api(s,self.root/'blocked') as (read,post):
            before=copy.deepcopy(s.core.snapshot())
            for fields,expected in [({},400),({'choice':'unknown'},400),({'choice':'bond','working_cats':['cat-mike']},422)]:
                self.assertEqual(post('start_objective',**fields)[0],expected);self.assertEqual(before,s.core.snapshot())
            self.assertEqual(post('start_business')[0],200);self.assertTrue(all(not r['can_start'] for r in read()['objective_start']['rows']));self.assertEqual(post('start_objective',choice='bond')[0],422)
        s=self.fixture.game();s.core.management=None
        self.assertTrue(all(not r['can_start'] for r in objective_start_view(s)['rows'] if r['choice']!='management'))
        from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
        selected=starting_conditions('free');selected['store_events']['probability']=0;s=create_game(self.root/'pending',selected)
        for _ in range(3):s.day_off()
        rows=objective_start_view(s)['rows'];self.assertTrue(all(not r['can_start'] for r in rows));self.assertTrue(any('受け入れ' in r['reason'] for r in rows))
