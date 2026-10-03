import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Docs.Results import BondSeedEvaluationRunner as runner


class BondEvaluationRunnerTests(unittest.TestCase):
    def run_fixture(self, preparation):
        cat = SimpleNamespace(health_status='healthy', stamina=100, fatigue=0)
        current = SimpleNamespace(
            day=2, closed=not preparation, funds=1200, cats={'cat': cat},
            recruitment={'candidates': {'cat': {'cost': 200}}},
            management={'stress': {'cat': 0}}, activity=lambda key: 'cafe',
            bond_goal={'status': 'cleared', 'resolved_day': 2},
            operations=[{'events': [{'kind': 'player_completed',
                         'result': {'cat_id': 'cat', 'affinity_before': 10, 'affinity_after': 85}}]}],
            snapshot=lambda: {'funds': 1200},
            summary=lambda: dict(opening_funds=1000, total_income=200, total_expenses=0),
        )
        session = SimpleNamespace(core=SimpleNamespace(funds=999),
            recruit_cat=lambda key: None, play_with_player=lambda key: None,
            checkpoint_path='unused', profiles={'cat': {'name': 'テスト猫'}})

        def play():
            session.core = current
            session.recruit_cat('cat')
            session.play_with_player('cat')
            return SimpleNamespace(reason='completed', days=1, operations=2)

        def collect(core, result):
            self.assertIs(core.cats, current.cats)
            self.assertEqual(core.funds, 1000 if preparation else 1200)
            return {'metrics': dict(days=1, starting_funds=1000, income=0 if preparation else 200,
                expenses=0, final_funds=core.funds, illnesses=0, runaways=0, expense_breakdown={})}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runner, 'create_game', return_value=session), \
                patch.object(runner, 'AutoPlayer', return_value=SimpleNamespace(run=play)), \
                patch.object(runner, 'collect', side_effect=collect), \
                patch.object(runner, 'reserve', return_value=300), \
                patch.object(runner, 'save_game'), \
                patch.object(runner, 'load_game', return_value=(SimpleNamespace(core=current), False)), \
                patch.object(runner.cafe_player, 'state', return_value={'affinity': {'cat': 10}}), \
                patch.object(runner.cafe_player, 'remaining', return_value=3), \
                patch.object(runner.cafe_player, 'unavailable_reason', return_value=''):
            row = runner.run((0, directory))
            self.assertEqual(row, json.loads((Path(directory)/'0.json').read_text()))
        return row

    def test_audit_and_final_collection_use_replaced_core(self):
        row = self.run_fixture(False)
        self.assertEqual(row['recruitment'][0]['funds_before'], 1200)
        self.assertEqual(row['selections'][0]['candidates'][0]['affinity'], 10)
        self.assertEqual(row['selections'][0]['result']['affinity_after'], 85)
        self.assertEqual(row['metrics']['income'], 200)
        self.assertTrue(row['save_resume_verified'])

    def test_preparation_income_is_included_without_adding_unfinished_day(self):
        row = self.run_fixture(True)
        self.assertEqual(row['metrics']['income'], 200)
        self.assertEqual(row['metrics']['final_funds'], 1200)
        self.assertEqual(row['metrics']['days'], 1)
        self.assertEqual(row['metrics']['uncompleted_day_finance']['total_income'], 200)
