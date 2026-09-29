import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_housing import admission_reason, capacity, count, reason, rules
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class HousingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def game(self, legacy=False, intake=False, seats=2, weekdays=True):
        selected = starting_conditions('free')
        selected['seat_count'] = seats
        selected.pop('store_events')
        selected.pop('growth')
        if legacy:
            selected.pop('housing')
        if not intake:
            selected.pop('intake_request')
        if not weekdays:
            for key in ('weekdays', 'customer_satisfaction', 'customer_loyalty', 'customer_discontent', 'customer_trust'):
                selected.pop(key)
        return create_game(Path(self.temp.name) / 'games', selected)

    def reload(self, session):
        save_game(session, session.checkpoint_path)
        loaded, _ = load_game(session.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
        return loaded

    def replay(self, session):
        self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(), session.core.snapshot())

    def test_purchase_same_day_cost_rest_day_save_and_replay(self):
        for seats, weekdays in ((1, False), (2, True)):
            with self.subTest(seats=seats):
                s = self.reload(self.game(seats=seats, weekdays=weekdays))
                self.assertEqual(capacity(s.core), 6)
                s.purchase_housing()
                self.assertEqual(s.core.funds, 500)
                self.assertEqual(capacity(s.core), 9)
                self.assertEqual(len(s.core.seats) if hasattr(s.core, 'seats') else 1, seats)
                self.assertIn('拡張済み', reason(s.core))
                before = s.core.snapshot()
                with self.assertRaises(ValueError):
                    s.purchase_housing()
                self.assertEqual(s.core.snapshot(), before)
                self.replay(s)
                s = self.reload(s)
                s.day_off()
                summary = s.core.day_results[-1]['summary']
                self.assertEqual(summary['housing_expenses'], 500)
                self.assertEqual(summary['operating_cost'], 40 + seats*10 + 20)
                self.assertEqual(summary['total_expenses'], 500 + summary['operating_cost'])
                s = self.reload(s)
                self.replay(s)
                s.day_off()
                self.assertEqual(s.core.day_results[-1]['summary']['housing_expenses'], 0)
                self.reload(s)

    def test_full_roster_blocks_registration_then_purchase_allows_join(self):
        s = self.game()
        s.open_recruitment()
        keys = list(s.core.recruitment['candidates'])
        s.recruit_cat(keys[0])
        self.assertEqual(count(s.core), 6)
        before = s.core.snapshot()
        with patch.object(s.store, '_write', side_effect=AssertionError('unexpected registration')):
            with self.assertRaisesRegex(ValueError, '満員'):
                s.recruit_cat(keys[1])
        self.assertEqual(s.core.snapshot(), before)
        s.purchase_housing()
        s.recruit_cat(keys[1])
        self.assertEqual(count(s.core), 7)
        self.reload(s)
        self.replay(s)

    def test_full_intake_decline_unblocks_and_remains_saved(self):
        s = self.game(intake=True)
        s.open_recruitment()
        s.recruit_cat(next(iter(s.core.recruitment['candidates'])))
        for _ in range(3):
            s.day_off()
        s = self.reload(s)
        before = s.core.snapshot()
        with patch.object(s.store, '_write', side_effect=AssertionError('unexpected registration')):
            with self.assertRaisesRegex(ValueError, '満員'):
                s.resolve_intake_request('accept')
        self.assertEqual(s.core.snapshot(), before)
        with self.assertRaises(ValueError):
            s.purchase_housing()
        s.resolve_intake_request('decline')
        self.assertEqual(s.core.funds, before['funds'])
        s.day_off()
        self.reload(s)
        self.replay(s)

    def test_purchase_before_intake_allows_seventh_cat(self):
        # Use a smaller purchase price for this scenario; rules remain fixed in the save.
        selected = starting_conditions('free')
        selected.pop('store_events'); selected.pop('growth')
        selected['housing']['cost'] = 100
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.open_recruitment()
        s.recruit_cat(next(iter(s.core.recruitment['candidates'])))
        s.purchase_housing()
        for _ in range(3):
            s.day_off()
        s.resolve_intake_request('accept')
        self.assertEqual(count(s.core), 7)
        self.reload(s)
        self.replay(s)

    def test_legacy_more_than_six_cats_and_original_admission_preserved(self):
        s = self.game(legacy=True)
        s.open_recruitment()
        for key in list(s.core.recruitment['candidates'])[:2]:
            s.recruit_cat(key)
        self.assertEqual(count(s.core), 7)
        self.assertIsNone(capacity(s.core))
        self.assertEqual(admission_reason(s.core), '')
        s = self.reload(s)
        self.assertNotIn('housing', s.core.snapshot())
        with self.assertRaises(ValueError):
            s.purchase_housing()
        s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'], 60)
        self.reload(s)
        self.replay(s)

    def test_roster_count_includes_absent_excludes_adopted(self):
        s = self.game()
        from cat_cafe_sim.core.cafe_activities import ensure
        ensure(s.core)
        keys = list(s.core.cats)
        s.core.activities['cats'][keys[0]] = 'dispatched'
        s.core.activities['cats'][keys[1]] = 'missing'
        self.assertEqual(count(s.core), 5)
        s.core.activities['cats'][keys[2]] = 'adopted'
        self.assertEqual(count(s.core), 4)

    def test_expanded_capacity_nine_and_save_failure_retry(self):
        selected = starting_conditions('free')
        for key in ('intake_request', 'store_events', 'growth'):
            selected.pop(key)
        selected['management']['starting_funds'] = 5000
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.purchase_housing()
        funds = s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_game(s, s.checkpoint_path)
        s = self.reload(s)
        self.assertEqual(s.core.funds, funds)
        s.open_recruitment()
        for key in list(s.core.recruitment['candidates']):
            s.recruit_cat(key)
        for _ in range(3):
            s.day_off()
        s.open_recruitment()
        keys = [key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted']]
        s.recruit_cat(keys[0])
        self.assertEqual(count(s.core), 9)
        with self.assertRaisesRegex(ValueError, '満員'):
            s.recruit_cat(keys[1])
        self.reload(s)
        self.replay(s)

    def test_legacy_intake_can_join_above_six(self):
        s = self.game(legacy=True, intake=True)
        s.open_recruitment()
        s.recruit_cat(next(iter(s.core.recruitment['candidates'])))
        for _ in range(3):
            s.day_off()
        s.resolve_intake_request('accept')
        self.assertEqual(count(s.core), 7)
        self.reload(s)
        self.replay(s)

    def test_cost_boundary_pending_and_business_restrictions(self):
        s = self.game()
        for funds in (499, 500):
            s.core.funds = funds
            before = s.core.snapshot()
            with self.assertRaises(ValueError):
                s.purchase_housing()
            self.assertEqual(s.core.snapshot(), before)
        s.core.funds = 501
        s.purchase_housing()
        self.assertEqual(s.core.funds, 1)
        s.day_off()
        self.assertEqual(s.core.management['game_over']['reason'], 'funds')
        s = self.game()
        with patch.object(type(s), 'pending', new_callable=unittest.mock.PropertyMock, return_value={'pending': {}}):
            with self.assertRaises(ValueError):
                s.purchase_housing()
        s.automatic_step()
        before = s.core.snapshot()
        with self.assertRaises(ValueError):
            s.purchase_housing()
        self.assertEqual(s.core.snapshot(), before)

    def test_business_day_maintenance_and_purchase_day_validation(self):
        s = self.game()
        s.day_off()
        s.purchase_housing()
        while not s.core.closed:
            s.automatic_step()
        self.assertEqual(s.core.summary()['operating_cost'], 80)
        self.assertEqual(s.core.summary()['housing_expenses'], 500)
        self.assertEqual(s.core.day_results[0]['summary']['operating_cost'], 60)
        self.reload(s)
        self.replay(s)

    def test_rules_and_corrupt_save_rejected(self):
        for change in ({'initial_capacity': 5}, {'initial_capacity': True}, {'capacity_bonus': 0},
                       {'cost': float('inf')}, {'daily_cost': -1}, {'daily_cost': True}):
            with self.assertRaises(ValueError):
                rules(dict(rules(), **change))
        s = self.game()
        s.purchase_housing()
        s.day_off()
        source = checkpoint(s.core, set())
        for mutate in (
                lambda d: d['state']['housing']['purchase'].update(cost=1),
                lambda d: d['state']['housing']['purchase'].update(day=0),
                lambda d: d['state']['housing']['purchase'].update(day=2),
                lambda d: d['state']['operating_cost']['charges'][0].update(housing_cost=0),
                lambda d: d['state']['day_results'][0]['summary'].update(housing_expenses=0)):
            bad = copy.deepcopy(source)
            mutate(bad)
            bad['digest'] = digest({k: v for k, v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class HousingWindowTests(unittest.TestCase):
    setUp = HousingTests.setUp
    game = HousingTests.game
    def test_gui_purchase_cancel_layout_and_full_admission(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_housing_gui import CafeHousingWindow
        from cat_cafe_sim.cafe_recruitment_gui import CafeRecruitmentWindow
        from cat_cafe_sim.cafe_intake_request_gui import CafeIntakeRequestWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        s = self.game(intake=True)
        window = CafeHousingWindow(root, s, lambda: None)
        window.window.geometry('500x320'); root.update()
        self.assertIn('上限：6 → 9匹', window.details.get())
        self.assertIn('60 → 80', window.details.get())
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.purchase_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        self.assertLessEqual(window.close_button.winfo_rooty()+window.close_button.winfo_height(),
                             window.window.winfo_rooty()+window.window.winfo_height())
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.purchase_button.invoke()
        self.assertIn('拡張済み', window.details.get())
        self.assertTrue(window.purchase_button.instate(['disabled']))
        window.close_button.invoke()
        s = self.game(intake=True)
        s.open_recruitment()
        keys = list(s.core.recruitment['candidates'])
        s.recruit_cat(keys[0])
        recruitment = CafeRecruitmentWindow(root, s, lambda: None)
        recruitment.cats.selection_set(keys[1]); recruitment.selection_changed()
        self.assertIn('在籍 6匹 / 上限 6匹 / 空き 0匹', recruitment.funds.get())
        self.assertIn('満員', recruitment.notice.get())
        self.assertTrue(recruitment.receive_button.instate(['disabled']))
        recruitment.window.destroy()
        for _ in range(3):
            s.day_off()
        request = CafeIntakeRequestWindow(root, s, lambda: None)
        request.window.geometry('560x420'); root.update()
        self.assertTrue(request.accept_button.instate(['disabled']))
        self.assertFalse(request.decline_button.instate(['disabled']))
        self.assertIn('満員', request.notice.get())
        with patch('tkinter.messagebox.askyesno', return_value=True):
            request.decline_button.invoke()
        self.assertEqual(s.core.intake_request['status'], 'declined')
        self.assertIn('見送りました', request.notice.get())


if __name__ == '__main__':
    unittest.main()
