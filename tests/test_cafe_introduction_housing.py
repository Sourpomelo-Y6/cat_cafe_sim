"""紹介回答待ちの拡張、再判定とモーダル画面の回帰検証。"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_housing import capacity, reason
from cat_cafe_sim.core.cafe_activities import destinations
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class IntroductionHousingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def game(self, kind, *, legacy=False, simultaneous=False):
        selected = starting_conditions('free')
        for key in ('store_events', 'growth', 'dispatch_unlocks', 'customer_trust', 'customer_discontent'):
            selected.pop(key)
        selected['management']['starting_funds'] = 10000
        selected['management']['stress_per_service_tick'] = 0
        selected['profiles']['cats']['sixth'] = copy.deepcopy(selected['profiles']['cats']['cat-mugi'])
        if kind != 'regular':
            selected.pop('regular_introduction')
        else:
            selected['customer_loyalty'] = dict(gain=25, threshold=25)
        if kind == 'intake' or simultaneous:
            selected['intake_request']['day'] = 2 if kind == 'intake' else 3
        else:
            selected.pop('intake_request')
        if legacy:
            selected.pop('housing')
        s = create_game(Path(self.temp.name) / 'games', selected)
        event_id = None
        if kind == 'intake':
            s.day_off()
        elif kind == 'regular':
            while not s.core.closed:
                s.automatic_step()
            s.next_day()
        else:
            s.dispatch('cat-mike', destinations()[1])
            event_id = 'dispatch-1-cat-mike'
            s.day_off()
            s.resolve_dispatch_choice(event_id, 'decline')
            s.day_off()
        return s, event_id

    def offered(self, kind, **kwargs):
        s, event_id = self.game(kind, **kwargs)
        if kind == 'dispatch':
            s.resolve_activity(event_id)
        return s, event_id

    def data(self, s, kind, event_id):
        if kind == 'dispatch':
            return s.core.activities['events'][event_id]['introduction']
        return getattr(s.core, 'intake_request' if kind == 'intake' else 'regular_introduction')

    def accept(self, s, kind, event_id):
        if kind == 'dispatch':
            s.resolve_dispatch_introduction(event_id, 'accept')
        elif kind == 'intake':
            s.resolve_intake_request('accept')
        else:
            s.resolve_regular_introduction('accept')

    def reload_replay(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        return loaded

    def test_all_introductions_expand_accept_finance_save_and_replay(self):
        for kind in ('intake', 'regular', 'dispatch'):
            with self.subTest(kind=kind):
                s, event_id = self.offered(kind)
                before = s.core.snapshot()
                with self.assertRaisesRegex(ValueError, '満員'):
                    self.accept(s, kind, event_id)
                self.assertEqual(before, s.core.snapshot())
                s = self.reload_replay(s)
                funds = s.core.funds
                self.assertEqual(reason(s.core), '')
                s.purchase_housing()
                self.assertEqual(capacity(s.core), 9)
                self.assertEqual(s.core.funds, funds - 500)
                self.assertEqual(self.data(s, kind, event_id)['status'], 'waiting')
                for action in (s.day_off, s.automatic_step, lambda: s.set_shifts([])):
                    with self.assertRaises(ValueError):
                        action()
                with self.assertRaises(ValueError):
                    s.purchase_housing()
                s = self.reload_replay(s)
                self.accept(s, kind, event_id)
                self.assertEqual(len(s.core.cats), 7)
                self.assertEqual(s.core.funds, funds - 700)
                s = self.reload_replay(s)
                s.day_off()
                summary = s.core.day_results[-1]['summary']
                self.assertEqual(summary['housing_expenses'], 500)
                self.assertEqual(summary['recruitment_expenses'], 200)
                self.assertEqual(summary['operating_cost'], 80)
                s = self.reload_replay(s)
                s.day_off()
                self.assertEqual(s.core.day_results[-1]['summary']['housing_expenses'], 0)
                self.reload_replay(s)

    def test_simultaneous_intake_and_dispatch_can_expand_once(self):
        s, event_id = self.offered('dispatch', simultaneous=True)
        funds = s.core.funds
        s.purchase_housing()
        s.resolve_intake_request('accept')
        with self.assertRaises(ValueError):
            s.day_off()
        s.resolve_dispatch_introduction(event_id, 'accept')
        self.assertEqual(len(s.core.cats), 8)
        self.assertEqual(s.core.funds, funds - 900)
        self.reload_replay(s)

    def test_return_confirmation_still_blocks_expansion(self):
        s, event_id = self.game('dispatch')
        before = s.core.snapshot()
        with self.assertRaises(ValueError):
            s.purchase_housing()
        self.assertEqual(before, s.core.snapshot())
        s.resolve_activity(event_id)
        s.purchase_housing()
        self.reload_replay(s)

    def test_save_failure_retry_never_charges_expansion_twice(self):
        s, event_id = self.offered('regular')
        funds = s.core.funds
        s.purchase_housing()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_game(s, s.checkpoint_path)
        s = self.reload_replay(s)
        self.assertEqual(s.core.funds, funds - 500)
        with self.assertRaises(ValueError):
            s.purchase_housing()
        self.accept(s, 'regular', event_id)
        self.reload_replay(s)

    def test_remaining_funds_and_pending_results_rechecked(self):
        for kind in ('intake', 'regular', 'dispatch'):
            with self.subTest(kind=kind):
                s, event_id = self.offered(kind)
                with patch.object(type(s), 'pending', new_callable=unittest.mock.PropertyMock, return_value={'pending': {}}):
                    before = s.core.snapshot()
                    with self.assertRaises(ValueError):
                        s.purchase_housing()
                    self.assertEqual(s.core.snapshot(), before)
                s.core.funds = 700
                s.purchase_housing()
                before = s.core.snapshot()
                with self.assertRaisesRegex(ValueError, '資金'):
                    self.accept(s, kind, event_id)
                self.assertEqual(s.core.snapshot(), before)

    def test_legacy_pending_introductions_keep_unlimited_capacity(self):
        for kind in ('intake', 'regular', 'dispatch'):
            with self.subTest(kind=kind):
                s, event_id = self.offered(kind, legacy=True)
                with self.assertRaisesRegex(ValueError, '従来ルール'):
                    s.purchase_housing()
                self.accept(s, kind, event_id)
                self.assertEqual(len(s.core.cats), 7)
                self.assertIsNone(capacity(s.core))
                self.reload_replay(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
class IntroductionHousingWindowTests(unittest.TestCase):
    setUp = IntroductionHousingTests.setUp
    game = IntroductionHousingTests.game
    offered = IntroductionHousingTests.offered

    def window(self, root, s, kind, event_id):
        from cat_cafe_sim.cafe_intake_request_gui import CafeIntakeRequestWindow
        from cat_cafe_sim.cafe_regular_introduction_gui import CafeRegularIntroductionWindow
        from cat_cafe_sim.cafe_dispatch_introduction_gui import CafeDispatchIntroductionWindow
        if kind == 'dispatch':
            return CafeDispatchIntroductionWindow(root, s, event_id, lambda: None)
        cls = CafeIntakeRequestWindow if kind == 'intake' else CafeRegularIntroductionWindow
        return cls(root, s, lambda: None)

    def test_three_windows_cancel_purchase_refresh_close_and_accept(self):
        import tkinter as tk
        root = tk.Tk()
        self.addCleanup(root.destroy)
        for kind in ('intake', 'regular', 'dispatch'):
            with self.subTest(kind=kind):
                s, event_id = self.offered(kind)
                owner = self.window(root, s, kind, event_id)
                owner.window.geometry('560x420'); root.update()
                self.assertTrue(owner.accept_button.instate(['disabled']))
                self.assertFalse(owner.housing_button.instate(['disabled']))
                for button in (owner.accept_button, owner.decline_button, owner.housing_button, owner.close_button):
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), owner.window.winfo_rootx() + owner.window.winfo_width())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), owner.window.winfo_rooty() + owner.window.winfo_height())
                owner.housing_button.invoke(); root.update()
                child = owner.housing_window
                before = s.core.snapshot()
                with patch('tkinter.messagebox.askyesno', return_value=False):
                    child.purchase_button.invoke()
                self.assertEqual(s.core.snapshot(), before)
                child.close_button.invoke(); root.update()
                self.assertIs(owner.window.grab_current(), owner.window)
                owner.housing_button.invoke(); root.update()
                child = owner.housing_window
                with patch('tkinter.messagebox.askyesno', return_value=True):
                    child.purchase_button.invoke()
                self.assertFalse(owner.accept_button.instate(['disabled']))
                self.assertTrue(owner.housing_button.instate(['disabled']))
                self.assertIn('上限 9匹', str([owner.details.item(key)['values'] for key in owner.details.get_children()]))
                child.window.focus_force(); root.update()
                child.window.event_generate('<Escape>'); root.update()
                self.assertFalse(child.window.winfo_exists())
                self.assertIs(owner.window.grab_current(), owner.window)
                with patch('tkinter.messagebox.askyesno', return_value=True):
                    owner.accept_button.invoke()
                self.assertEqual(len(s.core.cats), 7)
                owner.close_button.invoke(); root.update()

    def test_low_funds_and_legacy_buttons(self):
        import tkinter as tk
        root = tk.Tk(); self.addCleanup(root.destroy)
        for kind in ('intake', 'regular', 'dispatch'):
            with self.subTest(kind=kind):
                s, event_id = self.offered(kind)
                s.core.funds = 700
                owner = self.window(root, s, kind, event_id)
                owner.housing_button.invoke(); root.update()
                child = owner.housing_window
                with patch('tkinter.messagebox.askyesno', return_value=True):
                    child.purchase_button.invoke()
                child.close()
                self.assertTrue(owner.accept_button.instate(['disabled']))
                self.assertFalse(owner.decline_button.instate(['disabled']))
                self.assertIn('資金', owner.notice.get())
                owner.close_button.invoke()
                s, event_id = self.offered(kind, legacy=True)
                owner = self.window(root, s, kind, event_id)
                self.assertTrue(owner.housing_button.instate(['disabled']))
                self.assertFalse(owner.accept_button.instate(['disabled']))
                owner.close_button.invoke()
