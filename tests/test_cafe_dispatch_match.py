import copy
import tempfile
import unittest
from pathlib import Path
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_dispatch_match import terms
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,restore,digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game,load_game

class DispatchMatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def game(self,mode='free'):
        selected=starting_conditions(mode);selected.pop('intake_request');selected['store_events']['probability']=0
        return create_game(Path(self.temp.name)/'games',selected)
    def test_feature_bonus_saved_and_replayed(self):
        s=self.game();s.dispatch('cat-sora')
        e=s.core.activities['events']['dispatch-1-cat-sora']
        self.assertEqual(e['welcome_match']['reward_bonus'],20)
        before=s.core.funds;s.day_off();s.resolve_activity(e['id'])
        self.assertEqual(s.core.funds,before-s.core.day_results[-1]['summary']['operating_cost']+120)
        funds=s.core.funds;s.resolve_activity(e['id']);self.assertEqual(s.core.funds,funds)
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot())
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        bad=checkpoint(s.core,set());bad['state']['activities']['events'][e['id']]['welcome_match']['reward_bonus']=100
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)
    def test_patron_feature_adds_satisfaction(self):
        s=self.game('patron');s.dispatch('cat-sora',s.core.patron['rules']['destination'])
        s.day_off();s.day_off();s.resolve_activity('dispatch-1-cat-sora')
        self.assertEqual(s.core.patron['satisfaction'],30)
        save_game(s,s.checkpoint_path);self.assertEqual(load_game(s.checkpoint_path)[0].core.snapshot(),s.core.snapshot())
    def test_legacy_destination_keeps_original_reward(self):
        s=self.game();from cat_cafe_sim.core.cafe_activities import destination,reward
        rule=destination();rule.pop('welcome');s.core.dispatch('cat-sora',rule)
        event=s.core.activities['events']['dispatch-1-cat-sora']
        self.assertNotIn('welcome_match',event);self.assertEqual(reward(s.core,event),100)
