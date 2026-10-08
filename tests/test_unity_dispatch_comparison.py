import copy
import tempfile
import unittest
from pathlib import Path
import test_cafe_management as legacy
from test_unity_dispatch_choices import api
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_activities import reward,destinations
from cat_cafe_sim.core.cafe_growth import pending
from cat_cafe_sim.storage.cafe_saves import save_game
from cat_cafe_sim.unity_state_server import state_view,dispatch_comparison_view


class UnityDispatchComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def game(self,mode='free',growth=False):
        selected=starting_conditions(mode);selected.pop('intake_request');selected['store_events']['probability']=0
        if growth:selected['growth']['threshold']=1
        return create_game(self.root/mode,selected)
    def test_all_modes_read_only_complete_catalog_and_current_options_agree(self):
        for mode in ('free','patron','bond','popularity'):
            s=self.game(mode);before=s.core.snapshot();files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()};view=state_view(s);comparison=view['dispatch_comparison'];self.assertEqual(comparison,dispatch_comparison_view(s));self.assertEqual(before,s.core.snapshot());self.assertEqual(files,{p:p.read_bytes() for p in files});self.assertEqual(len(comparison['cats']),len(s.core.cats))
            expected={(kind,o['cat_id'],o['choice']):o for kind in ('general','patron') for o in view[kind+'_dispatch']['options']}
            actual={(r['kind'],cat['cat_id'],r['choice']):r for cat in comparison['cats'] for r in cat['rows']};self.assertEqual(set(actual),set(expected))
            for key,row in actual.items():
                reference=expected[key];self.assertEqual((row['reward'],row['days'],row['can_select'],row['reason']),(reference['reward'],reference['days'],reference['can_select'],reference['reason']));self.assertEqual(row['cost'],0);self.assertAlmostEqual(row['base_reward']*row['trait_multiplier']*row['growth_multiplier']+row['welcome_bonus'],row['reward']);self.assertIn(reference['detail'],row['details']);self.assertEqual(row['satisfaction'],reference.get('satisfaction',0))
            first=comparison['cats'][0]['rows'];self.assertTrue(any('未解放' in r['unlock'] for r in first));self.assertTrue(any(r['choice']=='cat_exercise_class' for r in first));self.assertTrue(any(r['choice']=='mountain_lodge_visit' for r in first));self.assertEqual(any(r['kind']=='patron' for r in first),mode=='patron')
    def test_trait_growth_welcome_actual_dispatch_retry_and_save_restore(self):
        s=self.game('patron',growth=True);cat_id=next(k for k,r in s.core.traits.items() if r['dispatch_reward']!=1);s.day_off()
        for key in list(pending(s.core)):s.resolve_growth(key,'dispatch' if key==cat_id else 'service')
        save_game(s,s.checkpoint_path);files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
        with api(s,self.root/'unity') as (read,post):
            row=next(r for cat in read()['dispatch_comparison']['cats'] if cat['cat_id']==cat_id for r in cat['rows'] if r['choice']=='neighborhood_visit');self.assertTrue(row['can_select']);self.assertGreater(row['trait_multiplier'],1);self.assertGreater(row['growth_multiplier'],1)
            before=s.core.funds;code,result,command=post('dispatch_general',cat_id=cat_id,choice=row['choice']);self.assertEqual(code,200,result);event=next(reversed(s.core.activities['events'].values()));self.assertAlmostEqual(row['reward'],reward(s.core,event));self.assertEqual(before,s.core.funds);self.assertEqual(post('dispatch_general',command)[:2],(code,result));after=read()['dispatch_comparison'];self.assertEqual(after,read()['dispatch_comparison']);cat=next(c for c in after['cats'] if c['cat_id']==cat_id);self.assertEqual(cat['status'],'派遣中');self.assertTrue(all(not r['can_select'] for r in cat['rows']))
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200);self.assertEqual(after,read()['dispatch_comparison'])
        self.assertEqual(files,{p:p.read_bytes() for p in files})
    def test_legacy_no_special_settings_and_business_restrictions(self):
        fixture=legacy.ManagementTests();fixture.setUp();self.addCleanup(fixture.doCleanups);s=fixture.session();before=copy.deepcopy(s.core.snapshot());view=dispatch_comparison_view(s);self.assertEqual(before,s.core.snapshot());self.assertEqual(len(view['cats'][0]['rows']),len(destinations(s.core)));self.assertTrue(all(r['trait_multiplier']==1 and r['growth_multiplier']==1 for r in view['cats'][0]['rows']));self.assertFalse(any(r['choice']=='cat_exercise_class' for r in view['cats'][0]['rows']))
        s=self.game()
        with api(s,self.root/'open') as (read,post):
            self.assertEqual(post('start_business')[0],200);before=copy.deepcopy(s.core.snapshot());rows=[r for c in read()['dispatch_comparison']['cats'] for r in c['rows']];self.assertTrue(all(not r['can_select'] for r in rows));self.assertTrue(all(r['reason'] for r in rows));self.assertEqual(before,s.core.snapshot())


if __name__=='__main__':unittest.main()
