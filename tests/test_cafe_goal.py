import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_goal_gui import progress
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.core.cafe_goal import rules, pending
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CafeGoalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relationships.json')
        for key in ('a','b','c'):self.store.register_cat(key,key,Personality())
        self.path=Path(self.temp.name)/'game.json'

    def session(self,seats=2,**management):
        s=CafeInteractionSession(store=self.store,seat_count=seats,
            cafe_config=replace(Config.load(),opening_ticks=2,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        s.enable_management(dict(management_rules(),**management))
        return s

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def reload(self,s):
        save_game(s,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot())
        return loaded

    def rejected(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(before,s.core.log())

    def test_clear_save_continue_and_cap_both_seats(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                s=self.session(seats,stress_per_service_tick=0)
                s.enable_goal(dict(rules(),gain_per_success=55,cap=160))
                self.close(s)
                self.assertEqual(s.core.management['popularity'],155)
                self.assertEqual(s.core.goal['status'],'cleared')
                self.assertTrue(pending(s.core))
                self.assertEqual(s.core.summary()['popularity_gain'],55)
                self.rejected(s,lambda:s.next_day())
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
                s=self.reload(s);s.continue_goal();s.next_day();self.close(s)
                self.assertEqual(s.core.management['popularity'],160)
                self.assertEqual(s.core.goal['days'][-1]['gain'],5)
                self.assertEqual(s.core.goal['resolved_day'],1)
                self.assertFalse(pending(s.core))
                self.rejected(s,lambda:s.continue_goal())
                self.reload(s)

    def test_late_enable_old_save_and_expiry_counts_days_off(self):
        s=self.session();self.close(s);s.next_day()
        s=self.reload(s)
        self.assertIsNone(s.core.goal)
        self.assertEqual(s.core.management['popularity'],100)
        s.enable_goal(dict(rules(),days=2))
        self.assertIn('3日目まで',progress(s.core))
        s.play_with_player('a');s.player_command('direct');s.player_command(finish=True)
        s.day_off()
        self.assertEqual(s.core.goal['days'][0]['gain'],0)
        self.assertEqual(s.core.goal['status'],'active')
        s=self.reload(s);s.day_off()
        self.assertEqual(s.core.day,4)
        self.assertEqual(s.core.goal['status'],'expired')
        self.assertEqual(s.core.goal['resolved_day'],3)
        self.assertIn('残り0日',progress(s.core))
        self.rejected(s,lambda:s.automatic_step())
        s=self.reload(s);s.continue_goal();s.day_off()
        self.assertEqual(s.core.management['popularity'],100)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_deadline_closing_inclusive_and_later_growth_does_not_reclear_expired_goal(self):
        s=self.session(stress_per_service_tick=0);s.enable_goal(dict(rules(),days=2,target=105))
        s.day_off();self.close(s)
        self.assertEqual(s.core.goal['status'],'cleared')
        self.assertEqual(s.core.goal['resolved_day'],2)
        self.reload(s)
        s=self.session(stress_per_service_tick=0);s.enable_goal(dict(rules(),days=1,target=105))
        s.day_off();s.continue_goal();self.close(s)
        self.assertEqual(s.core.management['popularity'],105)
        self.assertEqual(s.core.goal['status'],'expired')
        self.reload(s)

    def test_max_affinity_still_earns_but_no_action_does_not(self):
        warm=self.store.begin(replace(RelationshipConfig(),ticks=1,affinity_favorable=100),'a','guest-1')
        warm.step('direct');self.store.apply(warm)
        s=self.session();s.enable_goal();self.close(s)
        self.assertEqual(s.core.goal['days'][0]['qualified'],1)
        self.assertEqual(s.core.management['popularity'],105)
        s=self.session();s.enable_goal();s.automatic_step();s.start('guest-1','a');s.finish();self.close(s)
        self.assertEqual(s.core.goal['days'][0]['qualified'],0)
        self.assertEqual(s.core.management['popularity'],100)
        self.reload(s)

    def test_runaway_loss_before_goal_and_game_over_priority(self):
        for loss,expected in ((60,145),(300,0)):
            s=self.session(runaway_threshold=1,return_stress=0,popularity_loss=loss)
            s.enable_goal(dict(rules(),gain_per_success=105))
            self.close(s)
            self.assertEqual(s.core.management['popularity'],expected)
            self.assertEqual(s.core.goal['status'],'active')
            if loss==300:
                self.assertEqual(s.core.management['game_over']['reason'],'popularity')
                self.assertFalse(pending(s.core))
                self.rejected(s,lambda:s.continue_goal())
            self.reload(s)

    def test_return_events_must_be_resolved_before_continue(self):
        s=self.session();s.enable_goal(dict(rules(),target=105));s.dispatch('c');self.close(s)
        self.assertEqual(s.core.goal['status'],'cleared')
        self.rejected(s,lambda:s.continue_goal())
        s=self.reload(s);s.resolve_activity('dispatch-1-c');s.continue_goal();s.next_day()
        self.reload(s)

    def test_save_failure_then_retry_does_not_duplicate_gain(self):
        s=self.session();s.enable_goal(dict(rules(),target=105));s.automatic_step()
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.automatic_step()
        self.assertEqual(s.core.management['popularity'],105)
        self.rejected(s,lambda:s.continue_goal())
        s=self.reload(s);s.persist();s.continue_goal()
        self.assertEqual(s.core.management['popularity'],105)
        s=self.reload(s)
        self.assertEqual(s.core.goal['days'],[dict(day=1,qualified=1,gain=5)])

    def test_clear_does_not_prevent_later_return_cost_game_over(self):
        from cat_cafe_sim.core.cafe_management import waiting
        s=self.session(runaway_threshold=1,return_stress=0,kitten_probability=1,kitten_cost=2000)
        s.enable_goal(dict(rules(),target=105,gain_per_success=25))
        self.close(s)
        self.assertEqual(s.core.goal['status'],'cleared')
        s.continue_goal();s.next_day();s.day_off();s.day_off()
        s.resolve_missing(waiting(s.core)[0]['id'])
        self.assertEqual(s.core.management['game_over']['reason'],'funds')
        self.assertEqual(s.core.goal['status'],'cleared')
        self.rejected(s,lambda:s.day_off())
        self.reload(s)

    def test_enable_guards_and_corrupt_checkpoint(self):
        s=self.session();self.rejected(s,lambda:s.enable_goal(dict(rules(),days=0)))
        s.enable_goal();self.rejected(s,lambda:s.enable_goal());self.close(s)
        source=checkpoint(s.core,set())
        for update in (lambda g:g.update(status='cleared',resolved_day=1),lambda g:g.update(continued=True),
                       lambda g:g['days'][0].update(gain=10),lambda g:g['days'][0].update(qualified=2),
                       lambda g:g.update(started_day=2)):
            bad=copy.deepcopy(source);update(bad['state']['goal'])
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
