import copy
import tempfile
import unittest
from pathlib import Path
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import objective_start_view, objective_progress_view, goal_result_view


class UnityObjectivePresentationTests(unittest.TestCase):
    def test_started_summary_matches_progress_without_changing_game(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ('popularity', 'bond', 'patron', 'free'):
                session = create_game(Path(directory) / mode, starting_conditions(mode))
                before = copy.deepcopy(session.core.snapshot())
                files = {p: p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
                rows = objective_start_view(session)['rows']
                for row in rows:
                    if row['started'] and row['choice'] != 'management':
                        self.assertIn(objective_progress_view(session, row['choice'])['summary'], row['summary'])
                        if row['choice'] in ('bond', 'patron'):
                            self.assertIn('期限なし', row['summary'])
                    elif not row['started']:
                        self.assertEqual(row['summary'], '未開始')
                self.assertEqual(before, session.core.snapshot())
                self.assertEqual(files, {p: p.read_bytes() for p in files})

    def test_cleared_and_expired_summary_reuses_existing_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            for target, expected in ((105, 'cleared'), (250, 'expired')):
                settings = starting_conditions('popularity')
                settings['goal'].update(target=target, days=1)
                settings['store_events']['probability'] = 0
                session = create_game(Path(directory) / expected, settings)
                session.core.management['popularity'] = 110
                session.day_off()
                before = copy.deepcopy(session.core.snapshot())
                result = goal_result_view(session)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['summary'], objective_progress_view(session, 'popularity')['summary'])
                self.assertIn('残り0日', result['summary'])
                self.assertEqual(before, session.core.snapshot())


if __name__ == '__main__':
    unittest.main()
