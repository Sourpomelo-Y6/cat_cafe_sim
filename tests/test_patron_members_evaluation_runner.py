import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Docs.Results import PatronMembersEvaluationRunner as runner


class PatronEvaluationRunnerTests(unittest.TestCase):
    def test_collect_and_dispatch_audit_follow_replaced_session_core(self):
        def core(funds, feature):
            return SimpleNamespace(
                funds=funds, day=1, closed=True,
                cats={'cat': SimpleNamespace(fatigue=0, health_status='healthy')},
                cat_features={'cat': [feature]},
                growth={'cats': {'cat': {'specialization': 'service', 'selected_day': 1}}},
                patron={'status': 'cleared'}, activities={'events': {}},
                snapshot=lambda: {'funds': funds},
            )
        old, current = core(1000, 'black'), core(1200, 'white')
        session = SimpleNamespace(core=old, profiles={'cat': {'name': 'テスト猫'}},
                                  dispatch=lambda cat, rules: None, checkpoint_path='unused')

        def play():
            session.core = current
            session.dispatch('cat', {'id': 'patron_strict_visit'})
            return SimpleNamespace(reason='completed', days=1, operations=1)

        def collect(selected, result):
            self.assertEqual(selected.snapshot(), current.snapshot())
            self.assertIs(selected.cats, current.cats)
            return {'metrics': dict(days=1, starting_funds=1000, income=200,
                                    expenses=0, final_funds=1200, illnesses=0, expense_breakdown={})}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runner, 'create_game', return_value=session), \
                patch.object(runner, 'AutoPlayer', return_value=SimpleNamespace(run=play)), \
                patch.object(runner, 'collect', side_effect=collect), \
                patch.object(runner, 'save_game'), \
                patch.object(runner, 'load_game', return_value=(SimpleNamespace(core=current), False)), \
                patch.object(runner.cafe_patron_members, 'terms', return_value={'matched': True}), \
                patch.object(runner.cafe_activities, 'dispatch_reason', return_value=''):
            row = runner.run((0, directory))
            self.assertEqual(row['dispatch_audit'][0]['candidates'][0]['features'], ['white'])
            self.assertEqual(row['metrics']['final_funds'], 1200)
            self.assertTrue(row['save_resume_verified'])
            self.assertEqual(json.loads((Path(directory)/'0.json').read_text()), row)
