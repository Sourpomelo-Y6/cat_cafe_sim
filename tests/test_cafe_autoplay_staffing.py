import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay_staffing import plan, expansion_reason
from cat_cafe_sim.cafe_autoplay_strategy import prepare


class StaffingTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp

    def session(self, arrivals=(0,), funds=1):
        session = fixtures.AutoPlayTests.session(self, funds=funds)
        session.core.config = replace(session.core.config, opening_ticks=40, arrival_ticks=arrivals)
        session.interaction_config = replace(session.interaction_config, ticks=20)
        return session

    def test_busy_day_adds_workers_and_preview_is_readonly(self):
        session = self.session()
        before = copy.deepcopy(session.core.snapshot())
        stored = session.store.path.read_bytes()
        quiet = plan(session)
        self.assertEqual(quiet['workers'], ['a'])
        self.assertEqual(quiet['peak'], 1)
        self.assertEqual(session.core.snapshot(), before)
        self.assertEqual(session.store.path.read_bytes(), stored)
        session.core.config = replace(session.core.config, arrival_ticks=(0,0,0))
        busy = plan(session)
        self.assertEqual(busy['workers'], ['a','b','c'])
        self.assertEqual(busy['peak'], 3)
        self.assertEqual(expansion_reason(session.core, busy), '')

    def test_spaced_visitors_do_not_need_more_simultaneous_seats(self):
        session = self.session((0,20))
        staffing = plan(session)
        self.assertEqual(staffing['peak'], 1)
        self.assertEqual(staffing['workload'], 40)
        self.assertTrue(expansion_reason(session.core, staffing))
        session.core.config = replace(session.core.config, arrival_ticks=(39,))
        self.assertEqual(plan(session)['workload'], 1)

    def test_shortage_skips_expansion_and_excludes_sick_absent_and_exhausted(self):
        session = self.session((0,0,0))
        session.core.cats['a'].health_status = 'sick'
        session.core.cats['b'].cannot_continue = True
        staffing = plan(session)
        self.assertEqual(staffing['workers'], ['c'])
        self.assertIn('出勤候補1匹', expansion_reason(session.core, staffing))
        with patch.object(session.core, 'activity', side_effect=lambda key:'dispatch' if key=='c' else 'cafe'):
            self.assertEqual(plan(session)['workers'], [])
        session.core.cats['c'].stamina = 0
        self.assertEqual(plan(session)['workers'], [])

    def test_queue_pressure_is_capped_by_actual_seat_capacity(self):
        session = self.session((0,)*8)
        session.core.cats['a'].fatigue = 30
        staffing = plan(session)
        self.assertEqual(staffing['workload'], 160)
        self.assertEqual(staffing['predictions']['a']['actions'], 27)
        self.assertIn('a', staffing['workers'])

    def test_current_load_replaces_past_work_and_retains_safe_limits(self):
        session = self.session((0,0,0))
        session.core.cats['a'].fatigue = 30
        session.core.day_results = [dict(cats={'a':dict(service_ticks=40)})]
        self.assertIn('a', plan(session)['workers'])
        session.core.cats['a'].fatigue = 41
        self.assertNotIn('a', plan(session)['workers'])
        session.core.management['stress']['b'] = 61
        self.assertNotIn('b', plan(session)['workers'])

    def test_no_visitors_rest_and_reports_include_demand_and_expansion_skip(self):
        session = self.session(())
        reports = []
        label, action = prepare(session, None, lambda key:key,
                                report=lambda *row:reports.append(row))
        self.assertIn('休業', label)
        self.assertTrue(any(row[0]=='席の増設' and row[1]=='見送り' for row in reports))
        self.assertTrue(any('来店予定0人' in row[2] for row in reports if row[0] in session.core.cats))
