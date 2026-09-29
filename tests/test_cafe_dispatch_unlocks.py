import copy
import unittest
from tests import test_cafe_dispatch_match as matching
from cat_cafe_sim.core.cafe_dispatch_unlocks import reason,description
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,restore,digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game,load_game
from cat_cafe_sim.cafe_new_game import starting_conditions,create_game
from pathlib import Path

class DispatchUnlockTests(unittest.TestCase):
    setUp=matching.DispatchMatchTests.setUp
    def game(self,legacy=False):
        selected=starting_conditions('free');selected.pop('intake_request');selected['store_events']['probability']=0
        if legacy:selected.pop('dispatch_unlocks')
        else:selected['dispatch_unlocks']={'shopping_street_event':dict(popularity=100,returns=1),'out_of_town_visit':dict(popularity=100,returns=2)}
        return create_game(Path(self.temp.name)/'games',selected)
    def test_unlock_progress_save_replay_and_popularity_drop(self):
        s=self.game();self.assertIn('0/1',reason(s.core,'shopping_street_event'))
        from cat_cafe_sim.core.cafe_activities import destinations
        before=s.core.log()
        with self.assertRaisesRegex(ValueError,'未解放'):s.dispatch('cat-mike',destinations()[1])
        self.assertEqual(s.core.log(),before)
        for key in ('cat-sora','cat-kohaku'):
            s.dispatch(key);s.day_off();s.resolve_activity(f'dispatch-{s.core.day-1}-{key}')
        self.assertEqual(set(s.core.dispatch_unlocks['unlocked']),{'shopping_street_event','out_of_town_visit'})
        saved=s.core.log();self.assertEqual(verify_cafe_interaction(saved).snapshot(),s.core.snapshot())
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot())
        lowered=copy.deepcopy(s.core);lowered.management['popularity']=1
        self.assertEqual(reason(lowered,'out_of_town_visit'),'')
        bad=checkpoint(s.core,set());bad['state']['dispatch_unlocks']['unlocked']['out_of_town_visit']['returns']=0
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)
        missing=checkpoint(s.core,set());missing['state']['dispatch_unlocks']['unlocked'].clear()
        missing['digest']=digest({k:v for k,v in missing.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(missing)
    def test_legacy_remains_available_and_patron_is_not_locked(self):
        s=self.game(legacy=True);self.assertEqual(reason(s.core,'out_of_town_visit'),'')
        save_game(s,s.checkpoint_path);self.assertIsNone(load_game(s.checkpoint_path)[0].core.dispatch_unlocks)
        self.assertEqual(reason(self.game().core,'patron_visit'),'')
