import copy
from types import SimpleNamespace
import unittest

from cat_cafe_sim.cafe_shift_forecast import shift_forecast, forecast_note
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.cafe_shifts import ShiftRules
from cat_cafe_sim.core.models import Cat


class ShiftForecastTests(unittest.TestCase):
    def core(self, fatigue=60, actions=6):
        return SimpleNamespace(cats={'a':Cat(id='a',fatigue=fatigue)},
            shift_rules=ShiftRules(),health_rules=HealthRules(),
            day_results=[{'cats':{'a':{'service_ticks':actions}}}])

    def test_previous_work_and_rest_risk_without_mutation(self):
        core=self.core();before=copy.deepcopy(core)
        value=shift_forecast(core,'a')
        self.assertEqual(value['previous_actions'],6)
        self.assertEqual(value['work'],dict(fatigue=66,probability=.12))
        self.assertEqual(value['rest'],dict(fatigue=40,probability=0))
        self.assertEqual(core,before)

    def test_zero_history_is_distinct_from_unknown_and_caps_apply(self):
        core=self.core(fatigue=95,actions=20)
        value=shift_forecast(core,'a')
        self.assertEqual(value['work'],dict(fatigue=100,probability=.5))
        self.assertAlmostEqual(value['rest']['probability'],.3)
        core=self.core(fatigue=5,actions=0)
        value=shift_forecast(core,'a')
        self.assertEqual(value['work']['fatigue'],5)
        self.assertEqual(value['rest']['fatigue'],0)
        self.assertIn('接客0行動',forecast_note(value))
        for history in ([],[{'cats':{'a':{}}}],[{'cats':{}}]):
            core.day_results=history
            value=shift_forecast(core,'a')
            self.assertIsNone(value['work'])
            self.assertIsNone(value['previous_actions'])
            self.assertIn('記録がない',forecast_note(value))

    def test_sick_and_legacy_rules_are_not_shown_as_zero_risk(self):
        core=self.core()
        core.cats['a'].health_status='sick'
        core.cats['a'].recovery_days_remaining=2
        value=shift_forecast(core,'a')
        self.assertIsNone(value['work'])
        self.assertIsNone(value['rest']['probability'])
        self.assertEqual(value['recovery_after'],1)
        core.cats['a'].recovery_days_remaining=1
        self.assertIn('翌日から出勤',forecast_note(shift_forecast(core,'a')))
        core=self.core();core.health_rules=None
        self.assertIsNone(shift_forecast(core,'a')['work']['probability'])
        core.shift_rules=None
        self.assertIsNone(shift_forecast(core,'a')['rest'])

    def test_saved_coefficients_are_used(self):
        core=self.core(fatigue=20,actions=2)
        core.shift_rules=ShiftRules(max_fatigue=50,fatigue_per_service_tick=4,rest_day_recovery=3)
        core.health_rules=HealthRules(safe_fatigue=20,probability_per_fatigue=.1,max_probability=.9)
        value=shift_forecast(core,'a')
        self.assertEqual(value['work'],dict(fatigue=28,probability=.8))
        self.assertEqual(value['rest'],dict(fatigue=17,probability=0))
