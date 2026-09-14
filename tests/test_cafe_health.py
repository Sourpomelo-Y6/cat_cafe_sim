from dataclasses import asdict, replace
from pathlib import Path
import copy
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CafeHealthTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'day.json'
        self.store=RelationshipStore(Path(folder.name)/'relations.json')
        for key in ('a','b'):
            self.store.register_cat(key,key,Personality())

    def session(self, seats=2, rules=None, seed=0, cats=None, recovery=5):
        ids=cats or (['a','b'] if seats==2 else ['a'])
        core_type=MultiSeatCafeCore if seats==2 else CafeInteractionCore
        core=core_type(replace(Config.load(),opening_ticks=3,arrival_ticks=(0,0) if seats==2 else (0,)),
                       seed=seed,cat_ids=ids)
        core.set_shifts(ids,dict(max_fatigue=100,fatigue_per_service_tick=10,rest_day_recovery=recovery))
        core.enable_health(asdict(rules or HealthRules(safe_fatigue=0,probability_per_fatigue=1,max_probability=1)))
        return CafeInteractionSession(core=core,store=self.store,
            interaction_config=replace(RelationshipConfig(),ticks=2))

    def close_day(self, session):
        while not session.core.closed:
            session.automatic_step()

    def test_illness_two_full_rest_days_and_return_in_both_modes(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                session=self.session(seats)
                core=session.core
                self.close_day(session)
                self.assertTrue(all(cat.health_status=='sick' for cat in core.cats.values()))
                self.assertEqual(core.cats['a'].recovery_days_remaining,2)
                self.assertEqual(core.day_result()['cats']['a']['health']['outcome'],'sick')
                core_before=core.log()
                core.day_result();session.persist()
                self.assertEqual(core.log(),core_before)
                session.next_day()
                self.assertEqual(core.working_cats,set())
                self.assertEqual(core.cats['a'].stamina,core.config.max_stamina)
                self.assertEqual(core.cats['a'].recovery_days_remaining,2)
                self.assertEqual(session.available_cats(),[])
                before=core.log()
                with self.assertRaises(ValueError):session.set_shifts(['a'])
                self.assertEqual(core.log(),before)
                session.automatic_step()
                before=core.snapshot()
                with self.assertRaises(ValueError):session.start('guest-1','a')
                self.assertEqual(core.snapshot(),before)
                self.close_day(session)
                self.assertEqual(core.cats['a'].recovery_days_remaining,1)
                self.assertEqual(core.cats['a'].fatigue,15)
                self.assertEqual(core.summary()['revenue'],0)
                self.assertIsNone(core.health_results['a']['draw'])
                session.next_day();self.close_day(session)
                self.assertEqual(core.cats['a'].health_status,'healthy')
                self.assertEqual(core.cats['a'].recovery_days_remaining,0)
                self.assertEqual(core.cats['a'].fatigue,10)
                # Probability would be 1 at fatigue 10; recovery day is not re-rolled.
                self.assertEqual(core.health_results['a']['outcome'],'recovered')
                self.assertIsNone(core.health_results['a']['draw'])
                session.next_day()
                self.assertEqual(core.working_cats,set())
                session.set_shifts(['a'])
                self.assertEqual([cat.id for cat in session.available_cats()],['a'])
                self.assertFalse(core.cats['a'].cannot_continue)
                self.assertEqual(verify_cafe_interaction(core.log()).snapshot(),core.snapshot())

    def test_threshold_cap_zero_probability_and_invalid_rules(self):
        rules=HealthRules()
        self.assertEqual(rules.probability(60),0)
        self.assertAlmostEqual(rules.probability(70),.2)
        self.assertEqual(rules.probability(100),.5)
        for kwargs in ({'safe_fatigue':-1},{'max_probability':1.1},{'max_probability':True},
                       {'probability_per_fatigue':float('inf')},{'safe_fatigue':float('nan')},
                       {'recovery_days':0},{'recovery_days':1.5},{'recovery_days':True}):
            with self.assertRaises(ValueError):HealthRules(**kwargs)
        for rules in (HealthRules(safe_fatigue=20),HealthRules(safe_fatigue=0,max_probability=0)):
            session=self.session(rules=rules);self.close_day(session)
            self.assertTrue(all(cat.health_status=='healthy' for cat in session.core.cats.values()))
            self.assertTrue(all(result['probability']==0 for result in session.core.health_results.values()))

    def test_seed_cat_order_and_replay_are_reproducible(self):
        rules=HealthRules(safe_fatigue=0,probability_per_fatigue=.025,max_probability=1)
        a=self.session(rules=rules,seed=7);self.close_day(a)
        b=self.session(rules=rules,seed=7,cats=['b','a']);self.close_day(b)
        self.assertEqual(a.core.health_results,b.core.health_results)
        c=self.session(rules=rules,seed=8);self.close_day(c)
        self.assertNotEqual(a.core.health_results['a']['draw'],c.core.health_results['a']['draw'])
        self.assertNotEqual(a.core.health_results['a']['draw'],a.core.health_results['b']['draw'])
        self.assertEqual(verify_cafe_interaction(a.core.log()).snapshot(),a.core.snapshot())
        damaged=copy.deepcopy(a.core.log())
        damaged['operations'][-1]['state']['health']['results']['a']['remaining_after']=999
        with self.assertRaises(ValueError):verify_cafe_interaction(damaged)

    def test_saves_before_illness_during_rest_and_after_recovery(self):
        session=self.session()
        session.automatic_step();session.automatic_step()
        save_game(session,self.path)
        loaded,_=load_game(self.path)
        self.close_day(loaded)
        self.assertEqual(loaded.core.cats['a'].recovery_days_remaining,2)
        save_game(loaded,self.path)
        with patch.object(HealthRules,'load',side_effect=AssertionError('must use saved rules')):
            loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.cats['a'].recovery_days_remaining,2)
        loaded.next_day();loaded.automatic_step()
        save_game(loaded,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.cats['a'].recovery_days_remaining,2)
        self.close_day(loaded)
        self.assertEqual(loaded.core.cats['a'].recovery_days_remaining,1)
        loaded.next_day();self.close_day(loaded)
        save_game(loaded,self.path)
        resumed,_=load_game(self.path)
        self.assertEqual(resumed.core.snapshot(),loaded.core.snapshot())
        self.assertEqual(resumed.core.cats['a'].health_status,'healthy')

    def test_save_failure_retry_does_not_change_illness_or_recovery(self):
        session=self.session()
        session.automatic_step();session.automatic_step()
        with patch.object(self.store,'apply',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):session.automatic_step()
        self.assertTrue(session.core.closed)
        self.assertTrue(session.pending)
        result=copy.deepcopy(session.core.health_results)
        save_game(session,self.path)
        loaded,_=load_game(self.path)
        loaded.persist();loaded.persist()
        self.assertEqual(loaded.core.health_results,result)
        loaded.next_day()
        self.assertEqual(loaded.core.cats['a'].recovery_days_remaining,2)

    def test_old_shift_save_keeps_old_rules_until_enabled(self):
        core=MultiSeatCafeCore(replace(Config.load(),opening_ticks=3,arrival_ticks=(0,)),cat_ids=['a'])
        core.set_shifts(['a'],dict(max_fatigue=100,fatigue_per_service_tick=50,rest_day_recovery=20))
        session=CafeInteractionSession(core=core,store=self.store,
                                      interaction_config=replace(RelationshipConfig(),ticks=2))
        self.close_day(session)
        self.assertEqual(core.cats['a'].fatigue,100)
        self.assertEqual(core.cats['a'].health_status,'healthy')
        self.assertNotIn('health',core.snapshot())
        save_game(session,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(core.log(),loaded.core.log())
        loaded.next_day();loaded.set_shifts([])
        self.assertIsNotNone(loaded.core.health_rules)
        self.assertNotIn('health',loaded.core.day_results[0]['cats']['a'])
        self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(),loaded.core.snapshot())

    def test_enable_rule_and_shift_change_are_rejected_atomically(self):
        session=self.session()
        before=session.core.log()
        with self.assertRaises(ValueError):session.core.enable_health(asdict(HealthRules()))
        self.assertEqual(session.core.log(),before)
        legacy=MultiSeatCafeCore(replace(Config.load(),opening_ticks=3,arrival_ticks=(0,)),cat_ids=['a'])
        legacy.set_shifts(['a'])
        before=legacy.log()
        with self.assertRaises(ValueError):legacy.enable_health({'recovery_days':0})
        self.assertEqual(legacy.log(),before)
        legacy.step()
        before=legacy.log()
        with self.assertRaises(ValueError):legacy.enable_health(asdict(HealthRules()))
        self.assertEqual(legacy.log(),before)

    def test_rest_probability_uses_fatigue_after_recovery(self):
        session=self.session(rules=HealthRules(safe_fatigue=20,max_probability=1),recovery=20)
        self.close_day(session)
        self.assertEqual(session.core.cats['a'].fatigue,20)
        self.assertEqual(session.core.cats['a'].health_status,'healthy')
        session.next_day();session.set_shifts([]);self.close_day(session)
        self.assertEqual(session.core.health_results['a']['probability'],0)
        self.assertEqual(session.core.cats['a'].fatigue,0)
