import copy
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_shift_forecast import shift_forecast
from cat_cafe_sim.core.cafe_traits import definitions, trait
from cat_cafe_sim.core.cafe_activities import income, reward
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class TraitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relations.json')
        for key in ('a','b','c'):self.store.register_cat(key,key,Personality())
        self.path=Path(self.temp.name)/'cafe.json'
        self.traits=definitions()

    def session(self, assigned=None, *, fatigue=1, management=True):
        core=MultiSeatCafeCore(replace(Config.load(),opening_ticks=2,arrival_ticks=(0,0),initial_funds=1000),
                               cat_ids=['a','b','c'],compact=True)
        core.set_shifts(['a','b','c'],dict(max_fatigue=100,fatigue_per_service_tick=fatigue,rest_day_recovery=20))
        core.enable_health(asdict(HealthRules(max_probability=0)))
        if assigned is not None:core.initialize_traits({key:self.traits[value] for key,value in assigned.items()})
        s=CafeInteractionSession(core=core,store=self.store,interaction_config=replace(RelationshipConfig(),ticks=1))
        if management:s.enable_management()
        return s

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def reload(self,s):
        save_game(s,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot())
        return loaded

    def test_new_game_assignments_and_frozen_rules(self):
        s=create_game(Path(self.temp.name)/'games')
        self.assertEqual(trait(s.core,'cat-mike')['id'],'hospitality')
        self.assertEqual(trait(s.core,'cat-tama')['id'],'outgoing')
        self.assertEqual(trait(s.core,'cat-kohaku')['id'],'relaxed')
        self.assertIsNone(trait(s.core,'cat-sora'))
        self.assertEqual(dict(cat_details(s,'cat-mike')['basic'])['特性'],'接客好き')
        with patch('cat_cafe_sim.core.cafe_traits.definitions',side_effect=AssertionError('settings changed')):
            loaded,_=load_game(s.checkpoint_path)
            self.assertEqual(loaded.core.traits,s.core.traits)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_hospitality_service_stress_and_fatigue_are_applied_once(self):
        s=self.session({'a':'hospitality'})
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue,1.25)
        self.assertEqual(s.core.cats['b'].fatigue,1)
        self.assertEqual(s.core.management['stress']['a'],.5)
        self.assertEqual(s.core.management['stress']['b'],1)
        s=self.reload(s)
        self.assertEqual(s.core.management['stress']['a'],.5)
        s.next_day()
        self.assertEqual(shift_forecast(s.core,'a')['work']['fatigue'],2.5)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_relaxed_rest_bonus_matches_forecast_and_actual_day_off(self):
        s=self.session({'a':'relaxed'},fatigue=32)
        self.close(s);s.next_day()
        self.assertEqual(s.core.cats['a'].fatigue,40)
        self.assertEqual(s.core.cats['b'].fatigue,32)
        forecast=shift_forecast(s.core,'a')
        self.assertEqual(forecast['rest']['fatigue'],10)
        self.assertEqual(forecast['work']['fatigue'],80)
        s=self.reload(s);s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue,10)
        self.assertEqual(s.core.cats['b'].fatigue,12)
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue,0)
        self.reload(s)

    def test_outgoing_reward_stress_resume_replay_and_no_double_payment(self):
        s=self.session({'c':'outgoing'})
        s.dispatch('c');event=s.core.activities['events']['dispatch-1-c']
        self.assertEqual(reward(s.core,event),125)
        s=self.reload(s);s.day_off()
        self.assertEqual(s.core.management['stress']['c'],0)
        self.assertEqual(s.core.funds,1000)
        s=self.reload(s);s.resolve_activity('dispatch-1-c')
        self.assertEqual(s.core.management['stress']['c'],10)
        self.assertEqual(s.core.funds,1125)
        self.assertEqual(income(s.core),125)
        self.assertEqual(s.core.summary()['dispatch_income'],125)
        before=s.core.log();s.resolve_activity('dispatch-1-c')
        self.assertEqual(s.core.log(),before)
        s=self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.day_off()
        self.assertEqual(s.core.management['stress']['c'],0)

    def test_outgoing_without_management_and_outside_cats_do_not_recover(self):
        s=self.session({'a':'relaxed','c':'outgoing'},management=False,fatigue=32)
        self.close(s);s.next_day()
        self.assertEqual(s.core.cats['a'].fatigue,40)
        s.dispatch('a');s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue,40)
        s.resolve_activity('dispatch-2-a')
        s.dispatch('c');s.day_off();s.resolve_activity('dispatch-3-c')
        self.assertIsNone(s.core.management)
        self.assertEqual(income(s.core),225)
        self.reload(s)

    def test_recruitment_assigns_frozen_trait_without_modifying_existing_cats(self):
        s=self.session();s.open_recruitment()
        key=next(iter(s.core.recruitment['candidates']))
        candidate=copy.deepcopy(s.core.recruitment['candidates'][key])
        s=self.reload(s)
        with patch('cat_cafe_sim.core.cafe_traits.definitions',side_effect=AssertionError('settings changed')):
            s.recruit_cat(key)
        self.assertEqual(s.core.traits,{key:candidate['trait']})
        self.assertEqual(dict(cat_details(s,key)['basic'])['特性'],'接客好き')
        self.assertEqual(self.reload(s).core.traits,s.core.traits)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_old_save_and_old_candidates_keep_no_traits(self):
        from cat_cafe_sim.core.cafe_recruitment import candidates
        s=self.session()
        rows=candidates(s.core.cats)
        for row in rows.values():row.pop('trait',None)
        s.core.open_recruitment(rows)
        s=self.reload(s)
        self.assertIsNone(s.core.traits)
        self.assertEqual(dict(cat_details(s,'a')['basic'])['特性'],'なし')
        s.recruit_cat(next(iter(rows)))
        self.assertIsNone(s.core.traits)
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue,1)
        self.assertEqual(s.core.management['stress']['a'],1)
        self.reload(s)

    def test_invalid_traits_and_joined_trait_mismatch_are_rejected(self):
        s=self.session()
        before=s.core.log()
        for assigned in ({'unknown':self.traits['hospitality']}, {'a':dict(self.traits['hospitality'],service_stress=-1)}):
            with self.assertRaises(ValueError):s.core.initialize_traits(assigned)
            self.assertEqual(s.core.log(),before)
        s.open_recruitment();key=next(iter(s.core.recruitment['candidates']));s.recruit_cat(key)
        source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['traits'][key].update(return_stress=True),
                       lambda d:d['state']['traits'].update({key:self.traits['outgoing']}),
                       lambda d:d['state'].pop('traits')):
            bad=copy.deepcopy(source);mutate(bad)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
