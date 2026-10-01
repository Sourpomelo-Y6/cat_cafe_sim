import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.storage.cafe_saves import load_game


class GoalStopTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp
    session = fixtures.AutoPlayTests.session

    def test_each_stage_stops_before_advancing_and_preserves_pending_result(self):
        s = self.session()
        for stage in range(3):
            result = AutoPlayer(s, stop_on_goal=True).run()
            self.assertEqual(result.reason, 'completed' if stage==2 else 'goal_cleared')
            self.assertEqual(len(s.core.goal['history']), stage)
            self.assertFalse(s.core.goal['continued'])
            self.assertEqual(s.core.goal['status'], 'cleared')
            if stage<2:
                s.advance_goal()
                s.next_day()


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1', 'requires a display')
class AutoPlayGuiTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp
    session = fixtures.AutoPlayTests.session

    def app(self, **kwargs):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = CafeInteractionWindow(root, self.session(**kwargs))
        self.addCleanup(app.stop)
        root.update()
        return app

    def dialog(self, app):
        app.show_autoplay()
        dialog = app.autoplay_window
        dialog.interval_ms = 0
        return dialog

    def finish(self, app, dialog):
        deadline = time.monotonic()+15
        while dialog.running and time.monotonic()<deadline:
            app.root.update()
        self.assertFalse(dialog.running)
        self.assertIsNone(dialog.timer)

    def test_ten_days_yields_to_ui_and_restores_normal_operation(self):
        app = self.app(days=30, target=290, stages=False)
        dialog = self.dialog(app)
        ping = []
        dialog.start()
        app.root.after(0, lambda: ping.append(True))
        self.finish(app, dialog)
        self.assertTrue(ping)
        self.assertEqual(dialog.player.result.reason, 'day_limit')
        self.assertIn('10 / 10日', dialog.progress.get())
        self.assertIn('資金', dialog.summary.get())
        self.assertIn('疲労', dialog.summary.get())
        self.assertIn('基礎営業', dialog.log.get('1.0', 'end'))
        self.assertEqual(len(app.session.core.goal['days']), 10)
        saved = load_game(app.session.checkpoint_path)[0]
        self.assertEqual(saved.core.snapshot(), app.session.core.snapshot())
        dialog.close()
        self.assertIsNone(app.autoplay_window)
        self.assertTrue(app.day_button.instate(['!disabled']))
        app.session.next_day()
        app.refresh()
        self.assertTrue(app.run_button.instate(['!disabled']))

    def test_clear_mode_stops_at_first_stage_and_uses_result_screen(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.mode.set('クリアを目指す')
        dialog.start()
        self.finish(app, dialog)
        self.assertEqual(dialog.player.mode, 'clear')
        self.assertEqual(dialog.player.result.reason, 'goal_cleared')
        self.assertEqual(app.session.core.goal['history'], [])
        self.assertIsNotNone(app.session.core.rest_space)
        self.assertTrue(dialog.start_button.instate(['disabled']))
        self.assertIn('段階を達成', dialog.progress.get())
        dialog.close()
        app.show_goal()
        app.goal_window.window.destroy()

    def test_decision_table_purchase_forecasts_details_and_small_window(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.mode.set('クリアを目指す')
        dialog.start()
        self.finish(app, dialog)
        rows = [dialog.decision_table.item(item, 'values') for item in dialog.decision_table.get_children()]
        self.assertTrue(any(row[1]=='休養スペース' and row[2]=='購入' and '予備資金' in row[3] for row in rows))
        for key in app.session.core.cats:
            cats = [row for row in rows if row[0]=='1' and row[1]==key]
            self.assertEqual(len(cats), 1)
            self.assertIn('出勤時の予測', cats[0][3])
        item = dialog.decision_table.get_children()[0]
        before = app.session.core.snapshot()
        dialog.decision_table.selection_set(item)
        dialog.window.geometry('600x480')
        app.root.update()
        self.assertIn('予備資金', dialog.decision_detail.get('1.0', 'end'))
        self.assertGreater(dialog.decision_table.winfo_height(), 50)
        self.assertGreater(dialog.decision_detail.winfo_height(), 20)
        dialog.tabs.select(1)
        app.root.update()
        self.assertIn('クリアを目指す', dialog.log.get('1.0', 'end'))
        self.assertEqual(app.session.core.snapshot(), before)

    def test_basic_decisions_remain_after_cancel_and_reset_on_restart(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.start()
        dialog.window.after_cancel(dialog.timer)
        dialog.timer = None
        dialog.interval_ms = 10000
        dialog.advance()
        dialog.stop()
        rows = [dialog.decision_table.item(item, 'values') for item in dialog.decision_table.get_children()]
        self.assertTrue(any('現在の疲労' in row[3] for row in rows))
        self.assertTrue(all(row[4]=='実行済み' for row in rows))
        dialog.start()
        self.assertEqual(dialog.decision_table.get_children(), ())
        dialog.stop()

    def test_failed_purchase_appears_in_decision_table(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.mode.set('クリアを目指す')
        dialog.start()
        with patch.object(app.session, 'purchase_rest_space', side_effect=OSError('disk error')):
            self.finish(app, dialog)
        rows = [dialog.decision_table.item(item, 'values') for item in dialog.decision_table.get_children()]
        self.assertEqual(len(rows), 1)
        self.assertIn('失敗', rows[0][4])
        self.assertEqual(dialog.player.result.reason, 'blocked')

    def test_cancel_after_purchase_saves_and_reopen_can_resume(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.mode.set('クリアを目指す')
        dialog.start()
        dialog.window.after_cancel(dialog.timer)
        dialog.timer = None
        dialog.interval_ms = 10000
        dialog.advance()
        self.assertIsNotNone(app.session.core.rest_space)
        self.assertTrue(dialog.selector.instate(['disabled']))
        dialog.stop()
        self.assertEqual(dialog.player.result.reason, 'cancelled')
        before = app.session.core.snapshot()
        app.root.update()
        self.assertEqual(app.session.core.snapshot(), before)
        saved = load_game(app.session.checkpoint_path)[0]
        self.assertEqual(saved.core.snapshot(), before)
        dialog.close()
        app.replace_game(saved)
        resumed = self.dialog(app)
        resumed.mode.set('クリアを目指す')
        resumed.start()
        self.finish(app, resumed)
        self.assertEqual(resumed.player.result.reason, 'goal_cleared')
        self.assertTrue(any('終了' in line for line in resumed.lines))

    def test_expiry_and_game_over_stop_and_disabled_start(self):
        app = self.app(days=1, target=290, stages=False)
        dialog = self.dialog(app)
        dialog.start()
        self.finish(app, dialog)
        self.assertEqual(dialog.player.result.reason, 'expired')
        self.assertTrue(dialog.start_button.instate(['disabled']))
        dialog.close()
        second = self.session('broke', funds=1, target=290, stages=False)
        from cat_cafe_sim.core.cafe_operating_cost import rules
        second.core.initialize_operating_cost(dict(rules(), base_cost=100000))
        app.replace_game(second)
        dialog = self.dialog(app)
        dialog.start()
        self.finish(app, dialog)
        self.assertEqual(dialog.player.result.reason, 'game_over')
        self.assertTrue(app.autoplay_button.instate(['disabled']))

    def test_close_and_replace_cancel_all_callbacks(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.start()
        before = app.session.core.snapshot()
        dialog.close()
        app.root.update()
        self.assertEqual(app.session.core.snapshot(), before)
        other = self.session('other')
        dialog = self.dialog(app)
        dialog.start()
        app.replace_game(other)
        app.root.update()
        self.assertIsNone(app.autoplay_window)
        self.assertIs(app.session, other)
        self.assertEqual(other.core.tick, 0)

    def test_export_log_protects_save_and_reports_save_failure(self):
        app = self.app()
        dialog = self.dialog(app)
        dialog.start()
        with patch('cat_cafe_sim.storage.cafe_saves.save_game', side_effect=OSError('disk error')):
            dialog.stop()
        self.assertIn('保存に失敗', dialog.summary.get())
        destination = Path(self.temp.name)/'operations.txt'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)):
            dialog.save_log()
        self.assertIn('基礎営業', destination.read_text())
        before = app.session.checkpoint_path.read_bytes()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(app.session.checkpoint_path)), patch('tkinter.messagebox.showerror') as error:
            dialog.save_log()
        error.assert_called_once()
        self.assertEqual(before, app.session.checkpoint_path.read_bytes())
