from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from cat_cafe_sim.core.models import Cat
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.long_term_evaluation import choose_schedule, evaluate


class LongTermEvaluationTests(unittest.TestCase):
    def test_schedules_use_only_preparation_state(self):
        core = SimpleNamespace(day=1, cats={key:Cat(id=key) for key in ('a','b','c')}, health_rules=HealthRules())
        self.assertEqual(choose_schedule(core,'all_work'),['a','b','c'])
        self.assertEqual(choose_schedule(core,'rotating_rest'),['b','c'])
        core.day=2
        self.assertEqual(choose_schedule(core,'rotating_rest'),['a','c'])
        core.cats['a'].fatigue=60
        self.assertIsNone(choose_schedule(core,'fatigue_closure'))
        core.cats['a'].health_status='sick'
        self.assertEqual(choose_schedule(core,'fatigue_closure'),['b','c'])
        for cat in core.cats.values():cat.health_status='sick'
        for policy in ('all_work','rotating_rest','fatigue_closure'):
            self.assertIsNone(choose_schedule(core,policy))
        with self.assertRaises(ValueError):choose_schedule(core,'unknown')

    def test_run_is_reproducible_and_writes_reports_with_verified_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            first=evaluate('all_work',0,2,Path(directory)/'first')
            second=evaluate('all_work',0,2,Path(directory)/'second')
            gameplay=lambda report:{key:value for key,value in report['metrics'].items() if not key.endswith('_seconds')}
            self.assertEqual(gameplay(first),gameplay(second))
            self.assertEqual(first['metrics']['open_days']+first['metrics']['closed_days'],2)
            self.assertEqual(first['metrics']['revenue'],first['metrics']['final_funds'])
            self.assertEqual([sample['day'] for sample in first['samples']],[1,2])
            self.assertTrue((Path(directory)/'first'/'all_work-seed-0.csv').exists())
            self.assertTrue(all(sample['save_bytes']>0 for sample in first['samples']))
