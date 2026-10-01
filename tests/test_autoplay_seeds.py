import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.autoplay_evaluation import evaluate, evaluate_seeds, combine_reports, main
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction


class SeedEvaluationTests(unittest.TestCase):
    def test_seed_is_set_before_initialization_and_survives_save_replay(self):
        with tempfile.TemporaryDirectory() as root:
            selected = starting_conditions()
            before = copy.deepcopy(selected)
            session = create_game(root, selected, seed=7)
            self.assertEqual(session.core.seed, 7)
            self.assertEqual(session.core.log()['seed'], 7)
            self.assertEqual(verify_cafe_interaction(session.core.log()).snapshot(), session.core.snapshot())
            save_game(session, session.checkpoint_path)
            loaded = load_game(session.checkpoint_path)[0]
            self.assertEqual(loaded.core.seed, 7)
            self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
            self.assertEqual(selected, before)
            self.assertEqual(create_game(root).core.seed, 0)

    def test_nonzero_seed_is_repeatable_and_changes_actual_results(self):
        options = dict(max_days=2, scenarios=('basic',), emit=lambda _: None)
        a, b, zero = evaluate(seed=7, **options), evaluate(seed=7, **options), evaluate(**options)
        self.assertEqual(a['runs'], b['runs'])
        self.assertEqual(a['seed'], 7)
        self.assertEqual(a['conditions_sha256'], zero['conditions_sha256'])
        self.assertNotEqual(a['runs']['basic']['daily'], zero['runs']['basic']['daily'])

    def test_multiple_seeds_retain_order_and_metrics_without_daily(self):
        report = evaluate_seeds((2, 0), max_days=1, scenarios=('basic',), emit=lambda _: None)
        self.assertEqual(report['seeds'], [2, 0])
        self.assertEqual(report['format_version'], 2)
        self.assertEqual([r['seed'] for r in report['evaluations']], [2, 0])
        self.assertNotIn('daily', report['evaluations'][0]['runs']['basic'])
        summary = report['summary']['by_scenario']['basic']
        self.assertEqual(summary['stop_reasons'], {'day_limit': 2})
        self.assertEqual(summary['completion_days'], dict(count=0, mean=None, min=None, max=None))
        self.assertEqual(summary['stages'][0]['achievement_rate'], 0)

    def test_summary_excludes_failures_from_days_and_pairs_only_same_seed(self):
        base = evaluate(max_days=1, scenarios=('clear', 'fast'), emit=lambda _: None)
        reports = []
        for seed, clear_days, fast_days in ((0, 40, 39), (1, 38, 40), (2, 30, None)):
            report = copy.deepcopy(base)
            report['seed'] = seed
            for name, days in (('clear', clear_days), ('fast', fast_days)):
                run = report['runs'][name]
                run['reason'] = 'completed' if days is not None else 'expired'
                run['metrics']['days'] = days if days is not None else 20
                run['stages'] = [dict(stage=1, status='cleared' if days else 'expired',
                                      resolved_day=10 if days else 20, spare_days=10 if days else 0)]
            reports.append(report)
        blocked = copy.deepcopy(base)
        blocked['seed'] = 3
        for run in blocked['runs'].values():
            run['reason'] = 'blocked'
            run['metrics']['days'] = 3
            run['stages'][0].update(status='active', resolved_day=None, spare_days=None)
        reports.append(blocked)
        snapshot = copy.deepcopy(reports)
        result = combine_reports(reports)['summary']
        self.assertEqual(result['by_scenario']['fast']['completion_rate'], .5)
        self.assertEqual(result['by_scenario']['fast']['completion_days']['mean'], 39.5)
        self.assertEqual(result['by_scenario']['fast']['stages'][0]['expired'], 1)
        self.assertEqual(result['by_scenario']['fast']['stop_reasons'], {'blocked': 1, 'completed': 2, 'expired': 1})
        paired = result['paired']
        self.assertEqual((paired['both_completed'], paired['fast_earlier'], paired['clear_earlier']), (2, 1, 1))
        self.assertEqual(paired['only_clear_completed'], 1)
        self.assertEqual(paired['fast_minus_clear_days']['mean'], .5)
        self.assertEqual(reports, snapshot)

    def test_invalid_seed_and_mixed_comparisons_are_rejected(self):
        for seed in (-1, True, '1'):
            with self.assertRaises(ValueError):
                evaluate(seed=seed)
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):
                    create_game(Path(root)/'unused', seed=seed)
                self.assertFalse((Path(root)/'unused').exists())
        for seeds in ((), (0, 0), (-1,), (True,)):
            with self.assertRaises(ValueError):
                evaluate_seeds(seeds)
        base = evaluate(max_days=1, scenarios=('basic',), emit=lambda _: None)
        other = copy.deepcopy(base)
        other['seed'] = 1
        other['max_days'] = 2
        for reports in ([], [base, base], [base, other]):
            with self.assertRaises(ValueError):
                combine_reports(reports)

    def test_cli_seed_options_and_default_preserve_single_format(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)/'report.json'
            for args, expected in (([], 0), (['--seed', '7'], 7), (['--seeds', '0', '7'], [0, 7])):
                with redirect_stdout(io.StringIO()):
                    main(['--days', '1', '--scenarios', 'basic', '--output', str(output), *args])
                report = json.loads(output.read_text())
                self.assertEqual(report['seeds'] if isinstance(expected, list) else report['seed'], expected)
            for args in (['--seed', '-1'], ['--seeds', '0', '0'], ['--seed', '0', '--seeds', '1']):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
