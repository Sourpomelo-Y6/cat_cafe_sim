import unittest
import tempfile
from pathlib import Path

from cat_cafe_sim.autoplay_evaluation import evaluate, evaluation_conditions, service_metrics
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.core import cafe_equipment


class AutoPlayEvaluationTests(unittest.TestCase):
    def test_daily_totals_and_repeatability_for_same_conditions(self):
        a = evaluate(max_days=2, scenarios=('basic',), emit=lambda _: None)
        b = evaluate(max_days=2, scenarios=('basic',), emit=lambda _: None)
        self.assertEqual(a['runs'], b['runs'])
        self.assertEqual(a['conditions_sha256'], b['conditions_sha256'])
        run = a['runs']['basic']
        m = run['metrics']
        self.assertEqual(run['reason'], 'day_limit')
        self.assertEqual(m['days'], 2)
        self.assertEqual([row['day'] for row in run['daily']], [1, 2])
        self.assertEqual(m['starting_funds']+m['income']-m['expenses'], m['final_funds'])
        self.assertEqual(m['expenses'], sum(m['expense_breakdown'].values()))
        self.assertEqual(m['cat_days'], 10)
        self.assertEqual(m['arrivals'], sum(row['summary']['arrivals'] for row in run['daily']))
        self.assertEqual(m['occupied_seat_ticks']+m['empty_seat_ticks'], m['available_seat_ticks'])
        self.assertGreater(m['seat_utilization'], 0)
        self.assertLessEqual(m['seat_utilization'], 1)

    def test_customer_presets_are_isolated_and_retain_goal_rules(self):
        standard = evaluation_conditions('standard')
        legacy = evaluation_conditions('standard', 'legacy')
        self.assertEqual(standard['weekdays']['popular_customer_count'], 4)
        self.assertNotIn('popular_customer_count', legacy['weekdays'])
        legacy['weekdays']['popular_customer_count'] = 4
        self.assertEqual(standard, legacy)
        self.assertEqual(starting_conditions(), standard)
        with self.assertRaises(ValueError):
            evaluation_conditions('standard', 'unknown')

    def test_seat_capacity_excludes_days_off_and_counts_unserved_customers(self):
        rows = [dict(summary=dict(seat_count=2, arrivals=3, service_ticks=6),
                     cats={'cat': dict(shift='work')},
                     customer_outcomes=[dict(reason='wait_timeout'), dict(reason='queue_full')]),
                dict(day_type='day_off', summary=dict(seat_count=2, arrivals=0, service_ticks=0),
                     cats={'cat': dict(shift='rest')})]
        metrics = service_metrics(rows, 10)
        self.assertEqual(metrics['available_seat_ticks'], 20)
        self.assertEqual(metrics['empty_seat_ticks'], 14)
        self.assertEqual(metrics['seat_utilization'], .3)
        self.assertEqual(metrics['arrivals'], 3)
        self.assertEqual(metrics['wait_timeouts'], 1)
        self.assertEqual(metrics['queue_full_departures'], 1)
        self.assertEqual(service_metrics([], 10)['seat_utilization'], 0)

    def test_purchase_exclusion_is_local_and_baseline_rules_unchanged(self):
        original = cafe_equipment.reason
        report = evaluate(max_days=1, scenarios=('clear_no_rest', 'clear'), emit=lambda _: None)
        self.assertIs(cafe_equipment.reason, original)
        self.assertEqual(report['runs']['clear_no_rest']['metrics']['expense_breakdown']['equipment_expenses'], 0)
        self.assertGreater(report['runs']['clear']['metrics']['expense_breakdown']['equipment_expenses'], 0)
        self.assertEqual(report['conditions']['seat_count'], 2)
        self.assertEqual(report['seed'], 0)

    def test_invalid_scenarios_are_rejected(self):
        for scenarios in ((), ('unknown',)):
            with self.assertRaises(ValueError):
                evaluate(scenarios=scenarios)

    def test_goal_presets_do_not_change_normal_starting_conditions(self):
        baseline = starting_conditions()
        expected = {
            'legacy': [(150, 10), (225, 10), (300, 10)],
            'medium': [(200, 15), (350, 15), (500, 20)],
            'long': [(250, 20), (450, 20), (650, 25)],
        }
        for name, stages in expected.items():
            conditions = evaluation_conditions(name)
            goal = conditions['goal']
            self.assertEqual([(r['target'], r['days']) for r in [goal]+goal['stages']], stages)
            self.assertEqual(goal['cap'], stages[-1][0])
            self.assertEqual(goal['gain_per_success'], baseline['goal']['gain_per_success'])
            conditions['goal'] = baseline['goal']
            self.assertEqual(conditions, baseline)
        self.assertEqual(evaluation_conditions('standard'), baseline)
        self.assertEqual(evaluation_conditions('standard'), evaluation_conditions('long'))
        self.assertEqual(starting_conditions(), baseline)
        with self.assertRaises(ValueError):
            evaluation_conditions('unknown')

    def test_custom_goal_save_reload_and_report_use_selected_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(Path(directory), evaluation_conditions('long'))
            AutoPlayer(session, mode='clear', max_days=1).run()
            save_game(session, session.checkpoint_path)
            loaded = load_game(session.checkpoint_path)[0]
            self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
            self.assertEqual(loaded.core.goal['rules']['cap'], 650)
        report = evaluate(max_days=1, scenarios=('basic',), goal_preset='medium', emit=lambda _: None)
        self.assertEqual(report['goal_preset'], 'medium')
        stage = report['runs']['basic']['stages'][0]
        self.assertEqual((stage['target'], stage['deadline']), (200, 15))
