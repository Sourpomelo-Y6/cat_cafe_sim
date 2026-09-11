from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core.human_cat_interaction import HumanCatInteraction, InteractionConfig, verify
from cat_cafe_sim.human_cat_gui import PlaySession, history_row


class PlaySessionTests(unittest.TestCase):
    def test_gui_session_matches_cli_core_and_replay(self):
        config = InteractionConfig.load()
        ui = PlaySession(config)
        cli = HumanCatInteraction(config)
        for action in ('direct', 'direct', 'pause', 'feint', 'switch', 'adapt'):
            self.assertEqual(ui.act(action), cli.step(action))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'play.json'
            ui.save(path)
            self.assertEqual(verify(path).log(), cli.log())

    def test_restart_validates_before_replacing_and_clears_history(self):
        ui = PlaySession(InteractionConfig())
        ui.act('direct')
        old = ui.core.log()
        for values in (('abc', '1', '100'), ('nan', '1', '100'), ('1', '3', '100'), ('1', '1', '0')):
            with self.assertRaises(ValueError):
                ui.restart(*values)
            self.assertEqual(ui.core.log(), old)
        ui.restart('0', '2', '20')
        self.assertEqual(ui.core.records, [])
        self.assertEqual(ui.core.state['stamina'], 20)
        self.assertEqual(ui.act('direct')['reaction'], 'turn_away')

    def test_japanese_history_and_end(self):
        ui = PlaySession(InteractionConfig(ticks=1))
        record = ui.act('direct')
        self.assertEqual(history_row(record)[:3], (1, '素直に動かす', '好意的に応じる'))
        self.assertEqual(ui.core.valid_actions(), ())


# デスクトップ環境で明示的に有効化するウィジェット検証。
import os
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.human_cat_gui import InteractionWindow
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = InteractionWindow(self.root, InteractionConfig(ticks=3))
        self.root.update_idletasks()

    def test_buttons_history_restart_and_end(self):
        app = self.app
        app.buttons['switch'].invoke()
        self.assertTrue(app.buttons['intense'].instate(['disabled']))
        app.buttons['intense'].invoke()
        self.assertEqual(len(app.session.core.records), 1)
        app.buttons['direct'].invoke()
        app.buttons['pause'].invoke()
        self.assertTrue(all(b.instate(['disabled']) for b in app.buttons.values()))
        self.assertEqual(len(app.history.get_children()), 3)
        self.assertIn('時間になり', app.reaction.get())
        app.play.set('0')
        app.pet.set('2')
        app.stamina.set('20')
        app.restart()
        self.assertEqual(app.history.get_children(), ())
        self.assertEqual(app.session.core.config.preferences, (0, 2))
        self.assertTrue(all(b.instate(['!disabled']) for b in app.buttons.values()))
        before = app.session.core.log()
        app.stamina.set('nan')
        with patch('tkinter.messagebox.showerror') as error:
            app.restart()
            error.assert_called_once()
        self.assertEqual(app.session.core.log(), before)

    def test_save_cancel_success_and_io_error(self):
        app = self.app
        app.buttons['direct'].invoke()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''), patch.object(app.session, 'save') as save:
            app.save_log()
            save.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'ui.json')
            with patch('tkinter.filedialog.asksaveasfilename', return_value=path):
                app.save_log()
            self.assertEqual(verify(path).log(), app.session.core.log())
        with patch('tkinter.filedialog.asksaveasfilename', return_value='/unused.json'), \
                patch.object(app.session, 'save', side_effect=OSError('test error')), \
                patch('tkinter.messagebox.showerror') as error:
            app.save_log()
            error.assert_called_once()


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class SpecialWindowTests(unittest.TestCase):
    def test_special_reservations_buttons_history_and_save(self):
        import tkinter as tk
        from cat_cafe_sim.human_cat_gui import InteractionWindow
        from cat_cafe_sim.core.human_cat_special import SpecialConfig, SpecialInteraction
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = InteractionWindow(root, SpecialConfig())
        self.assertTrue(app.buttons['connect'].instate(['disabled']))
        app.session.core = SpecialInteraction(tension=100, engagement=80)
        app.refresh()
        root.update_idletasks()
        self.assertTrue(app.buttons['connect'].instate(['!disabled']))
        self.assertTrue(app.buttons['direct'].instate(['disabled']))
        self.assertIn('心をつかむ',app.special_status.get())
        app.buttons['connect'].invoke()
        self.assertIn('200',app.special_status.get())
        self.assertIn('心を開く',app.reaction.get())
        self.assertTrue(all(b.instate(['disabled']) for b in app.buttons.values()))
        self.assertEqual(len(app.history.item(app.history.get_children()[0])['values']),7)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'special.json')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=path):
                app.save_log()
            self.assertEqual(verify(path).log(), app.session.core.log())
        app.restart()
        self.assertEqual(app.session.core.state['bonus_funds'],0)
        self.assertEqual(app.session.core.state['tension'],0)
