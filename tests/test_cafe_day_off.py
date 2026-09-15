from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_history import comparison_rows
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore, RelationshipConflict
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CafeDayOffTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'day.json'
        self.store=RelationshipStore(Path(folder.name)/'relations.json')
        for key in ('a','b'):self.store.register_cat(key,key,Personality())

    def session(self, seats=2, health=None, legacy=False):
        cls=MultiSeatCafeCore if seats==2 else CafeInteractionCore
        core=cls(replace(Config.load(),opening_ticks=3,arrival_ticks=(0,0)),cat_ids=['a','b'],compact=not legacy)
        if not legacy:
            core.set_shifts(['a','b'],dict(max_fatigue=100,fatigue_per_service_tick=20,rest_day_recovery=5))
            core.enable_health(asdict(health or HealthRules()))
        return CafeInteractionSession(core,self.store,replace(RelationshipConfig(),ticks=2))

    def close_day(self, session):
        while not session.core.closed:session.automatic_step()

    def test_skip_has_no_arrivals_and_preserves_plans_money_and_relationships(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                session=self.session(seats)
                session.set_shifts(['a'])
                money=session.core.funds;relations=self.store.path.read_bytes()
                with patch.object(session.core,'_arrive',side_effect=AssertionError('no arrivals')):
                    session.day_off()
                core=session.core
                self.assertEqual((core.day,core.tick,core.closed),(2,0,False))
                self.assertEqual(core.working_cats,{'a'})
                self.assertEqual(core.returning_customers,set())
                self.assertEqual(core.visits,{})
                self.assertEqual(core.queue,[])
                self.assertEqual(core.outcomes,{})
                self.assertEqual(core.funds,money)
                self.assertEqual(self.store.path.read_bytes(),relations)
                result=core.day_results[0]
                self.assertEqual(result['day_type'],'day_off')
                self.assertEqual(result['summary']['arrivals'],0)
                self.assertEqual(result['summary']['departures'],{})
                self.assertEqual(result['summary']['revenue'],0)
                self.assertTrue(all(cat['shift']=='rest' for cat in result['cats'].values()))
                self.assertEqual(verify_cafe_interaction(core.log()).snapshot(),core.snapshot())
                session.automatic_step()
                self.assertTrue(core.visits['guest-1'].first_visit)

    def test_rest_recovery_once_and_lightweight_save_comparison(self):
        session=self.session();self.close_day(session);session.next_day()
        self.assertEqual(session.core.cats['a'].fatigue,40)
        money=session.core.funds
        session.day_off()
        self.assertEqual(session.core.cats['a'].fatigue,35)
        self.assertEqual(session.core.cats['a'].stamina,session.core.config.max_stamina)
        self.assertEqual(session.core.funds,money)
        before=session.core.snapshot();history=comparison_rows(session.core)
        save_game(session,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.snapshot(),before)
        self.assertEqual(comparison_rows(loaded.core),history)
        self.assertEqual(history[-1]['day_type'],'day_off')
        self.assertTrue(all(row['interactions']==0 for row in history[-1]['cats'].values()))
        loaded.persist();loaded.persist()
        self.assertEqual(loaded.core.snapshot(),before)
        loaded.day_off()
        self.assertEqual(loaded.core.cats['a'].fatigue,30)
        self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(),loaded.core.snapshot())

    def test_sickness_and_recovery_days_follow_normal_rules(self):
        session=self.session(health=HealthRules(safe_fatigue=0,probability_per_fatigue=1,max_probability=1))
        self.close_day(session);session.next_day()
        core=session.core
        self.assertEqual(core.working_cats,set())
        self.assertEqual(core.cats['a'].recovery_days_remaining,2)
        session.day_off()
        self.assertEqual(core.cats['a'].recovery_days_remaining,1)
        session.day_off()
        self.assertEqual(core.cats['a'].recovery_days_remaining,0)
        self.assertEqual(core.cats['a'].health_status,'healthy')
        self.assertEqual(core.working_cats,set())
        self.assertEqual(core.day_results[-1]['cats']['a']['health']['outcome'],'recovered')
        session.set_shifts(['a'])
        session.day_off()  # fatigue is still high: a new illness starts, without counting today as treatment.
        self.assertEqual(core.cats['a'].recovery_days_remaining,2)
        self.assertEqual(core.working_cats,set())
        self.assertEqual(core.day_results[-1]['cats']['a']['health']['outcome'],'sick')
        self.assertEqual(verify_cafe_interaction(core.log()).snapshot(),core.snapshot())

    def test_midday_closed_pending_and_stale_states_are_rejected(self):
        session=self.session();session.automatic_step()
        before=session.core.log()
        with self.assertRaises(ValueError):session.day_off()
        self.assertEqual(session.core.log(),before)
        session.automatic_step()
        with patch.object(self.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):session.automatic_step()
        before=session.core.log()
        with self.assertRaises(ValueError):session.day_off()
        self.assertEqual(session.core.log(),before)
        session.persist()
        with self.assertRaises(ValueError):session.day_off()
        session.next_day();save_game(session,self.path)
        self.store.register_cat('other','他の猫',Personality())
        before=session.core.log()
        with self.assertRaises(RelationshipConflict):session.day_off()
        self.assertEqual(session.core.log(),before)

    def test_legacy_preparation_can_enable_rules_and_take_day_off(self):
        session=self.session(legacy=True)
        session.day_off()
        self.assertIsNotNone(session.core.shift_rules)
        self.assertIsNotNone(session.core.health_rules)
        self.assertEqual(session.core.day,2)
        self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(),session.core.snapshot())
