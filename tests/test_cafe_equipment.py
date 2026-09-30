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

    def unlocked_upgrade(self, health=None):
        from cat_cafe_sim.core.cafe_management import rules as management_rules
        s = self.session(funds=10000, health=health)
        s.enable_management(dict(management_rules(), starting_funds=10000, stress_per_service_tick=0))
        s.enable_goal(dict(days=10, target=105, cap=300, gain_per_success=5))
        self.close(s)
        self.assertEqual(s.core.goal['status'], 'cleared')
        s.continue_goal()
        s.next_day()
        return s

    def test_upgrade_effect_total_forecast_finance_restore_replay(self):
        s = self.unlocked_upgrade()
        s.purchase_rest_space()
        original = copy.deepcopy(s.core.rest_space)
        self.assertEqual(shift_forecast(s.core, 'b')['rest']['fatigue'], 2)
        funds = s.core.funds
        s.upgrade_rest_space()
        self.assertEqual(s.core.funds, funds-800)
        self.assertEqual(s.core.rest_space['rules'], original['rules'])
        self.assertEqual(s.core.cats['b'].fatigue, 32)
        self.assertEqual(shift_forecast(s.core, 'b')['rest']['fatigue'], 0)
        self.assertEqual(s.core.summary()['equipment_expenses'], 1200)
        self.rejected(s, s.upgrade_rest_space)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s = self.reload(s)
        s.day_off()
        self.assertEqual(s.core.cats['b'].fatigue, 0)
        self.assertEqual(s.core.day_results[1]['summary']['equipment_expenses'], 1200)
        self.assertEqual(s.core.summary()['equipment_expenses'], 0)
        self.reload(s)

    def test_upgrade_conditions_and_funds_boundaries(self):
        s = self.session()
        self.rejected(s, s.upgrade_rest_space)
        s.purchase_rest_space()
        self.rejected(s, s.upgrade_rest_space)
        for funds in (799, 800, 801):
            s = self.unlocked_upgrade()
            self.rejected(s, s.upgrade_rest_space)
            s.purchase_rest_space()
            s.core.funds = funds
            if funds <= 800:
                self.rejected(s, s.upgrade_rest_space)
            else:
                s.core.recorded_digest = None
                s.upgrade_rest_space()
                self.assertEqual(s.core.funds, 1)
        s = self.unlocked_upgrade()
        s.purchase_rest_space()
        s.automatic_step()
        self.rejected(s, s.upgrade_rest_space)
        self.close(s)
        self.rejected(s, s.upgrade_rest_space)

    def test_upgrade_excludes_workers_and_absent_cats(self):
        s = self.unlocked_upgrade()
        s.purchase_rest_space()
        s.upgrade_rest_space()
        s.dispatch('a')
        s.set_shifts(['b'])
        self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue, 40)
        self.assertEqual(s.core.cats['b'].fatigue, 64)
        s.resolve_activity('dispatch-2-a')
        s.next_day()
        s.set_shifts([])
        self.close(s)
        self.assertEqual(s.core.cats['b'].fatigue, 24)
        self.reload(s)

    def test_upgrade_preserves_treatment_duration(self):
        s = self.unlocked_upgrade(HealthRules(safe_fatigue=0, probability_per_fatigue=1, max_probability=1, recovery_days=2))
        s.purchase_rest_space()
        s.upgrade_rest_space()
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.assertEqual(s.core.cats['a'].recovery_days_remaining, 1)
        self.reload(s)

    def test_old_equipment_and_frozen_upgrade_rules(self):
        from cat_cafe_sim.core.cafe_equipment import upgrade_rules
        s = self.unlocked_upgrade()
        s.purchase_rest_space(dict(cost=410, recovery_bonus=12))
        s = self.reload(s)
        self.assertNotIn('upgrade', s.core.rest_space)
        s.upgrade_rest_space(dict(cost=810, recovery_bonus=22))
        def frozen(data=None):
            if data is None:
                raise AssertionError('強化時の設定を使う必要があります。')
            return upgrade_rules(data)
        with patch('cat_cafe_sim.core.cafe_equipment.upgrade_rules', side_effect=frozen):
            self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s = self.unlocked_upgrade()
        s.purchase_rest_space(dict(cost=400, recovery_bonus=25))
        self.rejected(s, s.upgrade_rest_space)

    def test_upgrade_failed_save_and_player_block(self):
        s = self.unlocked_upgrade()
        s.purchase_rest_space()
        s.play_with_player('a')
        self.rejected(s, s.upgrade_rest_space)
        s.player_command(finish=True)
        s.upgrade_rest_space()
        funds = s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s, self.path)
        self.assertEqual(s.core.funds, funds)
        self.rejected(s, s.upgrade_rest_space)
        self.reload(s)

    def test_upgrade_corrupt_save_rejected(self):
        s = self.unlocked_upgrade()
        s.purchase_rest_space()
        s.upgrade_rest_space()
        source = checkpoint(s.core, set())
        for mutate in (
            lambda state: state['rest_space'].pop('upgrade'),
            lambda state: state['rest_space']['upgrade'].update(day=1),
            lambda state: state['rest_space']['upgrade']['rules'].update(cost=799),
            lambda state: state['rest_space']['upgrade']['rules'].update(recovery_bonus=10),
            lambda state: state['rest_space']['upgrade'].update(extra=True),
        ):
            bad = copy.deepcopy(source)
            mutate(bad['state'])
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        from cat_cafe_sim.core.cafe_equipment import upgrade_rules
        for change in (dict(cost=True), dict(cost=0), dict(recovery_bonus=101), dict(recovery_bonus=float('nan'))):
            with self.assertRaises(ValueError):
                upgrade_rules(dict(upgrade_rules(), **change))

    @unittest.skipUnless(__import__('os').environ.get('CAT_CAFE_TEST_GUI') == '1', 'GUIテストは明示実行')
    def test_upgrade_gui_cancel_purchase_history_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_equipment_gui import CafeEquipmentWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        s = self.unlocked_upgrade()
        s.purchase_rest_space()
        window = CafeEquipmentWindow(root, s, lambda: None)
        window.window.geometry('500x340')
        root.update()
        self.assertIn('強化費用：800', window.details.get())
        self.assertIn('＋10 → ＋20', window.details.get())
        self.assertNotIn('disabled', window.upgrade_button.state())
        for button in (window.purchase_button, window.upgrade_button, window.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), window.window.winfo_rootx()+window.window.winfo_width())
        funds = s.core.funds
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.upgrade_button.invoke()
        self.assertEqual(s.core.funds, funds)
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.upgrade_button.invoke()
        self.assertIn('強化済み', window.status.get())
        self.assertIn('支払額：800', window.details.get())
        self.assertIn('疲労回復＋20', window.details.get())
        self.assertIn('disabled', window.upgrade_button.state())
