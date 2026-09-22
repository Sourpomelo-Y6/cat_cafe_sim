import copy
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_shift_forecast import shift_forecast
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction, CafeInteractionCore
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_equipment import rules
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.cafe_traits import definitions
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class EquipmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relations.json')
        for key in ('a', 'b', 'c', 'd'):
            self.store.register_cat(key, key, Personality())
        self.path = Path(self.temp.name)/'cafe.json'

    def session(self, funds=1000, seats=2, health=None):
        cls = MultiSeatCafeCore if seats == 2 else CafeInteractionCore
        core = cls(replace(Config.load(), opening_ticks=2, arrival_ticks=(0,0), initial_funds=funds),
                   cat_ids=['a','b','c','d'], compact=True)
        core.set_shifts(['a','b','c','d'], dict(max_fatigue=100, fatigue_per_service_tick=32, rest_day_recovery=20))
        core.enable_health(asdict(health or HealthRules(max_probability=0)))
        core.initialize_traits({'a': definitions()['relaxed']})
        return CafeInteractionSession(core=core, store=self.store, interaction_config=replace(RelationshipConfig(), ticks=1))

    def close(self, s):
        while not s.core.closed:
            s.automatic_step()

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def rejected(self, s, action):
        before = s.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(before, s.core.log())

    def test_forecast_traits_day_off_actual_history_and_replay(self):
        s = self.session()
        self.close(s)
        s.next_day()
        self.assertEqual(s.core.cats['a'].fatigue, 40)
        self.assertEqual(s.core.cats['b'].fatigue, 32)
        self.assertEqual(shift_forecast(s.core, 'a')['rest']['fatigue'], 10)
        work = shift_forecast(s.core, 'a')['work']
        funds = s.core.funds
        s.purchase_rest_space()
        self.assertEqual(s.core.funds, funds-400)
        self.assertEqual(s.core.cats['a'].fatigue, 40)
        self.assertEqual(shift_forecast(s.core, 'a')['rest']['fatigue'], 0)
        self.assertEqual(shift_forecast(s.core, 'b')['rest']['fatigue'], 2)
        self.assertEqual(shift_forecast(s.core, 'a')['work'], work)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s = self.reload(s)
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.assertEqual(s.core.cats['b'].fatigue, 2)
        self.assertEqual(s.core.day_results[1]['summary']['equipment_expenses'], 400)
        self.assertEqual(s.core.summary()['equipment_expenses'], 0)
        def saved_rules_only(data=None):
            if data is None:
                raise AssertionError('購入時の設定を使う必要があります。')
            return rules(data)
        with patch('cat_cafe_sim.core.cafe_equipment.rules', side_effect=saved_rules_only):
            s = self.reload(s)
        s.day_off()
        self.assertEqual(s.core.cats['b'].fatigue, 0)
        self.reload(s)

    def test_business_rest_and_work_and_outside_exclusion(self):
        s = self.session()
        self.close(s)
        s.next_day()
        s.purchase_rest_space()
        s.dispatch('a')
        s.set_shifts(['b'])
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue, 40)
        self.assertEqual(s.core.cats['b'].fatigue, 64)
        s.resolve_activity('dispatch-2-a')
        s.next_day()
        s.set_shifts([])
        self.close(s)  # regular business, all cats rest
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.assertEqual(s.core.cats['b'].fatigue, 34)
        self.reload(s)

    def test_sick_cat_recovers_fatigue_without_shortening_treatment(self):
        s = self.session(health=HealthRules(safe_fatigue=0, probability_per_fatigue=1, max_probability=1, recovery_days=2))
        self.close(s)
        s.next_day()
        self.assertEqual(s.core.cats['a'].health_status, 'sick')
        s.purchase_rest_space()
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.assertEqual(s.core.cats['a'].recovery_days_remaining, 1)
        self.assertEqual(s.core.cats['a'].health_status, 'sick')
        self.reload(s)

    def test_cost_boundaries_old_save_repeat_and_three_seat_accounting(self):
        for funds in (399, 400, 401):
            s = self.session(funds=funds, seats=1)
            if funds <= 400:
                self.rejected(s, s.purchase_rest_space)
            else:
                s.purchase_rest_space()
                self.assertEqual(s.core.funds, 1)
                self.rejected(s, s.purchase_rest_space)
                self.reload(s)
        s = self.reload(self.session())
        self.assertIsNone(s.core.rest_space)
        self.assertNotIn('rest_space', checkpoint(s.core, set())['state'])
        s.expand_seats()
        s.purchase_rest_space()
        self.assertEqual(s.core.funds, 100)
        self.reload(s)

    def test_preparation_pending_events_player_and_failed_save(self):
        s = self.session()
        s.play_with_player('a')
        self.rejected(s, s.purchase_rest_space)
        s.player_command(finish=True)
        s.dispatch('d')
        s.day_off()
        self.rejected(s, s.purchase_rest_space)
        s.resolve_activity('dispatch-1-d')
        funds = s.core.funds
        s.purchase_rest_space()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s, self.path)
        self.assertEqual(s.core.funds, funds-400)
        self.reload(s)
        another = self.session()
        another.automatic_step()
        self.rejected(another, another.purchase_rest_space)
        self.close(another)
        self.rejected(another, another.purchase_rest_space)

    def test_invalid_settings_and_save_accounting(self):
        for change in (dict(cost=0), dict(cost=True), dict(recovery_bonus=101), dict(recovery_bonus=float('inf'))):
            with self.assertRaises(ValueError):
                rules(dict(rules(), **change))
        s = self.session()
        s.purchase_rest_space()
        source = checkpoint(s.core, set())
        for mutate in (
            lambda state: state.pop('rest_space'),
            lambda state: state['rest_space']['rules'].update(cost=300),
            lambda state: state['rest_space'].update(day=2),
            lambda state: state['rest_space']['rules'].update(recovery_bonus=-10),
        ):
            bad = copy.deepcopy(source)
            mutate(bad['state'])
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
