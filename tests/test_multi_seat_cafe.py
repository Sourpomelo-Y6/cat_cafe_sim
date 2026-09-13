import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats


class MultiSeatTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=RelationshipStore(Path(directory.name)/'relations.json')
        for key in ('cat-a','cat-b','cat-c'):
            self.store.register_cat(key,key,Personality())

    def session(self, ticks=20, opening=40, **rules):
        return CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),opening_ticks=opening,arrival_ticks=(0,0,1)),
            interaction_config=replace(RelationshipConfig(),ticks=ticks,**rules))

    def assigned(self, session):
        session.step()
        session.start('guest-1','cat-a','seat-1')
        session.start('guest-2','cat-b','seat-2')

    def test_two_seats_share_one_clock_and_preserve_third_cat(self):
        session=self.session();self.assigned(session)
        session.automatic_step()
        self.assertEqual(session.core.tick,2)
        self.assertEqual([len(s.records) for s in session.active_interactions.values()],[1,1])
        self.assertEqual(session.core.summary()['cat_stamina'],{'cat-a':95,'cat-b':95,'cat-c':100})
        self.assertEqual(session.core.service_ticks,2)
        self.assertEqual(session.core.queue,['guest-3'])
        self.assertEqual(session.core.seats['seat-2'].customer_id,'guest-2')
        self.assertEqual(session.core.visits['guest-2'].seated_at,1)
        self.assertFalse(any(e['kind']=='invalid_command' for e in session.core.events))

    def test_duplicate_cat_customer_seat_and_invalid_commands_do_not_mutate(self):
        session=self.session();session.step();session.start('guest-1','cat-a','seat-1')
        for guest,cat,seat in [('guest-2','cat-a','seat-2'),('guest-1','cat-b','seat-2'),('guest-2','cat-b','seat-1'),('guest-2','cat-b','bad')]:
            before=session.core.log()
            with self.assertRaises(ValueError):session.start(guest,cat,seat)
            self.assertEqual(session.core.log(),before)
        session.start('guest-2','cat-b','seat-2');before=session.core.log()
        with self.assertRaises(ValueError):session.core.step({'seat-1':['direct',None],'seat-2':['invalid',None]})
        with self.assertRaises(ValueError):session.core.step({'seat-1':['direct',None]})
        self.assertEqual(session.core.log(),before)

    def test_auto_fills_both_seats_without_reusing_cat(self):
        session=self.session();session.automatic_step();session.automatic_step()
        self.assertEqual({key:s.cat_id for key,s in session.active_interactions.items()}, {'seat-1':'cat-a','seat-2':'cat-b'})
        self.assertEqual([cat.id for cat in session.available_cats()],['cat-c'])
        self.assertEqual(session.core.tick,2)

    def test_both_close_same_tick_and_bill_once(self):
        session=self.session(opening=2);self.assigned(session);session.automatic_step()
        self.assertTrue(session.core.closed)
        self.assertFalse(session.active_interactions)
        self.assertEqual(session.core.funds,20)
        self.assertEqual(len(session.core.outcomes),2)
        self.assertEqual(session.core.visits['guest-1'].departure_reason,'closing')
        self.assertEqual(session.core.visits['guest-2'].departure_reason,'closing')
        session.finish();session.persist()
        self.assertEqual(session.core.funds,20)
        self.assertEqual(len([e for e in session.core.events if e['kind']=='departure']),3)

    def test_simultaneous_special_bonuses_are_billed_per_seat(self):
        session=self.session(ticks=2,direct_gain=100,tension_enthusiastic=100)
        self.assigned(session);session.automatic_step();session.automatic_step()
        self.assertEqual(session.core.funds,440)
        self.assertEqual(session.core.interaction_bonus,400)
        self.assertEqual([session.core.visits[key].bill for key in ('guest-1','guest-2')],[220,220])
        self.assertEqual({e['seat_id'] for e in session.core.events if e['kind']=='interaction_completed'},{'seat-1','seat-2'})

    def test_one_exhausts_while_other_continues_and_freed_seat_can_refill(self):
        session=self.session(direct_cost=100);session.step();session.start('guest-1','cat-a','seat-1')
        session.interaction_config=RelationshipConfig()
        session.start('guest-2','cat-b','seat-2');session.automatic_step()
        self.assertEqual(list(session.active_interactions),['seat-2'])
        self.assertTrue(session.core.cats['cat-a'].cannot_continue)
        session.start('guest-3','cat-c','seat-1')
        session.automatic_step()
        self.assertEqual(session.core.cats['cat-b'].stamina,90)
        self.assertEqual(session.core.cats['cat-c'].stamina,95)
        self.assertEqual(session.core.cats['cat-a'].stamina,0)

    def test_partial_save_failure_blocks_all_seats_and_retry_is_idempotent(self):
        session=self.session(ticks=1);self.assigned(session)
        apply=self.store.apply
        count=0
        def fail_second(core):
            nonlocal count
            count+=1
            if count==2:raise OSError('full')
            return apply(core)
        with patch.object(self.store,'apply',side_effect=fail_second):
            with self.assertRaises(OSError):session.automatic_step()
        self.assertEqual(len(session.pending),1)
        self.assertEqual(session.core.funds,20)
        before=session.core.log()
        with self.assertRaises(ValueError):session.automatic_step()
        self.assertEqual(session.core.log(),before)
        session.persist();session.persist()
        self.assertEqual(session.core.funds,20)
        for cat,guest in [('cat-a','guest-1'),('cat-b','guest-2')]:
            self.assertEqual(self.store.snapshot(cat,guest)['affinity'],.5)

    def test_replay_both_active_and_completed_without_store_writes(self):
        session=self.session(ticks=2);self.assigned(session);session.automatic_step()
        for ended in (False,True):
            if ended:session.automatic_step()
            data=json.loads(json.dumps(session.core.log()));before=self.store.path.read_bytes()
            self.assertEqual(verify_cafe_interaction(data).snapshot(),session.core.snapshot())
            self.assertEqual(self.store.path.read_bytes(),before)
            broken=copy.deepcopy(data);broken['seat_ids']=['seat-1']
            with self.assertRaises(ValueError):verify_cafe_interaction(broken)

    def test_seed_cats_preserves_existing_profiles_and_is_repeatable(self):
        self.store.register_cat('playtest-mike','既存の名前',Personality())
        self.assertEqual(len(add_playtest_cats(self.store)),4)
        self.assertEqual(self.store.cat_profile('playtest-mike')['name'],'既存の名前')
        before=self.store.path.read_bytes()
        self.assertEqual(add_playtest_cats(self.store),[])
        self.assertEqual(self.store.path.read_bytes(),before)
