import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from Docs.Results.BondStaminaEvaluationRunner import window_metrics
from cat_cafe_sim.autoplay_evaluation import collect
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions


class BondStaminaEvaluationRunnerTests(unittest.TestCase):
    def test_common_window_finance_and_load_use_only_completed_days_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(Path(directory), starting_conditions('bond'), seed=0)
            session.day_off()
            first_funds = session.core.funds
            session.day_off()
            session.day_off()
            core = session.core
            before = copy.deepcopy(core.snapshot())
            result = SimpleNamespace(reason='day_limit', message='')
            metrics = window_metrics(core, result, 2)
            self.assertEqual(metrics['days'], 2)
            self.assertEqual(metrics['final_funds'], core.day_results[1]['summary']['closing_funds'])
            self.assertEqual(metrics['starting_funds']+metrics['income']-metrics['expenses'], metrics['final_funds'])
            self.assertEqual(metrics['cat_days'], 10)
            self.assertEqual(window_metrics(core, result, 1)['final_funds'], first_funds)
            self.assertEqual(core.snapshot(), before)
            for invalid in (4, 0, -1, True):
                with self.assertRaises(ValueError):window_metrics(core, result, invalid)

    def test_current_closed_day_is_included_once(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(Path(directory), starting_conditions('bond'), seed=0)
            while not session.core.closed:session.automatic_step()
            result = SimpleNamespace(reason='day_limit', message='')
            before = copy.deepcopy(session.core.snapshot())
            self.assertEqual(window_metrics(session.core, result, 1), collect(session.core, result)['metrics'])
            self.assertEqual(session.core.snapshot(), before)
