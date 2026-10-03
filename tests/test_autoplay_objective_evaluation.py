import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cat_cafe_sim import autoplay_evaluation as evaluation
from cat_cafe_sim.autoplay_objective_metrics import objective_result, summarize_objective, completed_window
from cat_cafe_sim.cafe_new_game import starting_conditions


class ObjectiveEvaluationTests(unittest.TestCase):
    def test_default_and_native_conditions_are_isolated_and_presets_rejected_before_play(self):
        for objective in evaluation.OBJECTIVES:
            conditions = evaluation.evaluation_conditions('standard', objective=objective)
            self.assertEqual(conditions, starting_conditions(objective))
            conditions['management']['starting_funds'] = -1
            self.assertEqual(evaluation.evaluation_conditions('standard', objective=objective), starting_conditions(objective))
        with patch.object(evaluation, 'create_game') as create:
            for objective in ('bond', 'patron'):
                with self.assertRaises(ValueError):
                    evaluation.evaluate(objective=objective, goal_preset='legacy')
            for days in (0, -1, True):
                with self.assertRaises(ValueError):
                    evaluation.evaluate(max_days=days)
            for objectives in ([], ['bond', 'bond'], ['unknown']):
                with self.assertRaises(ValueError):
                    evaluation.evaluate_objectives(objectives, [0])
            create.assert_not_called()

    def test_basic_native_goals_have_no_fictitious_popularity_stages_or_objective_actions(self):
        for objective, metric in (('bond', 'sets'), ('patron', 'dispatched')):
            report = evaluation.evaluate_seeds([0, 1], objective=objective, max_days=1,
                                                scenarios=['basic'], emit=lambda _: None)
            summary = report['summary']['by_scenario']['basic']
            self.assertEqual(report['objective'], objective)
            self.assertEqual(summary['stages'], [])
            self.assertEqual(summary['completion_calendar_days']['count'], 0)
            self.assertEqual(summary['objective_metrics'][metric]['max'], 0)
            for row in report['evaluations']:
                run = row['runs']['basic']
                self.assertTrue(run['save_resume_verified'])
                self.assertEqual(run['objective_result']['status'], 'active')
                self.assertEqual(run['metrics']['days'], 1)
                self.assertAlmostEqual(run['metrics']['starting_funds']+run['metrics']['income']-
                                       run['metrics']['expenses'], run['metrics']['final_funds'])

    def test_preparation_completion_finance_calendar_day_and_real_events(self):
        real_conditions = evaluation.evaluation_conditions

        def easy(preset, customer, objective):
            conditions = real_conditions(preset, customer, objective)
            conditions['store_events']['probability'] = 0
            conditions.pop('intake_request', None)
            if objective == 'bond':
                conditions['bond'] = dict(target=1, affinity=.5)
            else:
                conditions['patron'].pop('members')
                conditions['patron']['target'] = 25
            return conditions

        with patch.object(evaluation, 'evaluation_conditions', side_effect=easy):
            for objective in ('bond', 'patron'):
                report = evaluation.evaluate(objective=objective, scenarios=['clear'], max_days=10, emit=lambda _: None)
                run = report['runs']['clear']
                metrics = run['metrics']
                self.assertEqual(run['reason'], 'completed')
                self.assertEqual(run['objective_result']['resolved_day'], run['current_day'])
                self.assertTrue(run['save_resume_verified'])
                self.assertEqual(metrics['days'], len(run['daily']))
                self.assertAlmostEqual(metrics['starting_funds']+metrics['income']-metrics['expenses'], metrics['final_funds'])
                self.assertAlmostEqual(metrics['expenses'], sum(metrics['expense_breakdown'].values()))
                if objective == 'bond':
                    self.assertEqual(metrics['days'], 0)
                    self.assertEqual(run['objective_result']['sets'], 1)
                    self.assertGreater(run['objective_result']['stamina_spent'], 0)
                    self.assertGreater(run['objective_result']['affinity_gain'], 0)
                    self.assertEqual(metrics['uncompleted_day_finance']['total_expenses'], metrics['expenses'])
                else:
                    self.assertEqual(run['objective_result']['received'], 1)
                    self.assertEqual(run['objective_result']['members']['patron_visit']['match_rate'], None)

    def test_same_seed_common_window_uses_closed_days_and_excludes_preparation(self):
        report = evaluation.evaluate(scenarios=['clear', 'fast'], max_days=2, emit=lambda _: None)
        snapshot = copy.deepcopy(report)
        for run in report['runs'].values():
            window = run['common_window_metrics']
            self.assertEqual(window['days'], 2)
            self.assertAlmostEqual(window['income'], sum(row['summary']['total_income'] for row in run['daily']))
            self.assertEqual(window['final_funds'], run['daily'][-1]['summary']['closing_funds'])
            self.assertNotIn('uncompleted_day_finance', window)
        summary = evaluation.combine_reports([report])['summary']
        self.assertEqual(summary['paired']['common_window']['trials'], 1)
        self.assertEqual(summary['paired']['common_window']['days']['mean'], 2)
        self.assertEqual(report, snapshot)

    def test_window_excludes_later_runaways_expansion_and_popularity(self):
        from cat_cafe_sim.cafe_new_game import create_game
        from cat_cafe_sim.cafe_autoplay import AutoPlayer
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            result = AutoPlayer(session, mode='basic', max_days=3).run()
            core = copy.copy(session.core)
            core.day_results = [*core.day_results, core.day_result()]
            core.closed = False
            core.management = copy.deepcopy(core.management)
            core.management['events'] = {'later': {'departed_day': 3}}
            core.management['popularity'] = 999
            core.seats = [None]*8
            metrics = completed_window(core, result, 1)
            first = core.day_results[0]
            self.assertEqual(metrics['runaways'], 0)
            self.assertEqual(metrics['seats'], first['summary']['seat_count'])
            self.assertEqual(metrics['final_popularity'], first['summary']['popularity'])
            self.assertEqual(completed_window(core, result, 3)['runaways'], 1)

    def test_patron_counts_received_conditions_not_pending_or_unconditional_visits(self):
        rules = dict(name='地域', target=100, destination={'id': 'patron_visit'}, members=[
            dict(id='patron_moody_visit', name='気分', target=100)])
        visits = {str(i): dict(destination={'id': destination}, status=status,
                              **({'patron_match': dict(matched=matched)} if matched is not None else {}))
                  for i, (destination, status, matched) in enumerate([
                      ('patron_visit', 'resolved', None), ('patron_moody_visit', 'resolved', True),
                      ('patron_moody_visit', 'resolved', False), ('patron_moody_visit', 'traveling', True),
                      ('other', 'resolved', True)])}
        core = SimpleNamespace(goal=None, bond_goal=None,
            patron=dict(rules=rules, status='active', resolved_day=None, satisfaction=25,
                        members={'patron_moody_visit': 22}), activities=dict(events=visits))
        before = copy.deepcopy(core)
        result = objective_result(core, 'patron')
        self.assertEqual((result['dispatched'], result['received']), (4, 3))
        member = result['members']['patron_moody_visit']
        self.assertEqual((member['matched'], member['unmatched'], member['pending']), (1, 1, 1))
        self.assertEqual(member['match_rate'], .5)
        second = copy.deepcopy(result)
        second['members']['patron_moody_visit'].update(conditional_visits=1, matched=1, unmatched=0)
        summary = summarize_objective([dict(objective_result=r) for r in (result, second)])
        self.assertAlmostEqual(summary['by_member']['patron_moody_visit']['match_rate'], 2/3)
        self.assertIsNone(summary['by_member']['patron_visit']['match_rate'])
        self.assertEqual(core, before)

    def test_old_reports_default_to_popularity_and_mixed_objectives_are_rejected(self):
        report = evaluation.evaluate(max_days=1, scenarios=['basic'], emit=lambda _: None)
        report.pop('objective')
        self.assertEqual(evaluation.combine_reports([report])['objective'], 'popularity')
        other = copy.deepcopy(report)
        other.update(seed=1, objective='bond')
        with self.assertRaises(ValueError):
            evaluation.combine_reports([report, other])

    def test_cli_multiple_objectives_are_grouped_and_single_format_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'report.json'
            with redirect_stdout(io.StringIO()):
                evaluation.main(['--objectives', 'popularity', 'bond', 'patron', '--seeds', '1', '0',
                                 '--days', '1', '--scenarios', 'basic', '--output', str(output)])
            report = json.loads(output.read_text())
            self.assertEqual(report['format_version'], 3)
            self.assertEqual(list(report['by_objective']), list(evaluation.OBJECTIVES))
            for objective, group in report['by_objective'].items():
                self.assertEqual(group['seeds'], [1, 0])
                self.assertEqual(group['objective'], objective)
            with redirect_stdout(io.StringIO()):
                evaluation.main(['--objective', 'patron', '--days', '1', '--scenarios', 'basic', '--output', str(output)])
            self.assertEqual(json.loads(output.read_text())['format_version'], 1)
            for args in (['--objective', 'bond', '--goal-preset', 'legacy'],
                         ['--objectives', 'bond', 'bond'], ['--objective', 'bond', '--objectives', 'patron']):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    evaluation.main(args)
