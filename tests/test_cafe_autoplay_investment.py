import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_autoplay_strategy import prepare, reserve, waiting_reserve, waiting_investment
from cat_cafe_sim.core import cafe_operating_cost, cafe_waiting_area
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_goal import rules as goal_rules
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class InvestmentTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp

    def session(self, name='game', *, funds=10000, days=4, arrivals=None):
        s = fixtures.AutoPlayTests.session(self, name, funds=funds, days=days, cat_ids=['a'])
        if arrivals is not None:
            path = s.checkpoint_path
            s = CafeInteractionSession(store=s.store, seat_count=2, cat_ids=['a'],
                cafe_config=replace(Config.load(), opening_ticks=2, arrival_ticks=arrivals, initial_funds=0),
                interaction_config=replace(RelationshipConfig(), ticks=1))
            s.enable_management(dict(management_rules(), starting_funds=funds, stress_per_service_tick=0))
            s.enable_goal(dict(goal_rules(), target=105, days=days,
                              stages=[dict(target=110, days=days), dict(target=115, days=days)]))
            save_game(s, path)
        s.core.initialize_operating_cost(cafe_operating_cost.rules())
        s.core.initialize_waiting_area()
        return s

    def first_stage(self, s):
        self.assertEqual(AutoPlayer(s, mode='basic', stop_on_goal=True).run().reason, 'goal_cleared')
        s.advance_goal()
        s.next_day()

    def demand(self):
        return dict(arrivals=5, workers=['a'])

    def test_readonly_choice_uses_normal_purchase_and_explains_cost(self):
        s = self.session()
        self.first_stage(s)
        before = copy.deepcopy(s.core.snapshot())
        store = s.store.path.read_bytes()
        rows = []
        label, action = waiting_investment(s, self.demand(), 3, lambda *row: rows.append(row))
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(s.store.path.read_bytes(), store)
        self.assertIn('待合スペース', label)
        self.assertIn('維持費10/日', rows[0][2])
        self.assertIn('予備資金', rows[0][2])
        funds = s.core.funds
        action()
        self.assertEqual(s.core.operations[-1]['operation']['kind'], 'purchase_waiting_area')
        self.assertEqual(s.core.funds, funds-800)
        self.assertEqual(len(s.core.seats), 2)

    def test_budget_exact_boundary_includes_daily_cost(self):
        s = self.session()
        self.first_stage(s)
        s.core.operating_cost['rules'].update(base_cost=200, per_seat_cost=20)
        self.assertEqual(reserve(s.core), 520)
        self.assertEqual(waiting_reserve(s.core, 10), 540)
        s.core.funds = 1339
        self.assertIsNone(waiting_investment(s, self.demand(), 3))
        s.core.funds = 1340
        _, action = waiting_investment(s, self.demand(), 3)
        action()
        self.assertEqual(s.core.funds, 540)
        self.assertEqual(waiting_reserve(s.core), 540)

    def test_unlocked_and_deadline_constraints(self):
        s = self.session()
        self.assertIsNone(waiting_investment(s, self.demand(), 3))
        self.first_stage(s)
        self.assertIsNone(waiting_investment(s, self.demand(), 1))
        _, action = waiting_investment(s, self.demand(), 3)
        action()
        self.assertIsNone(waiting_investment(s, self.demand(), 3))

    def test_forecast_or_previous_waiting_is_required(self):
        s = self.session()
        self.first_stage(s)
        staffing = dict(arrivals=1, workers=['a'])
        self.assertIsNone(waiting_investment(s, staffing, 3))
        for key in ('wait_timeout', 'queue_full'):
            s.core.day_results[-1]['summary']['departures'] = {key: 1}
            self.assertIsNotNone(waiting_investment(s, staffing, 3))
        s.core.day_results[-1]['summary']['departures'] = {}
        self.assertIsNone(waiting_investment(s, dict(arrivals=0, workers=[]), 3))

    def test_old_save_without_waiting_and_saved_purchase_rules(self):
        s = self.session()
        self.first_stage(s)
        s.core.waiting_area['rules']['cost'] = 123
        _, action = waiting_investment(s, self.demand(), 3)
        funds = s.core.funds
        action()
        self.assertEqual(s.core.funds, funds-123)
        s.core.waiting_area = None
        before = copy.deepcopy(s.core.snapshot())
        self.assertIsNone(waiting_investment(s, self.demand(), 3))
        self.assertEqual(s.core.snapshot(), before)

    def test_only_popularity_fast_uses_waiting_before_expansion(self):
        s = self.session()
        self.first_stage(s)
        label, action = prepare(s, None, str, mode='fast')
        self.assertIn('休養スペースを購入', label)
        action()
        for mode, objective in (('clear', 'popularity'), ('fast', 'bond')):
            with patch('cat_cafe_sim.cafe_autoplay_strategy.waiting_investment', side_effect=AssertionError('unexpected')):
                prepare(s, None, str, mode=mode, objective=objective)
        with patch('cat_cafe_sim.cafe_autoplay_strategy.plan', return_value=self.demand()):
            # The forecast's other fields are only needed after the waiting choice.
            label, action = prepare(s, None, str, mode='fast')
        self.assertIn('待合スペース', label)
        action()
        player = AutoPlayer(s, mode='basic')
        with patch('cat_cafe_sim.cafe_autoplay_strategy.waiting_investment', side_effect=AssertionError('unexpected')):
            self.assertTrue(player.step())

    def test_upgrade_cancel_resume_and_detailed_replay(self):
        s = self.session(arrivals=(0, 0, 1))
        direct = self.session('direct', arrivals=(0, 0, 1))
        continuous = AutoPlayer(direct, mode='fast')
        save_game(s, s.checkpoint_path)
        player = AutoPlayer(s, mode='fast')
        purchases = []
        while True:
            ids = [f'investment-{continuous.operations}-{i}' for i in range(10)]
            with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                progressed = continuous.step()
            with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                self.assertEqual(player.step(), progressed)
            self.assertEqual(s.core.snapshot(), direct.core.snapshot())
            if not progressed:
                break
            kind = s.core.operations[-1]['operation']['kind']
            if kind in ('purchase_waiting_area', 'upgrade_waiting_area'):
                purchases.append(kind)
                before = copy.deepcopy(s.core.snapshot())
                player.cancel()
                self.assertFalse(player.step())
                self.assertEqual(s.core.snapshot(), before)
                save_game(s, s.checkpoint_path)
                s = load_game(s.checkpoint_path)[0]
                self.assertEqual(s.core.snapshot(), before)
                player = AutoPlayer(s, mode='fast')
        self.assertEqual(player.result.reason, 'completed')
        self.assertEqual(purchases, ['purchase_waiting_area', 'upgrade_waiting_area'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.assertLessEqual(len(s.core.seats), 8)
        _, action = prepare(s, None, str, mode='fast')
        self.assertNotIn(action, (s.purchase_waiting_area, s.upgrade_waiting_area))
