import unittest
from unittest.mock import patch

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay import AutoPlayer


class AutoPlayDecisionTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp
    session = fixtures.AutoPlayTests.session

    def test_observing_decisions_preserves_operations_state_and_logs(self):
        for mode in ('basic', 'clear'):
            a, b = self.session(mode+'-plain'), self.session(mode+'-observed')
            rows, logs_a, logs_b = [], [], []
            plain = AutoPlayer(a, mode=mode, emit=logs_a.append)
            observed = AutoPlayer(b, mode=mode, emit=logs_b.append, on_decision=rows.append)
            while True:
                ids = [f'{mode}-{plain.operations}-{i}' for i in range(10)]
                with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                    progressed = plain.step()
                with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                    self.assertEqual(observed.step(), progressed)
                self.assertEqual(a.core.snapshot(), b.core.snapshot())
                if not progressed:
                    break
            self.assertEqual(plain.result, observed.result)
            self.assertEqual(logs_a, logs_b)
            self.assertTrue(rows)
            self.assertTrue(all(row['status']=='実行済み' for row in rows))

    def test_basic_rest_boundary_and_clear_forecast_reasons(self):
        basic = self.session('basic')
        basic.core.cats['a'].fatigue = 60
        rows = []
        self.assertTrue(AutoPlayer(basic, on_decision=rows.append).step())
        row = next(row for row in rows if row['subject']=='a')
        self.assertEqual(row['choice'], '休養')
        self.assertIn('現在の疲労60', row['reason'])
        self.assertNotIn('a', basic.core.working_cats)
        clear = self.session('clear', funds=1)
        rows = []
        self.assertTrue(AutoPlayer(clear, mode='clear', on_decision=rows.append).step())
        self.assertTrue(all('出勤時の予測' in row['reason'] for row in rows if row['subject'] in clear.core.cats))

    def test_purchase_failure_and_cancel_are_not_reported_as_executed(self):
        session = self.session()
        rows = []
        player = AutoPlayer(session, mode='clear', on_decision=rows.append)
        before = session.core.snapshot()
        with patch.object(session, 'purchase_rest_space', side_effect=OSError('disk error')):
            self.assertFalse(player.step())
        self.assertEqual(session.core.snapshot(), before)
        self.assertEqual(rows[0]['target'], '休養スペース')
        self.assertEqual(rows[0]['choice'], '購入')
        self.assertIn('予備資金300', rows[0]['reason'])
        self.assertIn('失敗', rows[0]['status'])
        rows.clear()
        player = AutoPlayer(session, mode='clear', on_decision=rows.append)
        player.cancel()
        self.assertFalse(player.step())
        self.assertEqual(rows, [])

    def test_reservation_decisions_explain_both_conditions(self):
        for days, longhair, choice in ((3, True, '受諾'), (1, True, '見送り'), (3, False, '見送り')):
            session = self.session(f'{days}-{longhair}', days=days)
            session.core.initialize_preferences({key: ['long_hair' if longhair else 'short_hair'] for key in session.core.cats})
            session.core.initialize_reservation()
            AutoPlayer(session, max_days=2).run()
            session.advance_goal()
            session.next_day()
            rows = []
            self.assertTrue(AutoPlayer(session, mode='clear', on_decision=rows.append).step())
            self.assertEqual(rows[0]['target'], '特別予約')
            self.assertEqual(rows[0]['choice'], choice)
            self.assertIn('長毛猫', rows[0]['reason'])
            self.assertIn('期限', rows[0]['reason'])
            if not longhair:
                self.assertIn('いない', rows[0]['reason'])
            if days==1:
                self.assertIn('超える', rows[0]['reason'])
