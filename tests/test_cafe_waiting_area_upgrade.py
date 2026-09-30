import copy
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.cafe_operating_cost import estimate
from cat_cafe_sim.core.cafe_waiting_area import (
    rules, upgrade_rules, queue_capacity, max_wait_ticks, daily_cost, expenses, upgrade_reason,
)
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class WaitingUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relationships.json')
        add_playtest_cats(self.store)
        self.path = Path(self.temp.name)/'game.json'

    def session(self, legacy=False, selected=None):
        core = MultiSeatCafeCore(replace(Config.load(), opening_ticks=2, arrival_ticks=(0, 0), initial_funds=10000),
                                 cat_ids=[row['cat_id'] for row in self.store.list_cats()], compact=True)
        core.set_shifts(list(core.cats), dict(max_fatigue=100, fatigue_per_service_tick=1, rest_day_recovery=20))
        core.enable_health(asdict(HealthRules(max_probability=0)))
        s = CafeInteractionSession(store=self.store, core=core,
            interaction_config=replace(RelationshipConfig(), ticks=1))
        s.enable_management(dict(management_rules(), starting_funds=10000, stress_per_service_tick=0))
        s.core.initialize_operating_cost()
        s.enable_goal(dict(days=10, target=105, cap=300, gain_per_success=5,
                           stages=[dict(days=10, target=110), dict(days=30, target=250)]))
        if not legacy:
            s.core.initialize_waiting_area(selected)
        return s

    def close(self, s):
        while not s.core.closed:
            s.automatic_step()

    def unlocked(self, buy=True, selected=None):
        s = self.session(selected=selected)
        self.close(s)
        self.assertEqual(s.core.goal['status'], 'cleared')
        s.advance_goal(); s.next_day()
        if buy:
            s.purchase_waiting_area()
        self.close(s)
        self.assertEqual(s.core.goal['status'], 'cleared')
        s.advance_goal(); s.next_day()
        return s

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def rejected(self, s, action):
        before = s.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(s.core.log(), before)

    def test_upgrade_totals_historical_charges_save_replay_and_rest_day(self):
        s = self.unlocked()
        original = copy.deepcopy(s.core.waiting_area)
        funds = s.core.funds
        s.upgrade_waiting_area()
        self.assertEqual(s.core.funds, funds-1200)
        self.assertEqual(s.core.waiting_area['purchase'], original['purchase'])
        self.assertEqual(s.core.waiting_area['rules'], original['rules'])
        self.assertEqual((queue_capacity(s.core), max_wait_ticks(s.core), daily_cost(s.core)), (6, 12, 20))
        self.assertEqual([daily_cost(s.core, day) for day in (1, 2, 3)], [0, 10, 20])
        self.assertEqual(estimate(s.core), 80)
        self.assertEqual(expenses(s.core), 2000)
        self.assertEqual(s.core.day_results[1]['summary']['operating_cost'], 70)
        self.assertEqual(s.core.summary()['waiting_area_expenses'], 1200)
        self.rejected(s, s.upgrade_waiting_area)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s = self.reload(s)
        s.day_off()
        summary = s.core.day_results[-1]['summary']
        self.assertEqual(summary['operating_cost'], 80)
        self.assertEqual(summary['waiting_area_expenses'], 1200)
        self.assertEqual(summary['total_expenses'], 1280)
        self.assertEqual(s.core.summary()['waiting_area_expenses'], 0)
        s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'], 80)
        self.reload(s)

    def test_same_day_purchase_upgrade_and_business_accounting(self):
        s = self.unlocked(buy=False)
        s.purchase_waiting_area(); s.upgrade_waiting_area()
        self.assertEqual(s.core.summary()['waiting_area_expenses'], 2000)
        self.close(s)
        self.assertEqual(s.core.summary()['waiting_area_expenses'], 2000)
        self.assertEqual(s.core.summary()['operating_cost'], 80)
        s = self.reload(s)
        s.next_day()
        self.assertEqual(s.core.day_results[-1]['summary']['waiting_area_expenses'], 2000)
        self.assertEqual(s.core.summary()['waiting_area_expenses'], 0)
        self.reload(s)

    def test_unlock_missing_purchase_boundaries_and_preparation(self):
        s = self.session()
        self.rejected(s, s.upgrade_waiting_area)
        self.close(s); s.advance_goal(); s.next_day(); s.purchase_waiting_area()
        self.assertIn('第2段階', upgrade_reason(s.core, upgrade_rules()))
        self.rejected(s, s.upgrade_waiting_area)
        for funds in (1199, 1200, 1201):
            s = self.unlocked(); s.core.funds = funds
            if funds <= 1200:
                self.rejected(s, s.upgrade_waiting_area)
            else:
                s.core.recorded_digest = None
                s.upgrade_waiting_area()
                self.assertEqual(s.core.funds, 1)
        s = self.unlocked()
        s.automatic_step(); self.rejected(s, s.upgrade_waiting_area)
        self.close(s); self.rejected(s, s.upgrade_waiting_area)

    def test_queue_capacity_and_wait_deadline_apply_to_arrivals(self):
        config = replace(Config.load(), opening_ticks=15, arrival_ticks=(0,)*7)
        base = CafeInteractionCore(config, compact=True)
        base.waiting_area = dict(rules=rules(), purchase=dict(day=1, cost=800))
        upgraded = CafeInteractionCore(config, compact=True)
        upgraded.waiting_area = dict(base.waiting_area, upgrade=dict(day=1, rules=upgrade_rules()))
        base.step(); upgraded.step()
        self.assertEqual(len(base.queue), 5)
        self.assertEqual(len(upgraded.queue), 6)
        self.assertEqual(base.visits['guest-6'].departure_reason, 'queue_full')
        self.assertIsNone(upgraded.visits['guest-6'].departure_reason)
        self.assertEqual(upgraded.visits['guest-7'].departure_reason, 'queue_full')
        for _ in range(9):
            base.step(); upgraded.step()
        self.assertEqual(base.visits['guest-1'].departure_reason, 'wait_timeout')
        self.assertIsNone(upgraded.visits['guest-1'].departure_reason)
        upgraded.step(); upgraded.step()
        self.assertEqual(upgraded.visits['guest-1'].departure_reason, 'wait_timeout')
        self.assertEqual(upgraded.config.opening_ticks, 15)

    def test_old_saves_custom_rules_and_frozen_upgrade_settings(self):
        old = self.reload(self.session(legacy=True))
        self.assertIsNone(old.core.waiting_area)
        self.rejected(old, old.upgrade_waiting_area)
        s = self.unlocked(selected=dict(rules(), cost=810, daily_cost=12))
        s = self.reload(s)
        self.assertNotIn('upgrade', s.core.waiting_area)
        self.assertEqual(daily_cost(s.core), 12)
        s.upgrade_waiting_area(dict(cost=1210, queue_bonus=3, wait_bonus=6, daily_cost=22))
        def saved(data=None):
            if data is None:
                raise AssertionError('強化時の設定を使う必要があります。')
            return upgrade_rules(data)
        with patch('cat_cafe_sim.core.cafe_waiting_area.upgrade_rules', side_effect=saved):
            self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.assertEqual(daily_cost(s.core, 2), 12)
        self.assertEqual(daily_cost(s.core, 3), 22)
        self.assertEqual(queue_capacity(s.core), 7)
        self.rejected(s, lambda:s.upgrade_waiting_area())

    def test_player_and_failed_save_do_not_duplicate_upgrade(self):
        s = self.unlocked()
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        self.rejected(s, s.upgrade_waiting_area)
        s.player_command(finish=True)
        s.upgrade_waiting_area()
        funds = s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s, self.path)
        self.assertEqual(s.core.funds, funds)
        self.rejected(s, s.upgrade_waiting_area)
        self.reload(s)

    def test_invalid_rules_and_corrupt_upgrade_accounting_rejected(self):
        for change in (dict(cost=True), dict(cost=0), dict(queue_bonus=True), dict(wait_bonus=0), dict(daily_cost=float('nan'))):
            with self.assertRaises(ValueError):
                upgrade_rules(dict(upgrade_rules(), **change))
        s = self.unlocked()
        self.rejected(s, lambda:s.upgrade_waiting_area(dict(upgrade_rules(), queue_bonus=1)))
        s.upgrade_waiting_area(); s.day_off()
        source = checkpoint(s.core, set())
        for mutate in (
            lambda state:state['waiting_area'].pop('upgrade'),
            lambda state:state['waiting_area']['upgrade'].update(day=2),
            lambda state:state['waiting_area']['upgrade'].update(day=True),
            lambda state:state['waiting_area']['upgrade']['rules'].update(cost=1199),
            lambda state:state['waiting_area']['upgrade']['rules'].update(wait_bonus=2),
            lambda state:state['waiting_area']['upgrade']['rules'].update(daily_cost=21),
            lambda state:state['waiting_area']['upgrade'].update(extra=True),
            lambda state:state['operating_cost']['charges'][1].update(facility_cost=20),
            lambda state:state['day_results'][-1]['summary'].update(waiting_area_expenses=0),
        ):
            bad = copy.deepcopy(source); mutate(bad['state'])
            bad['digest'] = digest({key:value for key,value in bad.items() if key!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1', 'requires a display')
class WaitingUpgradeGuiTests(unittest.TestCase):
    setUp = WaitingUpgradeTests.setUp
    session = WaitingUpgradeTests.session
    close = WaitingUpgradeTests.close
    unlocked = WaitingUpgradeTests.unlocked

    def test_confirmation_cancel_history_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_waiting_area_gui import CafeWaitingAreaWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.unlocked()
        window = CafeWaitingAreaWindow(root, s, lambda:None)
        window.window.geometry('480x340'); root.update()
        self.assertIn('強化費：1200', window.details.get())
        self.assertIn('5 → 6人', window.details.get())
        self.assertIn('10 → 12tick', window.details.get())
        self.assertIn('維持費 10 → 20', window.details.get())
        self.assertNotIn('disabled', window.upgrade_button.state())
        for button in (window.purchase_button, window.upgrade_button, window.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), window.window.winfo_rootx()+window.window.winfo_width())
        funds = s.core.funds
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.upgrade_button.invoke()
        self.assertEqual(s.core.funds, funds)
        with patch('tkinter.messagebox.askyesno', return_value=True) as confirm:
            window.upgrade_button.invoke()
        self.assertIn('休業日も発生', confirm.call_args.args[1])
        self.assertIn('2段階目へ強化済み', window.details.get())
        self.assertIn('費用 1200', window.details.get())
        self.assertIn('日次運営費への追加：20', window.details.get())
        self.assertIn('disabled', window.upgrade_button.state())

    def test_locked_second_stage_and_main_log_finance(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.session()
        self.close(s); s.advance_goal(); s.next_day(); s.purchase_waiting_area()
        app = CafeInteractionWindow(root, s)
        app.show_waiting_area(); window = app.waiting_area_window
        self.assertIn('第2段階', window.notice.get())
        self.assertIn('disabled', window.upgrade_button.state())
        window.window.destroy()
        self.close(s); s.advance_goal(); s.next_day(); s.upgrade_waiting_area(); app.refresh()
        self.assertTrue(any('待合スペースを2段階目へ強化' in str(app.history.item(key,'values')) for key in app.history.get_children()))
        s.day_off(); app.show_history(); history = app.history_window
        row = history.days.get_children()[-1]
        self.assertEqual(history.days.set(row,'待合費用'), '1200')
        self.assertEqual(history.days.set(row,'運営費'), '80')
