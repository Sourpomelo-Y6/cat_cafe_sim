import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core.config import Config
from cat_cafe_sim.training.encoding import StateEncoder
from cat_cafe_sim.training.settings import TrainingSettings

try:
    from cat_cafe_sim.envs.rewards import CatRewards
    from cat_cafe_sim.training.runner import train
    from cat_cafe_sim.training.model import CatModel
    from cat_cafe_sim.evaluation.failures import analyze_log
    from cat_cafe_sim.policies.learned import LearnedCatPolicy
    from cat_cafe_sim.core import SimulationCore, StartState
    from cat_cafe_sim.policies import FixedManagerPolicy
    from cat_cafe_sim.replay import save
except ModuleNotFoundError as error:
    if error.name not in ('gymnasium', 'numpy'):
        raise
    CatModel = None


class StaminaEncodingTests(unittest.TestCase):
    def setUp(self):
        self.settings = TrainingSettings.load('config/cat_training_stamina.json')
        self.old = StateEncoder.for_config(Config.load(), self.settings.resource_edges, self.settings.time_edges)
        self.new = StateEncoder.for_config(Config.load(), self.settings.resource_edges, self.settings.time_edges, self.settings.stamina_edges)

    def observation(self, stamina):
        return dict(resources=[.6, stamina, .1], last_interaction_kind=0,
                    interaction_streak=2, remaining_ticks=10)

    def test_only_stamina_resolution_changes(self):
        old = [self.old.encode(self.observation(x)) for x in (.03, .08, .11, .24)]
        new = [self.new.encode(self.observation(x)) for x in (.03, .08, .11, .24)]
        self.assertEqual(len(set(old)), 1)
        self.assertEqual(len(set(new)), 4)
        for a, b in zip(old, new):
            self.assertEqual(a[:1] + a[2:], b[:1] + b[2:])
        self.assertEqual(self.new.summary()['state_upper_bound'], 26136)

    def test_float32_threshold_equality(self):
        for edge in self.settings.stamina_edges:
            exact = self.new.encode(self.observation(edge))[1]
            rounded = self.new.encode(self.observation(StateEncoder._float32(edge)))[1]
            above = self.new.encode(self.observation(edge + .00001))[1]
            self.assertEqual(exact, rounded)
            self.assertEqual(above, exact + 1)

    def test_invalid_edges_and_version(self):
        for edges in ((.1, .1), (.2, .1), (float('nan'),), (.1, .10000000001), (1.0,)):
            with self.assertRaises(ValueError):
                replace(self.new, stamina_edges=edges)
        with self.assertRaises(ValueError):
            replace(self.old, stamina_edges=(.1,))

    def test_legacy_and_candidate_roundtrip(self):
        legacy = self.old.to_dict()
        legacy.pop('stamina_edges')
        self.assertEqual(StateEncoder.from_dict(legacy), self.old)
        self.assertEqual(StateEncoder.from_dict(self.new.to_dict()), self.new)
        baseline = json.loads(Path('config/cat_training_mixed.json').read_text())
        candidate = json.loads(Path('config/cat_training_stamina.json').read_text())
        candidate.pop('stamina_edges')
        self.assertEqual(baseline, candidate)
        self.assertIsNone(TrainingSettings.from_dict(baseline).stamina_edges)


@unittest.skipIf(CatModel is None, 'install requirements-env.txt')
class StaminaIntegrationTests(unittest.TestCase):
    def test_reproducibility_start_streams_and_model_roundtrip(self):
        settings = replace(TrainingSettings.load('config/cat_training_stamina.json'), episodes=30)
        config, rewards = Config.load(), CatRewards.load()
        model, rows = train(config, rewards, settings)
        repeat, repeat_rows = train(config, rewards, settings)
        self.assertEqual(rows, repeat_rows)
        self.assertEqual(model.agent.table, repeat.agent.table)
        _, baseline = train(config, rewards, replace(settings, stamina_edges=None))
        keys = [k for k in rows[0] if k.startswith('initial_')] + ['start_profile', 'scenario_seed', 'play_preference', 'pet_preference']
        self.assertEqual([[r[k] for k in keys] for r in rows], [[r[k] for k in keys] for r in baseline])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.json'
            model.save(path)
            loaded = CatModel.load(path)
            self.assertEqual(loaded.agent.encoder, model.agent.encoder)
            self.assertEqual(loaded.agent.table, model.agent.table)

    def test_failure_diagnostic_replay_and_fingerprint(self):
        settings = replace(TrainingSettings.load(), episodes=1)
        model, _ = train(Config.load(), CatRewards.load(), settings)
        model.agent.table.clear()
        with tempfile.TemporaryDirectory() as directory:
            path, log = Path(directory) / 'model.json', Path(directory) / 'day.json'
            model.save(path)
            policy = LearnedCatPolicy.load(path)
            core = SimulationCore(model.config, seed=42, start_state=StartState(3, 10, 0), cat_policy=policy)
            while not core.closed:
                core.step(manager_policy=FixedManagerPolicy())
            save(core, log)
            before = copy.deepcopy(policy.model.agent.table)
            failures = analyze_log(log, policy)
            self.assertTrue(failures)
            first = failures[0]
            self.assertEqual(first['action'], 0)
            self.assertEqual(first['alternatives_one_step'][0]['departure_reason'], 'failure')
            self.assertIsNone(first['alternatives_one_step'][6]['departure_reason'])
            self.assertEqual(policy.model.agent.table, before)
            data = json.loads(log.read_text())
            data['summary']['successes'] += 1
            log.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'summary'):
                analyze_log(log, policy)
            data['cat_policy_metadata']['model_sha256'] = 'wrong'
            log.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                analyze_log(log, policy)
