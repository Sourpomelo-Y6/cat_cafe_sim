import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.cafe_shifts import ShiftRules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CafeShiftTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'day.json'
        self.store=RelationshipStore(Path(folder.name)/'relations.json')
        for key in ('a','b','c'):
            self.store.register_cat(key,key,Personality())
        self.config=replace(Config.load(),opening_ticks=5,arrival_ticks=(0,0))

    def session(self, seats=2):
        return CafeInteractionSession(store=self.store,seat_count=seats,cafe_config=self.config,
                                      interaction_config=replace(RelationshipConfig(),ticks=2))

    def close_day(self, session):
        while not session.core.closed:
            session.automatic_step()

    def test_rest_excluded_from_manual_and_automatic_assignments_in_both_modes(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                session=self.session(seats)
                session.set_shifts(['b'])
                self.assertEqual([cat.id for cat in session.available_cats()],['b'])
                session.automatic_step()
                before=session.core.snapshot()
                with self.assertRaises(ValueError):session.start('guest-1','a')
                self.assertEqual(session.core.snapshot(),before)
                self.close_day(session)
                self.assertTrue(session.core.outcomes)
                self.assertTrue(all(log['initial_relationship']['cat_id']=='b' for log in session.core.outcomes.values()))
                result=session.core.day_result()['cats']
                self.assertEqual(result['b']['fatigue_after'],session.core.cat_service_ticks['b'])
                self.assertEqual(result['a']['fatigue_after'],0)
                self.assertEqual(result['a']['shift'],'rest')
                self.assertEqual(result['c']['service_ticks'],0)

    def test_two_seats_fatigue_is_individual_and_rest_recovers_next_day(self):
        session=self.session()
        self.close_day(session)
        self.assertEqual({key:cat.fatigue for key,cat in session.core.cats.items()}, {'a':2,'b':2,'c':0})
        session.next_day()
        self.assertEqual(session.core.cats['a'].fatigue,2)
        self.assertEqual(session.core.cats['a'].stamina,session.core.config.max_stamina)
        session.set_shifts([])
        self.close_day(session)
        self.assertEqual(session.core.summary()['revenue'],0)
        self.assertEqual(session.core.summary()['completed_interactions'],0)
        self.assertTrue(all(cat.fatigue==0 for cat in session.core.cats.values()))
        self.assertEqual(session.core.day_result()['cats']['a']['fatigue_before'],2)
        session.next_day()
        self.assertEqual(session.core.working_cats,set())
        self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(),session.core.snapshot())

    def test_invalid_and_midday_settings_do_not_change_state(self):
        session=self.session()
        for selected in (['missing'],['a','a'],'a',[True]):
            before=session.core.log()
            with self.assertRaises(ValueError):session.set_shifts(selected)
            self.assertEqual(session.core.log(),before)
        session.automatic_step()
        before=session.core.log()
        with self.assertRaises(ValueError):session.set_shifts([])
        self.assertEqual(session.core.log(),before)

    def test_settings_and_fatigue_resume_without_double_settlement(self):
        session=self.session()
        session.set_shifts(['a','b'])
        save_game(session,self.path)
        session,_=load_game(self.path)
        self.assertEqual(session.core.working_cats,{'a','b'})
        session.automatic_step(); session.automatic_step()
        save_game(session,self.path)
        session,_=load_game(self.path)
        self.assertEqual(session.core.cat_service_ticks,{'a':1,'b':1,'c':0})
        self.close_day(session)
        before=copy.deepcopy(session.core.snapshot())
        save_game(session,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.snapshot(),before)
        loaded.persist(); loaded.finish()
        self.assertEqual(loaded.core.snapshot(),before)
        loaded.next_day()
        self.assertEqual(loaded.core.cats['a'].fatigue,2)

    def test_legacy_log_and_save_still_replay_and_can_enable_at_next_preparation(self):
        for core_type in (CafeInteractionCore,MultiSeatCafeCore):
            core=core_type(self.config,cat_ids=['a'])
            session=CafeInteractionSession(core=core,store=self.store)
            self.close_day(session)
            self.assertNotIn('shifts',core.snapshot())
            self.assertNotIn('shift',core.day_result()['cats']['a'])
            save_game(session,self.path)
            loaded,_=load_game(self.path)
            from cat_cafe_sim.core.cafe_checkpoint import snapshot
            self.assertEqual(loaded.core.snapshot(),snapshot(core))
            loaded.next_day(); loaded.set_shifts([])
            self.assertIsNotNone(loaded.core.shift_rules)
            self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(),loaded.core.snapshot())

    def test_config_validation_cap_and_no_repeat_on_result_read(self):
        for kwargs in ({'max_fatigue':0},{'rest_day_recovery':-1},
                       {'fatigue_per_service_tick':float('nan')},{'max_fatigue':True}):
            with self.assertRaises(ValueError):ShiftRules(**kwargs)
        core=MultiSeatCafeCore(self.config,cat_ids=['a','b','c'])
        core.set_shifts(['a','b'],dict(max_fatigue=3,fatigue_per_service_tick=2,rest_day_recovery=1))
        session=CafeInteractionSession(core=core,store=self.store,
                                      interaction_config=replace(RelationshipConfig(),ticks=2))
        self.close_day(session)
        self.assertEqual(core.cats['a'].fatigue,3)
        result=core.day_result()
        self.assertEqual(core.day_result(),result)
        session.next_day();session.set_shifts(['c']);self.close_day(session)
        self.assertEqual(core.cats['a'].fatigue,2)
        self.assertEqual(core.cats['b'].fatigue,2)
        self.assertEqual(core.cats['c'].fatigue,3)

    def test_relationship_save_failure_at_closing_does_not_repeat_fatigue(self):
        session=CafeInteractionSession(store=self.store,
            cafe_config=replace(self.config,opening_ticks=3),
            interaction_config=replace(RelationshipConfig(),ticks=2))
        session.automatic_step();session.automatic_step()
        with patch.object(session.store,'apply',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):session.automatic_step()
        self.assertTrue(session.core.closed)
        self.assertTrue(session.pending)
        before={key:cat.fatigue for key,cat in session.core.cats.items()}
        self.assertEqual(before,{'a':2,'b':2,'c':0})
        with self.assertRaises(ValueError):session.next_day()
        session.persist();session.persist();session.next_day()
        self.assertEqual({key:cat.fatigue for key,cat in session.core.cats.items()},before)
