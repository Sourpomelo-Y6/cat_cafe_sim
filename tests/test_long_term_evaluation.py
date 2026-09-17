from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from cat_cafe_sim.core.models import Cat
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.long_term_evaluation import choose_schedule, choose_fatigue_cat, evaluate, POLICIES


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
        for policy in POLICIES:
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

    def test_fatigue_rest_prioritizes_healthy_cats_and_can_close(self):
        core = SimpleNamespace(day=1, cats={key:Cat(id=key) for key in ('a','b','c')}, health_rules=HealthRules())
        core.cats['b'].fatigue = 70
        core.cats['c'].fatigue = 40
        self.assertEqual(choose_schedule(core, 'fatigue_rest_one'), ['a','c'])
        self.assertEqual(choose_schedule(core, 'fatigue_rest_two'), ['a'])
        core.cats['b'].health_status = 'sick'
        self.assertEqual(choose_schedule(core, 'fatigue_rest_one'), ['a'])
        self.assertIsNone(choose_schedule(core, 'fatigue_rest_two'))
        core.cats['c'].fatigue = 0
        self.assertEqual(choose_schedule(core, 'fatigue_rest_one'), ['c'])

    def test_assignment_accounts_for_today_service_then_stamina_and_id(self):
        from cat_cafe_sim.core.cafe_shifts import ShiftRules
        cats = [Cat(id=key) for key in ('a','b','c')]
        core = SimpleNamespace(shift_rules=ShiftRules(), cat_service_ticks={'a':20,'b':0,'c':0})
        cats[1].fatigue = 10
        cats[2].fatigue = 10
        cats[1].stamina = 50
        session = SimpleNamespace(core=core, available_cats=lambda:cats)
        self.assertEqual(choose_fatigue_cat(session).id, 'c')
        cats[1].stamina = cats[2].stamina
        self.assertEqual(choose_fatigue_cat(session).id, 'b')

    def test_new_policies_finish_with_reproducible_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            for policy in ('fatigue_rest_one','fatigue_rest_two','fatigue_assignment'):
                with self.subTest(policy=policy):
                    a = evaluate(policy, 0, 2, Path(directory)/'first')
                    b = evaluate(policy, 0, 2, Path(directory)/'second')
                    for key in ('revenue','illnesses','recovery_cat_days','open_days','service_ticks'):
                        self.assertEqual(a['metrics'][key], b['metrics'][key])
                    self.assertEqual(a['metrics']['open_days'], 2)
                    self.assertGreater(a['metrics']['revenue'], 0)
