import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore, RelationshipConflict
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CafeSaveTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.store=RelationshipStore(self.root/'relationships.json')
        for key in ('a','b','c'):self.store.register_cat(key,key,Personality())
        self.path=self.root/'day.json'

    def session(self, ticks=20, **rules):
        return CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),arrival_ticks=(0,0,1),max_wait_ticks=20),
            interaction_config=replace(RelationshipConfig(),ticks=ticks,**rules))

    def active(self, session):
        session.automatic_step();session.automatic_step()

    def test_two_active_seats_queue_reservations_restore_and_continue(self):
        session=self.session(ticks=2,direct_gain=100,tension_enthusiastic=100)
        self.active(session)
        self.assertEqual(session.core.queue,['guest-3'])
        self.assertTrue(all(s.state['connect_pending'] for s in session.active_interactions.values()))
        before=self.store.path.read_bytes()
        save_game(session,self.path,auto_assign=True)
        loaded,automatic=load_game(self.path)
        self.assertTrue(automatic)
        self.assertEqual(loaded.core.snapshot(),session.core.snapshot())
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(loaded.interaction_config,session.interaction_config)
        loaded.automatic_step()
        self.assertEqual(loaded.core.funds,440)
        self.assertFalse(loaded.pending)
        loaded.persist();loaded.finish()
        self.assertEqual(loaded.core.funds,440)
        self.assertEqual(verify_cafe_interaction(loaded.core.log()).summary(),loaded.core.summary())

    def test_partial_relation_save_failure_is_resumable_without_reaccounting(self):
        session=self.session(ticks=1);session.automatic_step()
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
        save_game(session,self.path)
        before=self.store.path.read_bytes()
        loaded,_=load_game(self.path)
        self.assertEqual(len(loaded.pending),1)
        self.assertEqual(self.store.path.read_bytes(),before)
        with self.assertRaises(ValueError):loaded.automatic_step()
        loaded.persist();loaded.persist()
        self.assertFalse(loaded.pending)
        self.assertEqual(loaded.core.funds,20)
        for cat,guest in [('a','guest-1'),('b','guest-2')]:
            self.assertEqual(self.store.snapshot(cat,guest),{'affinity':.5,'revision':1})

    def test_relation_retry_after_checkpoint_is_recognized_on_load(self):
        session=self.session(ticks=1);session.automatic_step()
        with patch.object(self.store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):session.automatic_step()
        save_game(session,self.path)
        session.persist()
        before=self.store.path.read_bytes()
        for _ in range(2):
            loaded,_=load_game(self.path);loaded.persist()
            self.assertFalse(loaded.pending)
            self.assertEqual(loaded.core.funds,20)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_old_active_checkpoint_is_rejected_after_later_outcomes(self):
        session=self.session(ticks=2);self.active(session);save_game(session,self.path)
        session.automatic_step()
        before=self.store.path.read_bytes()
        with self.assertRaises(RelationshipConflict):load_game(self.path)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_external_change_after_load_stops_before_clock_or_money(self):
        session=self.session();self.active(session);save_game(session,self.path)
        loaded,_=load_game(self.path)
        self.store.register_cat('new','新しい猫',Personality())
        before=loaded.core.log()
        with self.assertRaises(RelationshipConflict):loaded.automatic_step()
        with self.assertRaises(RelationshipConflict):loaded.finish()
        with self.assertRaises(RelationshipConflict):save_game(loaded,self.path)
        self.assertEqual(loaded.core.log(),before)

    def test_atomic_failure_keeps_old_save_and_live_session(self):
        session=self.session();self.active(session);save_game(session,self.path)
        previous=self.path.read_bytes();session.automatic_step()
        state=session.core.snapshot()
        with patch('cat_cafe_sim.storage.relationships.os.replace',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(session,self.path)
        self.assertEqual(self.path.read_bytes(),previous)
        self.assertEqual(session.core.snapshot(),state)
        self.assertEqual(list(self.root.glob('.day.json.*')),[])
        old,_=load_game(self.path)
        self.assertEqual(old.core.tick,2)
        save_game(session,self.path)
        self.assertEqual(load_game(self.path)[0].core.tick,3)

    def test_corruption_missing_relations_and_path_collision_rejected(self):
        session=self.session();self.active(session);save_game(session,self.path)
        original=self.path.read_bytes()
        data=json.loads(original)
        for change in ('money','policy','relation'):
            bad=copy.deepcopy(data)
            if change=='money':bad['core']['summary']['funds']+=1
            if change=='policy':bad['policy_version']='unknown'
            if change=='relation':bad['relationship_path']=str(self.root/'missing.json')
            self.path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):load_game(self.path)
        self.path.write_bytes(original)
        with self.assertRaises(ValueError):save_game(session,self.store.path)
        with self.assertRaises(ValueError):session.save_log(self.path)
        self.assertEqual(self.path.read_bytes(),original)

    def test_closed_day_and_single_seat_legacy_can_restore(self):
        old=CafeInteractionSession(CafeInteractionCore(replace(Config.load(),opening_ticks=2,arrival_ticks=(0,))),self.store)
        old.automatic_step();old.automatic_step()
        self.assertTrue(old.core.closed)
        save_game(old,self.path)
        loaded,_=load_game(self.path)
        from cat_cafe_sim.core.cafe_checkpoint import snapshot
        self.assertEqual(loaded.core.snapshot(),snapshot(old.core))
        self.assertFalse(loaded.automatic_step())

    def test_unlogged_state_mutation_is_not_silently_lost(self):
        session=self.session();self.active(session)
        session.core.cats['c'].spirit-=1
        with self.assertRaises(ValueError):save_game(session,self.path)
        self.assertFalse(self.path.exists())
