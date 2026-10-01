import unittest

from cat_cafe_sim.autoplay_evaluation import evaluate
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
