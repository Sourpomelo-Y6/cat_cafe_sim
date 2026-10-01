import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_customers import directory, cat_rows
from cat_cafe_sim.core.cafe_weekdays import rules, schedule, popular_customers
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class PopularCustomerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def game(self, mode='popularity', legacy=False, seats=2):
        conditions = starting_conditions(mode)
        conditions.pop('store_events')
        conditions.pop('intake_request')
        conditions['seat_count'] = seats
        conditions['goal']['target'] = 105
        if legacy:
            conditions['weekdays'].pop('popular_customer_count')
        return create_game(self.temp.name, conditions)

    def close(self, session):
        while not session.core.closed:
            session.automatic_step()

    def reload(self, session):
        save_game(session, session.checkpoint_path)
        restored, _ = load_game(session.checkpoint_path)
        self.assertEqual(restored.core.snapshot(), session.core.snapshot())
        return restored

    def unlock(self, session, advance=True):
        self.close(session)
        self.assertEqual(session.core.goal['status'], 'cleared')
        (session.advance_goal if advance else session.continue_goal)()
        session.next_day()
        return session

    def start_challenge(self, session):
        from cat_cafe_sim.core.cafe_popularity_challenge import rules as challenge_rules
        selected = challenge_rules(session.core)
        selected['goal']['target'] = 105
        session.start_popularity_challenge(selected)

    def test_locked_preview_then_four_spaced_visitors_next_day(self):
        session = self.game()
        core = session.core
        expected = {'guest-7': 4, 'guest-8': 12, 'guest-9': 20, 'guest-10': 28}
        self.assertEqual(popular_customers(core), expected)
        before = copy.deepcopy(core.snapshot())
        stored = session.store.path.read_bytes()
        rows = {row['customer_id']: row for row in directory(session)}
        for key in expected:
            self.assertIsNone(rows[key]['arrival_tick'])
            self.assertIsNone(rows[key]['tomorrow_tick'])
            self.assertEqual(rows[key]['status'], '未解放（人気第1段階）')
            self.assertEqual(rows[key]['weekdays'], '月・火・水・木・金・土・日')
            self.assertIsNotNone(rows[key]['preference'])
            self.assertTrue(cat_rows(session, key))
        self.assertEqual(core.snapshot(), before)
        self.assertEqual(session.store.path.read_bytes(), stored)
        self.close(session)
        self.assertTrue(set(expected).isdisjoint(core.visits))
        self.assertTrue(set(expected).isdisjoint(schedule(core)))
        self.assertEqual({key: schedule(core, 2)[key] for key in expected}, expected)
        rows = {row['customer_id']: row for row in directory(session)}
        self.assertEqual({key: rows[key]['tomorrow_tick'] for key in expected}, expected)
        session = self.reload(session)
        self.unlock_after_close(session)
        self.assertEqual({key: schedule(session.core)[key] for key in expected}, expected)

    def unlock_after_close(self, session):
        session.advance_goal()
        session.next_day()

    def test_real_arrivals_preferences_visits_resume_and_replay(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                session = self.unlock(self.game(seats=seats))
                expected = popular_customers(session.core)
                preview = {row['customer_id']: row for row in directory(session)}
                while session.core.tick < 16:
                    session.automatic_step()
                session = self.reload(session)
                self.close(session)
                for key, tick in expected.items():
                    self.assertEqual(session.core.visits[key].arrival_tick, tick)
                    self.assertEqual(session.core.customer_preferences['customers'][key], preview[key]['preference'])
                self.assertTrue(set(expected) <= set(session.core.day_result()['customer_visits']))
                self.assertEqual({row['visits'] for row in directory(session) if row['customer_id'] in expected}, {1})
                session = self.reload(session)
                session.next_day()
                self.assertEqual({row['visits'] for row in directory(session) if row['customer_id'] in expected}, {1})
                self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(), session.core.snapshot())

    def test_continuation_day_off_and_popularity_drop_keep_unlock(self):
        session = self.unlock(self.game(), advance=False)
        expected = popular_customers(session.core)
        session.day_off()
        self.assertEqual(session.core.day_results[-1]['customer_visits'], [])
        self.assertTrue(set(expected) <= set(schedule(session.core)))
        session = self.reload(session)
        lowered = copy.deepcopy(session.core)
        lowered.management['popularity'] = 50
        self.assertTrue(set(expected) <= set(schedule(lowered)))
        self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(), session.core.snapshot())

    def test_normal_growth_and_seat_expansion_visitors_keep_separate_ids(self):
        session = self.game()
        session.expand_seats()
        self.unlock(session)
        session.expand_seats()
        expected = popular_customers(session.core)
        planned = schedule(session.core, 3)
        self.assertEqual(planned['expanded-guest'], 0)
        self.assertTrue(set(expected) <= set(planned))
        session.day_off()
        while not session.core.closed:
            session.step()
        self.assertTrue(set(expected) | {'expanded-guest'} <= set(session.core.visits))
        self.reload(session)
        self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(), session.core.snapshot())

    def test_later_challenge_unlocks_only_new_games(self):
        for mode in ('free', 'bond', 'patron'):
            session = self.game(mode)
            expected = popular_customers(session.core)
            self.assertTrue(set(expected).isdisjoint(schedule(session.core, 100)))
            session.day_off()
            self.start_challenge(session)
            session = self.unlock(session)
            self.assertTrue(set(expected) <= set(schedule(session.core)))
            self.reload(session)

    def test_legacy_settings_stay_absent_even_after_clear_and_challenge(self):
        for mode in ('popularity', 'free'):
            session = self.game(mode, legacy=True)
            if mode == 'free':
                self.start_challenge(session)
            session = self.unlock(session)
            with patch('cat_cafe_sim.core.cafe_weekdays.rules', side_effect=lambda data=None: rules(data) if data is not None else self.fail('設定を再読込')):
                session = self.reload(session)
            self.assertNotIn('popular_customer_count', session.core.weekdays)
            self.assertEqual(popular_customers(session.core), {})
            self.assertTrue({'guest-7', 'guest-8', 'guest-9', 'guest-10'}.isdisjoint(schedule(session.core)))

    def test_rain_suspension_and_permanent_departure_filter_extra_visitors(self):
        core = self.unlock(self.game()).core
        core.customer_discontent['customers']['guest-7'] = dict(score=100, score_day=1,
            suspensions=[dict(day=1, until=8)])
        core.customer_trust['customers']['guest-8'] = dict(status='departed', departed_day=1)
        core.store_events = dict(rules={}, days=[dict(day=2, type='rain')])
        planned = schedule(core)
        self.assertNotIn('guest-7', planned)
        self.assertNotIn('guest-8', planned)
        self.assertNotIn('guest-10', planned)
        self.assertEqual(planned['guest-9'], 20)
        # 毎日の定期枠は常連になっても開店時へ移動せず、1日1回来店。
        core.customer_loyalty['customers']['guest-9'] = dict(score=100, regular_day=1)
        self.assertEqual(schedule(core, 7)['guest-9'], 20)

    def test_invalid_count_and_tampered_completed_schedule_are_rejected(self):
        base = dict(start_weekday=0, patterns=[[0]])
        for count in (0, -1, 9, True, 4.0, '4', None):
            with self.assertRaises(ValueError):
                rules(dict(base, popular_customer_count=count))
        session = self.unlock(self.game())
        self.close(session)
        source = checkpoint(session.core, set())
        for count in (3, 5):
            bad = copy.deepcopy(source)
            bad['state']['weekdays']['popular_customer_count'] = count
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)

    @unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
    def test_gui_locked_and_unlocked_names_preferences_schedule_and_readonly(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_customers_gui import CafeCustomersWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        session = self.game()
        for unlocked in (False, True):
            if unlocked:
                self.unlock(session)
            before = copy.deepcopy(session.core.snapshot())
            stored = session.store.path.read_bytes()
            window = CafeCustomersWindow(root, session)
            window.window.geometry('660x520')
            root.update()
            self.assertEqual(window.customers.set('guest-7', 'お客さん'), '山本さん')
            self.assertEqual(window.customers.set('guest-7', '客層'), '人気第1段階で増える通常客')
            window.customers.selection_set('guest-7')
            window.select()
            self.assertIn('guest-7', window.details.get())
            self.assertIn('山本さん', window.details.get())
            self.assertNotEqual(window.customers.set('guest-7', '好み'), '未設定')
            if unlocked:
                self.assertEqual(window.customers.set('guest-7', '予定の進行'), '4')
            else:
                self.assertIn('未解放', window.customers.set('guest-7', '本日の状態'))
            window.view_day.set(window.day_choices[1])
            window.fill()
            self.assertEqual(window.customers.selection(), ('guest-7',))
            for table in (window.customers, window.cats):
                self.assertGreaterEqual(table.winfo_height(), 100)
                self.assertLessEqual(table.winfo_rooty()+table.winfo_height(),
                                     window.window.winfo_rooty()+window.window.winfo_height())
            self.assertEqual(session.core.snapshot(), before)
            self.assertEqual(session.store.path.read_bytes(), stored)
            window.window.destroy()
