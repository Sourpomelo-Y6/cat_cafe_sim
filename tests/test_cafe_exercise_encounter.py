"""運動教室だけの追加プログラムと、出発済み派遣の互換。"""
import copy
import os
import unittest
from unittest.mock import patch, PropertyMock

import test_cafe_exercise_dispatch as fixtures
from cat_cafe_sim.core.cafe_dispatch_unlocks import exercise_destination
from cat_cafe_sim.core.cafe_dispatch_encounters import for_destination, pending
from cat_cafe_sim.core.cafe_activities import destinations, reward
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.cafe_dispatch_results import result_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class ExerciseEncounterTests(unittest.TestCase):
    setUp = fixtures.ExerciseDispatchTests.setUp
    game = fixtures.ExerciseDispatchTests.game
    unlock = fixtures.ExerciseDispatchTests.unlock
    reload_replay = fixtures.ExerciseDispatchTests.reload_replay
    rejected = fixtures.ExerciseDispatchTests.rejected

    def depart(self):
        s = self.unlock(self.game())
        s.dispatch('cat-mugi', exercise_destination(s.core))
        return s, 'dispatch-2-cat-mugi'

    def test_exclusive_definition_and_existing_destination_choices_unchanged(self):
        s = self.game()
        row = for_destination(exercise_destination(s.core))
        self.assertEqual(row['id'], 'exercise_program')
        self.assertEqual([(r['id'], r['reward'], r['fatigue'], r['stress']) for r in row['choices']],
                         [('accept', 80, 10, 0), ('decline', 0, 0, 0)])
        self.assertIsNone(for_destination(destinations()[0]))
        self.assertEqual(for_destination(destinations()[1])['id'], 'extra_work')
        self.assertEqual(for_destination(destinations()[2])['id'], 'rest_stop')
        self.assertIsNone(for_destination(s.core.dispatch_trouble['destination']))

    def test_accept_decline_business_rest_pending_effects_return_and_replay(self):
        for choice in ('accept', 'decline'):
            for day_off in (False, True):
                with self.subTest(choice=choice, day_off=day_off):
                    s, event_id = self.depart()
                    s = self.reload_replay(s)
                    event = s.core.activities['events'][event_id]
                    self.assertEqual(event['encounter']['status'], 'scheduled')
                    if day_off:
                        s.day_off()
                    else:
                        while not s.core.closed: s.automatic_step()
                    event = s.core.activities['events'][event_id]
                    self.assertTrue(pending(event))
                    self.assertEqual(event['remaining'], 1)
                    self.assertEqual(event['encounter']['occurred_day'], 2)
                    for action in (s.day_off, s.next_day, s.automatic_step,
                                   lambda: s.set_shifts([]), lambda: s.resolve_activity(event_id)):
                        self.rejected(s, action)
                    s = self.reload_replay(s)
                    funds = s.core.funds
                    fatigue = s.core.cats['cat-mugi'].fatigue
                    stress = s.core.management['stress']['cat-mugi']
                    s.resolve_dispatch_choice(event_id, choice)
                    expected = 380 if choice == 'accept' else 300
                    self.assertEqual(s.core.funds, funds)
                    self.assertEqual(s.core.cats['cat-mugi'].fatigue, fatigue + (10 if choice == 'accept' else 0))
                    self.assertEqual(s.core.management['stress']['cat-mugi'], stress)
                    self.assertEqual(reward(s.core, s.core.activities['events'][event_id]), expected)
                    before = s.core.snapshot(); s.resolve_dispatch_choice(event_id, choice)
                    self.assertEqual(s.core.snapshot(), before)
                    self.rejected(s, lambda: s.resolve_dispatch_choice(event_id, 'decline' if choice == 'accept' else 'accept'))
                    s = self.reload_replay(s)
                    if s.core.closed: s.next_day()
                    s.day_off()
                    before = s.core.funds
                    s.resolve_activity(event_id)
                    self.assertEqual(s.core.funds, before + expected)
                    self.assertEqual(s.core.summary()['dispatch_income'], expected)
                    self.assertEqual(dict(result_rows(s.core, s.core.activities['events'][event_id]))['イベント増減'], '+80' if choice == 'accept' else '+0')
                    before = s.core.snapshot(); s.resolve_activity(event_id)
                    self.assertEqual(s.core.snapshot(), before)
                    s = self.reload_replay(s); s.day_off()
                    self.assertEqual(s.core.day_results[-1]['summary']['dispatch_income'], expected)
                    self.reload_replay(s)

    def test_departed_old_record_keeps_no_encounter_and_base_reward(self):
        s = self.unlock(self.game())
        # 更新前の出発操作は選択イベントなしで記録されている。
        s.core.dispatch('cat-mugi', exercise_destination(s.core))
        event_id = 'dispatch-2-cat-mugi'
        self.assertNotIn('encounter', s.core.activities['events'][event_id])
        s = self.reload_replay(s); s.day_off(); s.day_off()
        self.assertNotIn('encounter', s.core.activities['events'][event_id])
        funds = s.core.funds; s.resolve_activity(event_id)
        self.assertEqual(s.core.funds, funds + 300)
        self.reload_replay(s)

    def test_saved_choice_rules_remain_frozen_after_settings_change(self):
        s, event_id = self.depart()
        original = copy.deepcopy(s.core.activities['events'][event_id]['encounter']['rules'])
        with patch('cat_cafe_sim.core.cafe_dispatch_encounters.for_destination', side_effect=AssertionError('settings changed')):
            s = self.reload_replay(s); s.day_off()
            s = self.reload_replay(s); s.resolve_dispatch_choice(event_id, 'accept')
            s = self.reload_replay(s); s.day_off(); s.resolve_activity(event_id)
            self.assertEqual(s.core.activities['events'][event_id]['encounter']['rules'], original)
            self.assertEqual(reward(s.core, s.core.activities['events'][event_id]), 380)
            self.reload_replay(s)

    def test_save_failure_retry_preserves_single_fatigue_and_payment(self):
        s, event_id = self.depart(); s.day_off()
        s.resolve_dispatch_choice(event_id, 'accept')
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, s.checkpoint_path)
        s = self.reload_replay(s); s.resolve_dispatch_choice(event_id, 'accept')
        self.assertEqual(s.core.cats['cat-mugi'].fatigue, 10)
        s.day_off(); funds = s.core.funds; s.resolve_activity(event_id)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, s.checkpoint_path)
        s = self.reload_replay(s); s.resolve_activity(event_id)
        self.assertEqual(s.core.funds, funds + 380)
        self.reload_replay(s)

    def test_choice_with_other_return_waiting_and_unpersisted_results(self):
        s, event_id = self.depart()
        s.dispatch('cat-kohaku'); other = 'dispatch-2-cat-kohaku'
        s.day_off()
        with patch.object(type(s), 'pending', new_callable=PropertyMock, return_value={'pending'}):
            self.rejected(s, lambda: s.resolve_dispatch_choice(event_id, 'accept'), '保存を再試行')
        s.resolve_dispatch_choice(event_id, 'accept')
        self.rejected(s, s.day_off)
        s.resolve_activity(other)
        s.day_off(); s.resolve_activity(event_id)
        self.reload_replay(s)

    def test_corrupt_choice_date_and_effect_rejected(self):
        s, event_id = self.depart(); s.day_off(); s.resolve_dispatch_choice(event_id, 'accept')
        source = checkpoint(s.core, set())
        for change in (dict(choice='unknown'), dict(occurred_day=1), dict(resolved_day=99),
                       dict(changes=dict(fatigue_before=0, fatigue_after=7.5, stress_before=0, stress_after=0))):
            bad = copy.deepcopy(source)
            bad['state']['activities']['events'][event_id]['encounter'].update(change)
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError): restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
class ExerciseEncounterWindowTests(unittest.TestCase):
    setUp = fixtures.ExerciseDispatchTests.setUp
    game = fixtures.ExerciseDispatchTests.game
    unlock = fixtures.ExerciseDispatchTests.unlock

    def test_preview_wait_close_answer_effects_and_result(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.unlock(self.game())
        app = CafeInteractionWindow(root, s)
        app.activity_button.invoke(); activity = app.activity_window
        index = next(i for i, row in enumerate(activity.destinations) if row['id']=='cat_exercise_class')
        activity.destination_choice.current(index); activity.select_destination()
        activity.cats.selection_set('cat-mugi'); activity.buttons()
        with patch('tkinter.messagebox.askyesno', return_value=False) as confirm:
            activity.send_button.invoke()
        self.assertIn('1日目終了時に選択イベント', confirm.call_args.args[1])
        self.assertIn('追加の運動プログラム', confirm.call_args.args[1])
        with patch('tkinter.messagebox.askyesno', return_value=True): activity.send_button.invoke()
        s.day_off(); app.refresh(); activity.refresh()
        event_id = 'dispatch-2-cat-mugi'
        activity.events.selection_set(event_id); activity.buttons()
        self.assertEqual(activity.receive_button['text'], '出来事に回答…')
        activity.receive_button.invoke(); child = activity.choice_window
        child.window.geometry('560x360'); root.update()
        self.assertIn('帰還報酬 +80 / 疲労 +10', child.buttons['accept']['text'])
        self.assertIn('帰還報酬 +0 / 疲労 +0', child.buttons['decline']['text'])
        child.close(); root.update()
        self.assertTrue(pending(s.core.activities['events'][event_id]))
        self.assertIs(activity.window.grab_current(), activity.window)
        activity.receive_button.invoke(); child = activity.choice_window
        child.buttons['accept'].invoke(); root.update()
        self.assertIn('疲労 0 → 10', child.notice.get())
        self.assertIn('帰還報酬：380', child.notice.get())
        self.assertTrue(child.buttons['accept'].instate(['disabled']))
        self.assertTrue(child.buttons['decline'].instate(['disabled']))
        self.assertLessEqual(child.buttons['decline'].winfo_rooty()+child.buttons['decline'].winfo_height(),
                             child.window.winfo_rooty()+child.window.winfo_height())
        child.close(); s.day_off(); activity.refresh()
        activity.events.selection_set(event_id); activity.buttons(); activity.receive_button.invoke()
        activity.result_button.invoke(); root.update()
        self.assertIn('イベント増減：+80', activity.result_text.get('1.0', 'end'))
        self.assertIn('資金報酬合計：380', activity.result_text.get('1.0', 'end'))
