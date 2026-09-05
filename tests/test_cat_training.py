import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core.config import Config
from cat_cafe_sim.training.settings import TrainingSettings

try:
    from cat_cafe_sim.envs import CatInteractionEnv
    from cat_cafe_sim.envs.rewards import CatRewards
    from cat_cafe_sim.training.model import CatModel
    from cat_cafe_sim.training.runner import train
    from cat_cafe_sim.evaluation.cat_policies import evaluate
except ModuleNotFoundError as error:
    if error.name not in ("gymnasium", "numpy"):
        raise
    CatInteractionEnv = None


@unittest.skipIf(CatInteractionEnv is None, "install requirements-env.txt for training integration tests")
class CatTrainingTests(unittest.TestCase):
    def train_small(self, **overrides):
        settings = replace(TrainingSettings.load(), episodes=30, **overrides)
        return train(Config.load(), CatRewards.load(), settings)

    def test_training_reproducibility_and_reward_logs(self):
        first, rows = self.train_small()
        second, other_rows = self.train_small()
        self.assertEqual(rows, other_rows)
        self.assertEqual(first.agent.table, second.agent.table)
        self.assertGreater(first.agent.updates, 0)
        self.assertLess(len(first.agent.table), first.agent.encoder.summary()["state_upper_bound"])
        self.assertEqual({(r["play_preference"], r["pet_preference"]) for r in rows}, set(first.settings.train_preferences))
        for row in rows:
            self.assertAlmostEqual(row["reward"], sum(row[f"reward_{key}"] for key in
                                   ("satisfaction", "success", "perfect", "stamina", "spirit", "discontent", "failure", "time")))
            self.assertEqual(sum(row[f"action_{i}"] for i in range(7)), row["seated_ticks"])

    def test_saved_model_reproduces_evaluation_and_bytes(self):
        model, _ = self.train_small()
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.json", Path(directory) / "second.json"
            model.save(first)
            loaded = CatModel.load(first)
            self.assertEqual(loaded.agent.table, model.agent.table)
            self.assertEqual(loaded.agent.updates, model.agent.updates)
            self.assertEqual(evaluate(loaded), evaluate(model))
            loaded.save(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_evaluation_uses_shared_cases_without_learning_or_exploration(self):
        model, _ = self.train_small()
        before = copy.deepcopy(model.agent.table)
        rng = model.agent.rng.getstate()
        updates = model.agent.updates
        report = evaluate(model, split="test")
        for policy in ("random", "fixed", "q_learning"):
            cases = {(tuple(r["preferences"]), r["seed"]) for r in report["episodes"] if r["policy"] == policy}
            self.assertEqual(cases, {(pair, seed) for pair in model.settings.test_preferences for seed in model.settings.test_seeds})
        self.assertEqual(model.agent.table, before)
        self.assertEqual(model.agent.rng.getstate(), rng)
        self.assertEqual(model.agent.updates, updates)
        self.assertFalse(report["learning"])
        self.assertFalse(report["exploration"])

    def test_incompatible_or_corrupt_model_rejected(self):
        model, _ = self.train_small()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save(path)
            original = json.loads(path.read_text())
            mutations = [lambda d: d.update(format_version=999),
                         lambda d: d.update(simulator_version="unknown"),
                         lambda d: d["encoder"].update(streak_cap=4),
                         lambda d: d["q_rows"][0].update(state=[999, 0, 0, 0, 0]),
                         lambda d: d["q_rows"][0].update(values=[1, 2]),
                         lambda d: d["q_rows"][0]["values"].__setitem__(0, float("nan")),
                         lambda d: d["q_rows"].append(d["q_rows"][0])]
            for mutate in mutations:
                data = copy.deepcopy(original)
                mutate(data)
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    CatModel.load(path)

    def test_budget_checked_before_any_learning(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            self.train_small(max_states=10)

    def test_truncated_environment_supplies_bootstrap_mask(self):
        env = CatInteractionEnv(max_steps=1)
        obs, _ = env.reset(seed=42)
        model, _ = self.train_small()
        next_obs, reward, terminated, truncated, info = env.step(6)
        self.assertTrue(truncated)
        self.assertFalse(terminated)
        self.assertFalse(info["action_mask"].any())
        self.assertTrue(info["bootstrap_action_mask"].all())
        state, next_state = model.agent.encoder.encode(obs), model.agent.encoder.encode(next_obs)
        model.agent.table[state] = [0.0] * 7
        model.agent.table[next_state] = [10.0] * 7
        old = model.agent.values(state)[6]
        updated = model.agent.update(state, 6, reward, next_state, terminated=terminated, truncated=truncated,
                                     next_mask=info["bootstrap_action_mask"])
        self.assertAlmostEqual(updated, old + model.agent.learning_rate * (reward + model.agent.discount * 10 - old))
