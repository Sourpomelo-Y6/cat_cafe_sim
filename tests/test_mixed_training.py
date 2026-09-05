import copy
from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest

from cat_cafe_sim.core.config import Config
from cat_cafe_sim.training.settings import TrainingSettings
from cat_cafe_sim.training.start_profiles import StartProfile, choose_start

MIXED = Path('config/cat_training_mixed.json')

try:
    from cat_cafe_sim.envs.rewards import CatRewards
    from cat_cafe_sim.training.runner import train
    from cat_cafe_sim.training.model import CatModel
    from cat_cafe_sim.evaluation.cat_policies import evaluate
    from cat_cafe_sim.evaluation.days import compare_days, validate_cases
    from cat_cafe_sim.policies.learned import LearnedCatPolicy
except ModuleNotFoundError as error:
    if error.name not in ('gymnasium', 'numpy'):
        raise
    CatModel = None


class StartProfileTests(unittest.TestCase):
    def test_mixture_weights_and_seed_reproducibility(self):
        profiles = TrainingSettings.load(MIXED).train_starts
        left, right = random.Random(42), random.Random(42)
        samples = [choose_start(profiles, left) for _ in range(5000)]
        self.assertEqual(samples, [choose_start(profiles, right) for _ in range(5000)])
        for name, fraction in (('full', .3), ('depleted', .5), ('late', .2)):
            count = sum(label == name for label, _ in samples)
            self.assertAlmostEqual(count / len(samples), fraction, delta=.025)
        for name, case in samples:
            profile = next(p for p in profiles if p.name == name)
            self.assertIn(case, list(profile.cases()))

    def test_missing_profiles_preserve_legacy_defaults_without_rng_use(self):
        settings = TrainingSettings.load()
        rng = random.Random(42)
        state = rng.getstate()
        self.assertEqual(choose_start(settings.train_starts, rng), ('default', {}))
        self.assertEqual(state, rng.getstate())
        self.assertEqual(TrainingSettings.from_dict(settings.to_dict()), settings)

    def test_profile_validation_and_split_disjointness(self):
        settings = TrainingSettings.load(MIXED)
        for weight in (0, -1, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                replace(settings.train_starts[0], weight=weight)
        with self.assertRaises(ValueError):
            replace(settings, test_starts=settings.train_starts)
        with self.assertRaises(ValueError):
            replace(settings, validation_starts=())
        with self.assertRaises(ValueError):
            replace(settings, train_starts=(settings.train_starts[0],) * 2)
        with self.assertRaises(ValueError):
            replace(settings.train_starts[0], stamina=(0,))
        with self.assertRaises(ValueError):
            replace(settings.train_starts[0], remaining_ticks=(1.5,))
        with self.assertRaises(ValueError):
            replace(settings.train_starts[0], stamina=(1000,)).validate_config(Config.load())
        with self.assertRaises(ValueError):
            replace(settings.train_starts[0], spirit=(0,)).validate_config(Config.load())
        self.assertEqual(TrainingSettings.from_dict(settings.to_dict()), settings)


@unittest.skipIf(CatModel is None, 'install requirements-env.txt for mixed training tests')
class MixedTrainingTests(unittest.TestCase):
    def model(self, mixed=True):
        settings = replace(TrainingSettings.load(MIXED) if mixed else TrainingSettings.load(), episodes=60)
        return train(Config.load(), CatRewards.load(), settings)

    def test_training_logs_actual_start_conditions_and_is_reproducible(self):
        model, rows = self.model()
        repeated, again = self.model()
        self.assertEqual(rows, again)
        self.assertEqual(model.agent.table, repeated.agent.table)
        self.assertEqual({r['start_profile'] for r in rows}, {'full', 'depleted', 'late'})
        for row in rows:
            profile = next(p for p in model.settings.train_starts if p.name == row['start_profile'])
            start = {k: row[f'initial_{k}'] for k in ('stamina', 'spirit', 'remaining_ticks')}
            self.assertIn(start, list(profile.cases()))
            self.assertLessEqual(row['seated_ticks'], start['remaining_ticks'])
        _, legacy = self.model(False)
        self.assertEqual([(r['play_preference'], r['pet_preference']) for r in rows],
                         [(r['play_preference'], r['pet_preference']) for r in legacy])

    def test_model_roundtrip_and_held_out_starts_evaluated_exhaustively(self):
        model, _ = self.model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.json'
            model.save(path)
            loaded = CatModel.load(path)
            self.assertEqual(loaded.settings, model.settings)
            report = evaluate(loaded, split='test')
            self.assertEqual(report, evaluate(model, split='test'))
            self.assertEqual(report['summary']['q_learning']['episodes'], 30)
            allowed = [case for p in model.settings.test_starts for case in p.cases()]
            for row in report['episodes']:
                self.assertIn(row['initial_state'], allowed)
                self.assertIn(tuple(row['preferences']), model.settings.test_preferences)

    def test_old_model_without_new_fields_loads(self):
        model, _ = self.model(False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.json'
            model.save(path)
            data = json.loads(path.read_text())
            for key in ('train_starts', 'validation_starts', 'test_starts'):
                del data['training'][key]
            path.write_text(json.dumps(data))
            loaded = CatModel.load(path)
            self.assertEqual(loaded.agent.table, model.agent.table)
            self.assertEqual(loaded.settings.train_starts, ())

    def test_bad_start_rejected_before_training(self):
        settings = TrainingSettings.load(MIXED)
        profile = replace(settings.train_starts[0], stamina=(200,))
        settings = replace(settings, train_starts=(profile,))
        progress = []
        with self.assertRaises(ValueError):
            train(Config.load(), CatRewards.load(), settings, progress=progress.append)
        self.assertEqual(progress, [])

    def test_day_comparison_shared_cases_frozen_models_and_replays(self):
        old, _ = self.model(False)
        new, _ = self.model()
        models = {'old_seed42': LearnedCatPolicy(old), 'new_seed42': LearnedCatPolicy(new)}
        manifest = json.loads(Path('config/cafe_evaluation.json').read_text())
        manifest['test']['seeds'] = [50000]
        tables = [copy.deepcopy(m.agent.table) for m in (old, new)]
        rngs = [m.agent.rng.getstate() for m in (old, new)]
        with tempfile.TemporaryDirectory() as directory:
            report = compare_days(models, manifest, log_dir=directory)
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 9)
            for label in ('fixed', 'old_seed42', 'new_seed42'):
                rows = [r for r in report['results'] if r['policy'] == label]
                self.assertEqual({r['scenario'] for r in rows}, {'test_play', 'test_pet', 'test_difficult'})
                self.assertEqual({r['seed'] for r in rows}, {50000})
                self.assertTrue(all(Path(r['replay']).is_file() for r in rows))
            delta = report['paired_new_minus_old']['new_seed42']['mean_revenue']
            self.assertAlmostEqual(delta, report['summary']['new_seed42']['mean_revenue'] - report['summary']['old_seed42']['mean_revenue'])
        for i, model in enumerate((old, new)):
            self.assertEqual(model.agent.table, tables[i])
            self.assertEqual(model.agent.rng.getstate(), rngs[i])

    def test_day_manifest_rejects_leakage_and_unsafe_names(self):
        old, _ = self.model(False)
        new, _ = self.model()
        models = {'old_seed42': LearnedCatPolicy(old), 'new_seed42': LearnedCatPolicy(new)}
        original = json.loads(Path('config/cafe_evaluation.json').read_text())
        mutations = [lambda d: d['test']['scenarios'][0].update(preferences=[1, 1]),
                     lambda d: d['test']['scenarios'][0].update(preferences=[1.1, .9]),
                     lambda d: d['test']['scenarios'][0].update(name='../bad'),
                     lambda d: d['test'].update(seeds=d['validation']['seeds']),
                     lambda d: d['test'].update(seeds=[10000])]
        for mutation in mutations:
            data = copy.deepcopy(original)
            mutation(data)
            with self.assertRaises(ValueError):
                validate_cases(data, models)
