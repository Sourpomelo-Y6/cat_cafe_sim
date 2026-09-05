import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cat_cafe_sim.core import Command, SimulationCore
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.policies import FixedManagerPolicy
from cat_cafe_sim.replay import save, verify

try:
    from cat_cafe_sim.envs import CatInteractionEnv
    from cat_cafe_sim.envs.rewards import CatRewards
    from cat_cafe_sim.policies.learned import LearnedCatPolicy
    from cat_cafe_sim.training.encoding import StateEncoder
    from cat_cafe_sim.training.model import CatModel
    from cat_cafe_sim.training.q_learning import QLearningAgent
    from cat_cafe_sim.training.settings import TrainingSettings
except ModuleNotFoundError as error:
    if error.name not in ("gymnasium", "numpy"):
        raise
    LearnedCatPolicy = None


@unittest.skipIf(LearnedCatPolicy is None, "install requirements-env.txt for learned cafe tests")
class LearnedCafeTests(unittest.TestCase):
    def model(self, **overrides):
        config = replace(Config.load(), **overrides)
        settings = replace(TrainingSettings.load(), episodes=10)
        encoder = StateEncoder.for_config(config, settings.resource_edges, settings.time_edges)
        agent = QLearningAgent(encoder, learning_rate=settings.learning_rate, discount=settings.discount)
        # 空表の推論は有効行動の最小ID=0。境界条件を意図した行動で検証できる。
        return CatModel(agent, config, CatRewards.load(), settings)

    def core(self, model):
        return SimulationCore(model.config, seed=42, cat_policy=LearnedCatPolicy(model))

    def test_two_customers_reset_satisfaction_and_history_but_keep_resources(self):
        model = self.model(opening_ticks=2, arrival_ticks=(0, 1), satisfaction_target=12)
        core = self.core(model)
        seen = []
        original = core.cat_policy.choose

        def choose(obs):
            seen.append(dict(obs))
            return original(obs)

        core.cat_policy.choose = choose
        while not core.closed:
            core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual(core.summary()["successes"], 2)
        self.assertEqual([o["satisfaction"] for o in seen], [0, 0])
        self.assertEqual([o["interaction_streak"] for o in seen], [0, 0])
        self.assertEqual([o["last_interaction_kind"] for o in seen], [None, None])
        self.assertEqual([o["previous_action"] for o in seen], [None, None])
        self.assertEqual([o["stamina"] for o in seen], [100, 92])
        self.assertEqual([o["remaining_ticks"] for o in seen], [2, 1])
        self.assertTrue(all(o["first_action"] for o in seen))

    def test_exact_exhaustion_success_refills_only_before_next_customer(self):
        model = self.model(opening_ticks=2, arrival_ticks=(0, 1), max_stamina=8, satisfaction_target=12)
        core = self.core(model)
        core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual((core.cat.stamina, core.cat.spirit), (0, 100))
        core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual((core.cat.stamina, core.cat.spirit), (0, 70))
        self.assertEqual(core.summary()["perfect_successes"], 2)
        self.assertEqual(core.funds, 420)
        kinds = [e["kind"] for e in core.records[1]["events"]]
        self.assertLess(kinds.index("refill"), kinds.index("action"))

    def test_known_q_rows_select_actions_for_each_customer(self):
        model = self.model(opening_ticks=2, arrival_ticks=(0, 1), satisfaction_target=20)
        for stamina, remaining, action in ((1.0, 2, 1), (.85, 1, 2)):
            state = model.agent.encoder.encode({"resources": [0, stamina, 1],
                "last_interaction_kind": 2, "interaction_streak": 0, "remaining_ticks": remaining})
            model.agent.table[state] = [10.0 if i == action else 0.0 for i in range(7)]
        core = self.core(model)
        while not core.closed:
            core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual([e["action"] for e in core.events if e["kind"] == "action"], [1, 2])
        self.assertEqual(core.summary()["successes"], 2)
        self.assertEqual(core.cat_policy.unknown_states, 0)

    def test_low_spirit_boundaries_and_no_actions_after_failure(self):
        for spirit, allow, failed in ((29, False, True), (30, False, True),
                                      (30, True, False), (31, False, False)):
            with self.subTest(spirit=spirit, allow=allow):
                model = self.model(opening_ticks=2, arrival_ticks=(0,), max_stamina=8,
                                   max_spirit=spirit, allow_zero_spirit_after_refill=allow)
                core = self.core(model)
                core.step(manager_policy=FixedManagerPolicy())
                self.assertEqual(core.cat.cannot_continue, failed)
                core.step(manager_policy=FixedManagerPolicy())
                self.assertEqual(core.cat_policy.decisions, 1 if failed else 2)
                departures = [e for e in core.events if e["kind"] == "departure"]
                self.assertEqual(len(departures), 1)
                self.assertEqual(core.funds, departures[0]["bill"])

    def test_closed_last_tick_and_success_priority(self):
        for target, reason in ((12, "success"), (100, "closing")):
            model = self.model(arrival_ticks=(39,), satisfaction_target=target, max_stamina=8)
            core = self.core(model)
            while not core.closed:
                core.step(manager_policy=FixedManagerPolicy())
            visit = core.visits["guest-1"]
            self.assertEqual(visit.departure_reason, reason)
            self.assertEqual(visit.seated_ticks, 1)
            self.assertEqual(visit.discontent, 0)
            self.assertEqual(core.cat_policy.decisions, 1)
            with self.assertRaises(RuntimeError):
                core.step()

    def test_adverse_preferences_close_or_fail_without_fake_success(self):
        model = self.model()
        config = replace(model.config, preferences=(0, 0))
        core = SimulationCore(config, cat_policy=LearnedCatPolicy(model))
        while not core.closed:
            core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual(core.summary()["successes"], 0)
        self.assertTrue(all(v.satisfaction == 0 for v in core.visits.values()))
        self.assertEqual(core.summary()["revenue"], sum(v.bill for v in core.visits.values()))

    def test_config_compatibility_rejected_before_simulation(self):
        model = self.model()
        for overrides in ({"max_stamina": 50}, {"max_spirit": 30}, {"satisfaction_target": 50},
                          {"boredom_decay": 0}, {"opening_ticks": 41}, {"time_price": 20}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "mismatch"):
                SimulationCore(replace(model.config, **overrides), cat_policy=LearnedCatPolicy(model))
        compatible = replace(model.config, opening_ticks=10, arrival_ticks=(0, 3, 9),
                             preferences=(0.2, 0.1), max_wait_ticks=2, queue_capacity=2, initial_funds=50)
        core = SimulationCore(compatible, cat_policy=LearnedCatPolicy(model))
        while not core.closed:
            core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual(core.tick, 10)

    def test_float32_observation_matches_training_at_bin_boundary(self):
        model = self.model()
        env = CatInteractionEnv(model.config, model.rewards)
        env.reset(seed=42)
        env.step(6)
        env.core.visits["guest-1"].satisfaction = 25.000001
        observation = env._observation()
        state = model.agent.encoder.encode(observation)
        self.assertEqual(state[0], 1)  # float32では正規化後0.25へ丸められる
        model.agent.table[state] = [0, 0, 0, 0, 5, 0, 0]
        raw = {"satisfaction": 25.000001, "stamina": 100, "spirit": 100,
               "previous_action": 6, "last_interaction_kind": None, "interaction_streak": 0,
               "remaining_ticks": 39, "first_action": False, "first_visit": True, "first_meeting": True}
        policy = LearnedCatPolicy(model)
        self.assertEqual(policy.choose(raw), 4)
        self.assertEqual(policy.diagnostics()["unknown_states"], 0)

    def test_policy_inference_does_not_learn_or_advance_rng(self):
        model = self.model()
        before, rng = copy.deepcopy(model.agent.table), model.agent.rng.getstate()
        core = self.core(model)
        while not core.closed:
            core.step(manager_policy=FixedManagerPolicy())
        self.assertEqual(model.agent.table, before)
        self.assertEqual(model.agent.updates, 0)
        self.assertEqual(model.agent.rng.getstate(), rng)
        self.assertEqual(core.cat_policy.decisions, core.service_ticks)
        self.assertEqual(core.cat_policy.unknown_states, core.service_ticks)

    def test_learned_log_replays_without_model_and_preserves_provenance(self):
        model = self.model()
        with tempfile.TemporaryDirectory() as directory:
            model_path, log = Path(directory) / "model.json", Path(directory) / "day.json"
            model.save(model_path)
            policy = LearnedCatPolicy.load(model_path)
            core = SimulationCore(model.config, seed=42, cat_policy=policy)
            while not core.closed:
                core.step(manager_policy=FixedManagerPolicy())
            save(core, log)
            payload = json.loads(log.read_text())
            self.assertEqual(payload["cat_policy_metadata"]["model_sha256"], hashlib.sha256(model_path.read_bytes()).hexdigest())
            self.assertEqual(payload["cat_policy_metadata"]["decisions"], core.service_ticks)
            model_path.unlink()
            self.assertEqual(verify(log).records, core.records)

    def test_cli_learned_uses_model_config_and_rejects_bad_arguments(self):
        model = self.model(opening_ticks=2, arrival_ticks=(0, 1), satisfaction_target=12)
        with tempfile.TemporaryDirectory() as directory:
            model_path, log = Path(directory) / "model.json", Path(directory) / "day.json"
            model.save(model_path)
            command = [sys.executable, "-m", "cat_cafe_sim", "run"]
            result = subprocess.run(command + ["--policy", "learned", "--model", str(model_path), "--output", str(log)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["ticks"], 2)
            self.assertEqual(output["successes"], 2)
            self.assertIn("policy_diagnostics", output)
            self.assertTrue(log.with_suffix(".csv").exists())
            for arguments in (["--policy", "learned"], ["--model", str(model_path)],
                              ["--policy", "learned", "--model", str(model_path), "--config", "config/default.json"]):
                failed = subprocess.run(command + arguments, capture_output=True, text=True)
                self.assertNotEqual(failed.returncode, 0)
                self.assertNotIn("Traceback", failed.stderr)

    def test_standard_cli_does_not_import_learning_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            # -Sでsite-packagesを外して固定営業と学習済みログの再生を確認する。
            model = self.model()
            core = self.core(model)
            while not core.closed:
                core.step(manager_policy=FixedManagerPolicy())
            log = Path(directory) / "learned.json"
            save(core, log)
            for args in (["run", "--output", str(Path(directory) / "fixed.json")], ["replay", str(log)]):
                result = subprocess.run([sys.executable, "-S", "-m", "cat_cafe_sim", *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
