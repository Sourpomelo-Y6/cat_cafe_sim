import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.core.cafe_management import rules, waiting, is_over
from cat_cafe_sim.core.cafe_activities import waiting_events
from cat_cafe_sim.core.cafe_adoption import waiting as adoption_waiting
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relations.json')
        for key in ('a','b','c'):
            self.store.register_cat(key,key,Personality())
        self.path=Path(self.temp.name)/'cafe.json'

    def session(self,seats=2,**config):
        return CafeInteractionSession(store=self.store,seat_count=seats,
            cafe_config=replace(Config.load(),opening_ticks=2,arrival_ticks=(0,),**config),
            interaction_config=replace(RelationshipConfig(),ticks=1))

    def enable(self,s,**changes):
        selected=dict(rules(),runaway_threshold=2,return_stress=0,kitten_probability=0)
        selected.update(changes)
        s.enable_management(selected)

    def close(self,s):
        while not s.core.closed:
            s.automatic_step()

    def reload(self,s):
        save_game(s,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot())
        return loaded

    def rejected(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(before,s.core.log())

    def test_explicit_start_grants_once_and_old_saves_stay_unmodified(self):
        s=self.session()
        old=checkpoint(s.core,set())
        self.assertNotIn('management',old['state'])
        self.assertIsNone(restore(old).management)
        self.assertEqual(s.core.funds,0)
        self.enable(s)
        self.assertEqual(s.core.funds,1000)
        s=self.reload(s)
        self.rejected(s,lambda:s.enable_management())
        self.assertEqual(s.core.funds,1000)
        wealthy=self.session(initial_funds=1500)
        self.enable(wealthy)
        self.assertEqual(wealthy.core.funds,1500)
        self.assertEqual(wealthy.core.management['grant'],0)
        self.reload(wealthy)

    def test_enable_existing_profitable_save_on_later_day(self):
        s=self.session();self.close(s);s.next_day()
        self.assertEqual(s.core.funds,10)
        s=self.reload(s);self.enable(s)
        self.assertEqual(s.core.management['grant'],990)
        self.assertEqual(s.core.management['started_day'],2)
        self.assertEqual(s.core.funds,1000)
        self.assertNotIn('popularity',s.core.day_results[0]['summary'])
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_missing_two_days_return_resume_and_replay_both_seat_counts(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                s=self.session(seats);self.enable(s)
                self.close(s)
                self.assertEqual(s.core.activity('a'),'missing')
                self.assertEqual(s.core.management['popularity'],80)
                self.assertEqual(s.core.day_result()['cats']['a']['stress'],2)
                s=self.reload(s)
                s.next_day()
                self.assertNotIn('a',[c.id for c in s.available_cats()])
                self.rejected(s,lambda:s.set_shifts(['a']))
                self.rejected(s,lambda:s.play_with_player('a'))
                self.rejected(s,lambda:s.dispatch('a'))
                stamina=s.core.cats['a'].stamina
                s.day_off()
                self.assertEqual(s.core.management['events']['missing-1-a']['remaining'],1)
                self.assertEqual(s.core.cats['a'].stamina,stamina)
                s=self.reload(s);s.day_off()
                self.assertEqual(s.core.day,4)
                event=waiting(s.core)[0]
                self.assertEqual(event['remaining'],0)
                self.rejected(s,lambda:s.automatic_step())
                s=self.reload(s)
                funds=s.core.funds
                s.resolve_missing(event['id'])
                after=s.core.log();s.resolve_missing(event['id'])
                self.assertEqual(s.core.log(),after)
                self.assertEqual(s.core.funds,funds)
                self.assertEqual(s.core.activity('a'),'cafe')
                self.assertEqual(s.core.cats['a'].stamina,100)
                self.assertEqual(s.core.management['stress']['a'],0)
                s.set_shifts(['a'])
                self.assertIn('a',[c.id for c in s.available_cats()])
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
                self.reload(s)

    def test_stress_relief_by_rest_and_successful_player_set(self):
        s=self.session();self.enable(s,runaway_threshold=80)
        self.close(s);s.next_day()
        self.assertEqual(s.core.management['stress']['a'],2)
        s.play_with_player('a')
        s.player_command('direct');s.player_command(finish=True)
        self.assertEqual(s.core.management['stress']['a'],0)
        s.set_shifts(['a'])
        self.close(s);s.next_day()
        self.assertGreater(s.core.management['stress']['a'],0)
        s.day_off()
        self.assertEqual(s.core.management['stress']['a'],0)
        self.assertEqual(dict(cat_details(s,'a')['basic'])['ストレス'],'0 / 100')
        self.reload(s)

    def test_good_player_reactions_relieve_stress_even_at_max_affinity(self):
        s=self.session();self.enable(s,runaway_threshold=80)
        s.interaction_config=replace(s.interaction_config,affinity_favorable=100)
        s.play_with_player('a');s.player_command('direct');s.player_command(finish=True)
        self.assertEqual(s.core.player_bond['affinity']['a'],100)
        s.set_shifts(['a']);self.close(s);s.next_day()
        self.assertEqual(s.core.management['stress']['a'],2)
        s.play_with_player('a');s.player_command('direct');s.player_command(finish=True)
        self.assertEqual(s.core.player_bond['last']['summary']['affinity_delta'],0)
        self.assertEqual(s.core.management['stress']['a'],0)
        self.reload(s)

    def test_dispatch_and_adopted_cats_are_not_subject_to_daily_stress(self):
        s=self.session();self.enable(s)
        s.dispatch('c');self.close(s)
        self.assertEqual(s.core.management['stress']['c'],0)
        self.assertEqual(s.core.activity('c'),'dispatched')
        s.resolve_activity(waiting_events(s.core)[0]['id'])
        self.assertEqual(s.core.activity('c'),'cafe')
        self.reload(s)

    def test_pending_adoption_takes_priority_over_runaway(self):
        warm=self.store.begin(replace(RelationshipConfig(),ticks=1,affinity_favorable=80),'a','guest-1')
        warm.step('direct');self.store.apply(warm)
        s=self.session();self.enable(s);s.configure_adoption(True);self.close(s)
        self.assertTrue(adoption_waiting(s.core))
        self.assertEqual(s.core.activity('a'),'cafe')
        self.assertEqual(s.core.management['popularity'],100)
        s.resolve_adoption(adoption_waiting(s.core)[0]['id'],'accept')
        s.next_day();s.day_off()
        self.assertEqual(s.core.activity('a'),'adopted')
        self.assertEqual(s.core.management['stress']['a'],2)
        self.reload(s)

    def test_kitten_cost_is_only_money_and_zero_or_negative_funds_end_game(self):
        for cost in (1010,1100):
            with self.subTest(cost=cost):
                s=self.session();self.enable(s,kitten_probability=1,kitten_cost=cost)
                ids=set(s.core.cats)
                self.close(s);s.next_day();s.day_off();s.day_off()
                event=waiting(s.core)[0]
                self.assertTrue(event['kitten'])
                before=s.core.funds
                s=self.reload(s);s.resolve_missing(event['id'])
                self.assertEqual(s.core.funds,before-cost)
                self.assertLessEqual(s.core.funds,0)
                self.assertEqual(set(s.core.cats),ids)
                self.assertEqual(s.core.management['game_over'],dict(reason='funds',day=4))
                self.assertEqual(s.core.summary()['kitten_expenses'],cost)
                s=self.reload(s)
                for action in (lambda:s.automatic_step(),lambda:s.day_off(),lambda:s.next_day(),
                               lambda:s.play_with_player('b'),lambda:s.dispatch('b'),
                               lambda:s.resolve_missing(event['id']),lambda:s.configure_adoption(True),
                               lambda:s.core.player_command(finish=True)):
                    self.rejected(s,action)
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_popularity_game_over_stops_next_day_and_saves(self):
        s=self.session();self.enable(s,popularity_loss=100)
        self.close(s)
        self.assertTrue(is_over(s.core))
        self.assertEqual(s.core.management['game_over']['reason'],'popularity')
        self.assertEqual(s.core.day,1)
        self.rejected(s,lambda:s.next_day())
        s=self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertEqual(s.core.day_result()['summary']['popularity'],0)

    def test_pending_save_failure_and_return_save_retry_do_not_duplicate_cost(self):
        s=self.session();self.enable(s,kitten_probability=1,kitten_cost=100)
        s.automatic_step()
        with patch.object(self.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.automatic_step()
        self.assertTrue(s.pending)
        s=self.reload(s);s.persist();s.next_day();s.day_off();s.day_off()
        event=waiting(s.core)[0];s.resolve_missing(event['id'])
        before=s.core.log()
        with patch.object(RelationshipStore,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,self.path)
        self.assertEqual(s.core.log(),before)
        s=self.reload(s);s.resolve_missing(event['id'])
        self.assertEqual(s.core.log(),self.reload(s).core.log())
        self.assertEqual(s.core.funds,910)

    def test_game_over_prevents_pending_dispatch_and_adoption_from_changing_state(self):
        warm=self.store.begin(replace(RelationshipConfig(),ticks=1,affinity_favorable=80),'b','guest-2')
        warm.step('direct');self.store.apply(warm)
        s=CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),opening_ticks=2,arrival_ticks=(0,0)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        self.enable(s,popularity_loss=100)
        s.configure_adoption(True);s.dispatch('c')
        self.close(s)
        self.assertTrue(is_over(s.core))
        adoption=adoption_waiting(s.core)[0]['id']
        dispatch=s.core.activities['events']['dispatch-1-c']['id']
        self.rejected(s,lambda:s.resolve_adoption(adoption,'accept'))
        self.rejected(s,lambda:s.resolve_activity(dispatch))
        self.reload(s)

    def test_invalid_rules_and_checkpoint_are_rejected(self):
        s=self.session()
        self.rejected(s,lambda:s.enable_management(dict(rules(),missing_days=0)))
        self.enable(s);self.close(s)
        source=checkpoint(s.core,set())
        for field,value in (('popularity',100),('game_over',dict(reason='popularity',day=1)),
                            ('grant',-1)):
            bad=copy.deepcopy(source);bad['state']['management'][field]=value
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        for field,value in (('remaining',0),('kitten',True),('cost',250),('resolved_day',1)):
            bad=copy.deepcopy(source)
            bad['state']['management']['events']['missing-1-a'][field]=value
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
