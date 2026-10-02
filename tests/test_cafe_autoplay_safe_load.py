import copy
import unittest
from dataclasses import replace

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay_staffing import plan
from cat_cafe_sim.cafe_autoplay_strategy import prepare
from cat_cafe_sim.core.cafe_traits import definitions


class SafeLoadTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp

    def session(self, arrivals=(0, 6, 12)):
        s = fixtures.AutoPlayTests.session(self, funds=1)
        s.core.config = replace(s.core.config, opening_ticks=40, arrival_ticks=arrivals)
        s.interaction_config = replace(s.interaction_config, ticks=20)
        s.core.initialize_traits({'a': definitions()['hospitality'], 'b': definitions()['hardy']})
        s.core.management['rules']['stress_per_service_tick'] = 1
        return s

    def test_unmatched_visitors_can_exhaust_hospitality_cat(self):
        s = self.session()
        s.core.cats['a'].fatigue = 22.5
        safe, fast = plan(s), plan(s, 'fast')
        self.assertEqual(safe['predictions']['a']['actions'], 40)
        self.assertEqual(safe['predictions']['a']['fatigue'], 72.5)
        self.assertNotIn('a', safe['workers'])
        self.assertEqual(fast['predictions']['a']['actions'], 20)
        self.assertEqual(fast['predictions']['a']['fatigue'], 47.5)

    def test_resting_candidates_do_not_reduce_survivors_forecast(self):
        s = self.session((0, 0, 0, 0))
        s.core.cats['a'].fatigue = s.core.cats['b'].fatigue = 50
        safe = plan(s)
        self.assertEqual(safe['desired'], 3)
        self.assertEqual(safe['workers'], ['c'])
        self.assertEqual(safe['predictions']['c']['actions'], 40)
        self.assertEqual(safe['predictions']['c']['fatigue'], 40)

    def test_traits_and_exact_safety_boundary(self):
        s = self.session()
        s.core.cats['a'].fatigue = 10
        s.core.cats['b'].fatigue = 30
        safe = plan(s)
        self.assertEqual(safe['predictions']['a']['fatigue'], 60)
        self.assertEqual(safe['predictions']['b']['fatigue'], 60)
        self.assertIn('a', safe['workers'])
        self.assertIn('b', safe['workers'])
        s.core.cats['a'].fatigue += .1
        s.core.cats['b'].fatigue += .1
        safe = plan(s)
        self.assertNotIn('a', safe['workers'])
        self.assertNotIn('b', safe['workers'])

    def test_visit_workload_and_closing_bound_without_dividing(self):
        s = self.session((0,))
        self.assertEqual(plan(s)['predictions']['a']['actions'], 20)
        s.core.config = replace(s.core.config, arrival_ticks=(0, 30))
        self.assertEqual(plan(s)['predictions']['a']['actions'], 30)
        s.core.config = replace(s.core.config, arrival_ticks=(0, 0, 0, 0))
        self.assertEqual(plan(s)['predictions']['a']['actions'], 40)
        s.core.config = replace(s.core.config, arrival_ticks=(39,))
        self.assertEqual(plan(s)['predictions']['a']['actions'], 20)

    def test_stress_excludes_cat_and_forecast_does_not_mutate(self):
        s = self.session()
        s.core.management['stress']['c'] = 21
        before = copy.deepcopy(s.core.snapshot())
        store = s.store.path.read_bytes()
        checkpoint = s.checkpoint_path.read_bytes()
        safe = plan(s)
        self.assertEqual(safe['predictions']['c']['stress'], 61)
        self.assertNotIn('c', safe['workers'])
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(s.store.path.read_bytes(), store)
        self.assertEqual(s.checkpoint_path.read_bytes(), checkpoint)

    def test_decisions_explain_concentration_and_all_rest(self):
        s = self.session()
        for cat in s.core.cats.values():
            cat.fatigue = 60
        rows = []
        label, action = prepare(s, None, lambda key: key, report=lambda *row: rows.append(row))
        self.assertIn('休業', label)
        self.assertTrue(all('集中上限' in row[2] for row in rows if row[0] in s.core.cats))
        self.assertEqual(plan(s, 'fast')['predictions']['a']['actions'], 20)
