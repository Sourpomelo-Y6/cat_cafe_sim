import os
import unittest
import copy

import test_cafe_popular_customers as existing
from cat_cafe_sim.cafe_new_game import starting_conditions, create_game
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.core.cafe_weekdays import schedule, rules, popular_customers
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction


class SecondPopularCustomerTests(unittest.TestCase):
    setUp = existing.PopularCustomerTests.setUp
    close = existing.PopularCustomerTests.close
    reload = existing.PopularCustomerTests.reload
    unlock = existing.PopularCustomerTests.unlock
    def game(self, mode='popularity', legacy=False, seats=2):
        return existing.PopularCustomerTests.game(self, mode, legacy, seats)

    def second_game(self, mode='popularity'):
        selected = starting_conditions(mode)
        for key in ('store_events', 'intake_request', 'regular_introduction', 'reservation'):
            selected.pop(key, None)
        selected['goal']['target'] = 105
        selected['goal']['stages'][0]['target'] = 110
        return create_game(self.temp.name, selected)

    def test_second_stage_preview_actual_arrivals_save_and_replay(self):
        session = self.second_game()
        expected = {'guest-11': 10, 'guest-12': 30}
        before = copy.deepcopy(session.core.snapshot())
        rows = {r['customer_id']: r for r in directory(session)}
        self.assertEqual(rows['guest-11']['name'], '吉田さん')
        self.assertEqual(rows['guest-12']['name'], '山田さん')
        self.assertEqual(rows['guest-11']['status'], '未解放（人気第2段階）')
        self.assertEqual(session.core.snapshot(), before)
        self.unlock(session)
        self.assertTrue(set(expected).isdisjoint(schedule(session.core)))
        self.close(session)
        self.assertEqual(session.core.goal['status'], 'cleared')
        self.assertTrue(set(expected).isdisjoint(session.core.visits))
        self.assertEqual({k: schedule(session.core, 3)[k] for k in expected}, expected)
        session = self.reload(session)
        session.advance_goal()
        session.next_day()
        while session.core.tick < 16:
            session.automatic_step()
        session = self.reload(session)
        self.close(session)
        for key, tick in expected.items():
            self.assertEqual(session.core.visits[key].arrival_tick, tick)
        self.reload(session)
        self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(), session.core.snapshot())
        lowered = copy.deepcopy(session.core)
        lowered.management['popularity'] = 50
        self.assertTrue(set(expected) <= set(schedule(lowered, 4)))

    def test_second_stage_continuation_day_off_and_filters(self):
        session = self.second_game()
        self.unlock(session)
        self.close(session)
        session.continue_goal()
        session.next_day()
        session.day_off()
        self.assertEqual(session.core.day_results[-1]['customer_visits'], [])
        session = self.reload(session)
        self.assertTrue({'guest-11', 'guest-12'} <= set(schedule(session.core)))
        session.core.customer_trust['customers']['guest-11'] = dict(status='departed', departed_day=1)
        self.assertNotIn('guest-11', schedule(session.core))
        session.core.customer_discontent['customers']['guest-12'] = dict(score=100, score_day=1, suspensions=[dict(day=1, until=8)])
        self.assertNotIn('guest-12', schedule(session.core))

    def test_second_count_validation_and_legacy_first_stage_only(self):
        base = dict(start_weekday=0, patterns=[[0]], popular_customer_count=4)
        for value in (0, -1, 9, True, 2.0, None):
            with self.assertRaises(ValueError):
                rules(dict(base, second_popular_customer_count=value))
        session = self.game()
        self.assertEqual(set(popular_customers(session.core)), {'guest-7', 'guest-8', 'guest-9', 'guest-10'})
        self.reload(session)
        self.assertNotIn('second_popular_customer_count', session.core.weekdays)

    def test_later_challenge_and_short_opening(self):
        session = self.second_game('free')
        self.assertNotIn('guest-11', schedule(session.core, 100))
        existing.PopularCustomerTests.start_challenge(self, session)
        self.unlock(session)
        self.assertNotIn('guest-11', schedule(session.core))
        short = copy.deepcopy(session.core)
        from dataclasses import replace
        short.config = replace(short.config, opening_ticks=3)
        self.assertTrue(all(0 <= tick < 3 for tick in popular_customers(short).values()))

    @unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
    def test_gui_second_stage_labels_and_names(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_customers_gui import CafeCustomersWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        session = self.second_game()
        before = copy.deepcopy(session.core.snapshot())
        stored = session.store.path.read_bytes()
        window = CafeCustomersWindow(root, session)
        self.addCleanup(window.window.destroy)
        window.window.geometry('660x520')
        root.update()
        self.assertEqual(window.customers.set('guest-11', 'お客さん'), '吉田さん')
        self.assertEqual(window.customers.set('guest-12', 'お客さん'), '山田さん')
        self.assertEqual(window.customers.set('guest-11', '客層'), '人気第2段階で増える通常客')
        self.assertEqual(window.customers.set('guest-11', '本日の状態'), '未解放（人気第2段階）')
        window.customers.selection_set('guest-11')
        window.select()
        self.assertIn('吉田さん', window.details.get())
        self.assertEqual(session.core.snapshot(), before)
        self.assertEqual(session.store.path.read_bytes(), stored)
