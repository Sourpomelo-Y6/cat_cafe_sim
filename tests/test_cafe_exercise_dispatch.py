"""体力自慢向け派遣先の解放・参加・帰還と旧ルール互換。"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_activities import destinations, dispatch_reason
from cat_cafe_sim.core.cafe_dispatch_unlocks import EXERCISE_ID, exercise_destination, reason, rules
from cat_cafe_sim.core.cafe_traits import definitions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.cafe_dispatch_results import result_rows
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ExerciseDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def game(self, *, legacy=False, no_unlocks=False, threshold=100, seats=2, hardy=True, mode='free'):
        selected = starting_conditions(mode)
        for key in ('store_events', 'intake_request', 'regular_introduction', 'customer_trust', 'customer_discontent'):
            selected.pop(key)
        selected['growth']['threshold'] = 1000
        selected['management']['starting_funds'] = 10000
        selected['dispatch_unlocks'][EXERCISE_ID]['popularity'] = threshold
        selected['management']['stress_per_service_tick'] = 0
        selected['seat_count'] = seats
        if hardy:
            selected['traits']['cat-mugi'] = definitions()['hardy']
        if legacy:
            selected['dispatch_unlocks'].pop(EXERCISE_ID)
            selected['dispatch_unlocks'].pop('quiet_reading_salon')  # Original two-destination rules.
        if no_unlocks:
            selected.pop('dispatch_unlocks')
        return create_game(Path(self.temp.name) / 'games', selected)

    def unlock(self, s):
        s.dispatch('cat-kohaku'); event_id = f'dispatch-{s.core.day}-cat-kohaku'
        s.day_off()
        s.resolve_activity(event_id)
        return s

    def reload_replay(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        return loaded

    def rejected(self, s, action, message=None):
        before = s.core.snapshot()
        with self.assertRaisesRegex(ValueError, message or '.'):
            action()
        self.assertEqual(s.core.snapshot(), before)

    def test_default_destination_all_modes_and_initially_locked(self):
        for mode in ('free', 'popularity', 'bond', 'patron'):
            with self.subTest(mode=mode):
                s = self.game(mode=mode, threshold=120)
                row = exercise_destination(s.core)
                self.assertEqual((row['name'], row['days'], row['reward'], row['max_fatigue']),
                                 ('猫の運動教室', 2, 300, 40))
                self.assertIn(row, destinations(s.core))
                self.assertEqual(destinations(s.core)[:3], destinations())
                self.rejected(s, lambda: s.dispatch('cat-mugi', row), '未解放')
                self.reload_replay(s)

    def test_popularity_and_received_return_both_needed_and_unlock_persists(self):
        s = self.game(threshold=101)
        self.unlock(s)
        self.assertIn('100/101', reason(s.core, EXERCISE_ID))
        self.assertIn('1/1', reason(s.core, EXERCISE_ID))
        self.reload_replay(s)
        s = self.game()
        s.dispatch('cat-kohaku'); s.day_off()
        self.assertNotIn(EXERCISE_ID, s.core.dispatch_unlocks['unlocked'])
        s.resolve_activity('dispatch-1-cat-kohaku')
        self.assertEqual(s.core.dispatch_unlocks['unlocked'][EXERCISE_ID], dict(day=2, popularity=100, returns=1))
        self.assertEqual(sum(e['kind']=='dispatch_destination_unlocked' and e['destination_id']==EXERCISE_ID for e in s.core.events), 1)
        before = s.core.snapshot(); s.resolve_activity('dispatch-1-cat-kohaku')
        self.assertEqual(s.core.snapshot(), before)
        self.reload_replay(s)
        lowered = copy.deepcopy(s.core); lowered.management['popularity'] = 1
        self.assertEqual(reason(lowered, EXERCISE_ID), '')
        # 既定の人気120も、実際の接客成果から到達して解放する。
        s = self.game(threshold=120)
        for _ in range(10):
            while not s.core.closed: s.automatic_step()
            s.next_day()
            if s.core.management['popularity'] >= 120: break
        self.assertGreaterEqual(s.core.management['popularity'], 120)
        self.assertNotIn(EXERCISE_ID, s.core.dispatch_unlocks['unlocked'])
        self.unlock(s)
        self.assertEqual(reason(s.core, EXERCISE_ID), '')
        self.reload_replay(s)


    def test_trait_id_fatigue_health_and_surplus_conditions(self):
        s = self.unlock(self.game()); row = exercise_destination(s.core)
        self.rejected(s, lambda: s.dispatch('cat-mike', row), '体力自慢')
        core = copy.deepcopy(s.core)
        core.traits['cat-mike']['name'] = '体力自慢'
        self.assertIn('体力自慢', dispatch_reason(core, 'cat-mike', row))
        core.cats['cat-mugi'].fatigue = 40
        self.assertEqual(dispatch_reason(core, 'cat-mugi', row), '')
        core.cats['cat-mugi'].fatigue = 40.01
        self.assertIn('疲労40以下', dispatch_reason(core, 'cat-mugi', row))
        core.cats['cat-mugi'].fatigue = 0
        core.cats['cat-mugi'].health_status = 'sick'
        self.assertIn('健康', dispatch_reason(core, 'cat-mugi', row))
        core.cats['cat-mugi'].health_status = 'healthy'
        for key in ('cat-mike', 'cat-tama', 'cat-sora'):
            core.cats[key].stamina = 0
        self.assertIn('席数を超える', dispatch_reason(core, 'cat-mugi', row))
        with patch.object(type(s), 'pending', new_callable=PropertyMock, return_value={'pending'}):
            self.rejected(s, lambda: s.dispatch('cat-mugi', row), '未保存')
        self.rejected(s, lambda: s.dispatch('cat-mugi', dict(row, reward=999)), '開始時の設定')

    def test_two_days_return_finance_growth_save_replay_and_no_double_receipt(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.unlock(self.game(seats=seats)); row = exercise_destination(s.core)
                funds = s.core.funds
                s.dispatch('cat-mugi', row); event_id = 'dispatch-2-cat-mugi'
                self.rejected(s, lambda: s.dispatch('cat-mugi', row), '在店')
                event = s.core.activities['events'][event_id]
                for field in ('trouble', 'introduction', 'item_reward'):
                    self.assertNotIn(field, event)
                self.assertEqual(dict(result_rows(s.core, event))['基本報酬'], '300')
                s = self.reload_replay(s); s.day_off()
                self.assertEqual(s.core.activities['events'][event_id]['remaining'], 1)
                self.assertEqual(s.core.activity('cat-mugi'), 'dispatched')
                s = self.reload_replay(s)
                s.resolve_dispatch_choice(event_id, 'decline')
                s.day_off()
                self.assertEqual(s.core.activities['events'][event_id]['status'], 'waiting')
                self.rejected(s, s.day_off)
                s = self.reload_replay(s)
                before = s.core.funds
                s.resolve_activity(event_id)
                self.assertEqual(s.core.funds, before + 300)
                self.assertEqual(s.core.funds, funds - 2*(40+seats*10) + 300)
                self.assertEqual(s.core.summary()['dispatch_income'], 300)
                self.assertEqual(s.core.growth['cats']['cat-mugi']['dispatch'], s.core.growth['rules']['dispatch_xp'])
                self.assertNotIn('cat-mugi', s.core.working_cats)
                before = s.core.snapshot(); s.resolve_activity(event_id)
                self.assertEqual(s.core.snapshot(), before)
                self.assertEqual(dict(result_rows(s.core, s.core.activities['events'][event_id]))['状態'], '受取済み')
                s = self.reload_replay(s); s.day_off()
                self.assertEqual(s.core.day_results[-1]['summary']['dispatch_income'], 300)
                self.reload_replay(s)

    def test_new_rescue_sora_can_participate(self):
        s = self.unlock(self.game(hardy=False))
        s.open_recruitment()
        for _ in range(3): s.day_off()
        s.open_recruitment()
        key = next(key for key, row in s.core.recruitment['candidates'].items() if row['trait']['id']=='hardy')
        s.recruit_cat(key)
        s.dispatch(key, exercise_destination(s.core))
        self.reload_replay(s)

    def test_business_day_and_rest_day_advance_same_dispatch(self):
        s = self.unlock(self.game())
        s.dispatch('cat-mugi', exercise_destination(s.core))
        while not s.core.closed: s.automatic_step()
        self.assertEqual(s.core.activities['events']['dispatch-2-cat-mugi']['remaining'], 1)
        s = self.reload_replay(s)
        s.resolve_dispatch_choice('dispatch-2-cat-mugi', 'decline')
        s.next_day(); s.day_off()
        s.resolve_activity('dispatch-2-cat-mugi')
        self.reload_replay(s)

    def test_old_two_destination_rules_and_absent_rules_keep_old_destinations(self):
        for no_unlocks in (False, True):
            s = self.game(legacy=True, no_unlocks=no_unlocks)
            self.assertIsNone(exercise_destination(s.core))
            self.assertNotIn(EXERCISE_ID, [row['id'] for row in destinations(s.core)])
            self.rejected(s, lambda: s.dispatch('cat-mugi', rules()[EXERCISE_ID]['destination']), '設定がありません')
            s.dispatch('cat-kohaku')
            saved = copy.deepcopy(s.core.activities['events']['dispatch-1-cat-kohaku'])
            s = self.reload_replay(s)
            self.assertEqual(saved, s.core.activities['events']['dispatch-1-cat-kohaku'])
            if s.core.dispatch_unlocks:
                self.assertNotIn(EXERCISE_ID, s.core.dispatch_unlocks['rules'])

    def test_saved_destination_and_unlock_conditions_are_frozen_and_retry_safe(self):
        s = self.unlock(self.game())
        row = exercise_destination(s.core)
        s.dispatch('cat-mugi', row)
        s.day_off(); s.resolve_dispatch_choice('dispatch-2-cat-mugi', 'decline')
        s.day_off(); s.resolve_activity('dispatch-2-cat-mugi')
        funds = s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, s.checkpoint_path)
        with patch('cat_cafe_sim.core.cafe_dispatch_unlocks.rules', wraps=rules) as reader:
            s = self.reload_replay(s)
            self.assertTrue(all(call.args and call.args[0] is not None for call in reader.call_args_list))
            self.assertEqual(exercise_destination(s.core), row)
        s.resolve_activity('dispatch-2-cat-mugi')
        self.assertEqual(s.core.funds, funds)

    def test_invalid_unlock_settings_and_saved_destination_rejected(self):
        source = rules()
        for mutate in (lambda d: d[EXERCISE_ID].pop('destination'),
                       lambda d: d[EXERCISE_ID]['destination'].update(required_trait='hospitality'),
                       lambda d: d[EXERCISE_ID]['destination'].update(days=0),
                       lambda d: d[EXERCISE_ID].update(returns=True)):
            bad = copy.deepcopy(source); mutate(bad)
            with self.assertRaises(ValueError): rules(bad)
        s = self.unlock(self.game()); s.dispatch('cat-mugi', exercise_destination(s.core))
        source = checkpoint(s.core, set())
        for mutate in (lambda d: d['state']['activities']['events']['dispatch-2-cat-mugi']['destination'].update(reward=999),
                       lambda d: d['state']['dispatch_unlocks']['rules'].pop(EXERCISE_ID),
                       lambda d: d['state'].pop('dispatch_unlocks')):
            bad = copy.deepcopy(source); mutate(bad)
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError): restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
class ExerciseDispatchWindowTests(unittest.TestCase):
    setUp = ExerciseDispatchTests.setUp
    game = ExerciseDispatchTests.game
    unlock = ExerciseDispatchTests.unlock

    def test_conditions_cancel_dispatch_return_and_result_at_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game()
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        app = CafeInteractionWindow(root, s)
        window = CafeActivityWindow(root, s, lambda: None, show_navigation=False)
        index = next(i for i, row in enumerate(window.destinations) if row['id']==EXERCISE_ID)
        window.destination_choice.current(index); window.select_destination()
        self.assertIn('未解放', window.destination_info.get())
        window.cats.selection_set('cat-mugi'); window.buttons()
        self.assertTrue(window.send_button.instate(['disabled']))
        self.unlock(s); app.refresh(); window.refresh()
        self.assertTrue(any('派遣先を解放：猫の運動教室' in str(app.history.item(key)['values'])
                            for key in app.history.get_children()))
        window.window.geometry('500x400'); root.update()
        self.assertIn('2日', window.destination_info.get())
        self.assertIn('体力自慢', window.destination_info.get())
        window.cats.selection_set('cat-mike'); window.buttons()
        self.assertTrue(window.send_button.instate(['disabled']))
        window.cats.selection_set('cat-mugi'); window.buttons()
        self.assertIn('300', window.selection_info.get())
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False): window.send_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        with patch('tkinter.messagebox.askyesno', return_value=True): window.send_button.invoke()
        event_id = 'dispatch-2-cat-mugi'
        s.day_off(); s.resolve_dispatch_choice(event_id, 'decline')
        s.day_off(); window.refresh()
        window.events.selection_set(event_id); window.buttons()
        window.receive_button.invoke()
        self.assertEqual(s.core.activities['events'][event_id]['status'], 'resolved')
        window.result_button.invoke(); root.update()
        self.assertIn('資金報酬合計：300', window.result_text.get('1.0', 'end'))
        self.assertLessEqual(window.close_button.winfo_rooty()+window.close_button.winfo_height(),
                             window.window.winfo_rooty()+window.window.winfo_height())
