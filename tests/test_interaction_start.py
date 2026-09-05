import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core import Command, SimulationCore, StartState
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.replay import save, verify

try:
    import numpy as np
    from cat_cafe_sim.envs import CatInteractionEnv
except ModuleNotFoundError as error:
    if error.name not in ("gymnasium", "numpy"):
        raise
    CatInteractionEnv = None


class StartStateTests(unittest.TestCase):
    def test_validation_and_default_core_state(self):
        config = Config.load()
        core = SimulationCore(config)
        self.assertEqual(core.start_state, StartState(100, 100, 0))
        for initial in (StartState(0, 100), StartState(-1, 100), StartState(101, 100),
                        StartState(10, -1), StartState(10, 101), StartState(10, 0),
                        StartState(float("nan"), 100), StartState(10, float("inf")),
                        StartState(True, 10), StartState(10, True),
                        StartState(10, 10, -1), StartState(10, 10, 40),
                        StartState(10, 10, True), StartState(10, 10, 1.5)):
            with self.subTest(initial=initial), self.assertRaises(ValueError):
                SimulationCore(config, start_state=initial)

    def test_nondefault_start_replays_and_tampering_is_detected(self):
        config = replace(Config.load(), arrival_ticks=(37,))
        core = SimulationCore(config, seed=42, start_state=StartState(8, 29, 37))
        core.step(Command("assign", "guest-1"), cat_action=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start.json"
            save(core, path)
            loaded = verify(path)
            self.assertEqual(loaded.start_state, core.start_state)
            self.assertEqual(loaded.records, core.records)
            payload = json.loads(path.read_text())
            payload["start_state"]["stamina"] = 100
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify(path)

    def test_legacy_log_without_start_state_still_replays(self):
        core = SimulationCore()
        core.step(Command("assign", "guest-1"), cat_action=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            save(core, path)
            payload = json.loads(path.read_text())
            del payload["start_state"]
            path.write_text(json.dumps(payload))
            self.assertEqual(verify(path).records, core.records)


@unittest.skipIf(CatInteractionEnv is None, "install requirements-env.txt for environment tests")
class InteractionStartTests(unittest.TestCase):
    def test_reset_sets_resources_clock_and_public_initial_diagnostics(self):
        env = CatInteractionEnv()
        obs, info = env.reset(seed=42, options={"stamina": 12.5, "spirit": 29, "remaining_ticks": 3})
        self.assertTrue(env.observation_space.contains(obs))
        np.testing.assert_allclose(obs["resources"], [0, .125, .29])
        self.assertEqual(obs["remaining_ticks"], 3)
        self.assertEqual((obs["first_action"], obs["interaction_streak"], obs["last_interaction_kind"]), (1, 0, 2))
        self.assertEqual(info["initial_state"], {"stamina": 12.5, "spirit": 29, "remaining_ticks": 3})
        self.assertEqual(info["elapsed_steps"], 0)
        self.assertEqual(info["events"], [])
        self.assertEqual(env.core.tick, 37)
        self.assertEqual(env.core.spirit_spent, 0)
        self.assertEqual(env.core.funds, env.config.initial_funds)
        self.assertEqual(env.core.records, [])
        self.assertEqual(env.config.max_stamina, 100)
        self.assertEqual(env.config.opening_ticks, 40)

    def test_late_start_assigns_on_first_step_and_bills_only_elapsed_ticks(self):
        env = CatInteractionEnv()
        env.reset(options={"remaining_ticks": 3, "stamina": 20, "spirit": 40})
        for step in range(3):
            obs, _, terminated, truncated, info = env.step(6)
            self.assertEqual(info["elapsed_steps"], step + 1)
            self.assertEqual(obs["remaining_ticks"], 2 - step)
            self.assertEqual(terminated, step == 2)
            self.assertFalse(truncated)
        self.assertEqual(info["departure_reason"], "closing")
        self.assertEqual(info["accounting"], {"base_charge": 30, "bonus": 0, "bill": 30})
        self.assertEqual(env.core.visits["guest-1"].arrival_tick, 37)
        self.assertEqual(env.core.visits["guest-1"].seated_at, 37)
        self.assertEqual(info["metrics"]["seated_ticks"], 3)
        self.assertEqual(info["reward_breakdown"]["discontent"], 0)

    def test_external_limit_counts_from_start_not_absolute_tick(self):
        env = CatInteractionEnv(max_steps=2)
        env.reset(options={"remaining_ticks": 5})
        _, _, terminated, truncated, info = env.step(6)
        self.assertFalse(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["elapsed_steps"], 1)
        obs, _, terminated, truncated, info = env.step(6)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(obs["remaining_ticks"], 3)
        self.assertEqual(info["accounting"]["bill"], 0)
        self.assertFalse(info["action_mask"].any())
        self.assertTrue(info["bootstrap_action_mask"].all())
        with self.assertRaises(RuntimeError):
            env.step(6)

    def test_closing_takes_priority_over_external_limit_at_late_start(self):
        env = CatInteractionEnv(max_steps=1)
        env.reset(options={"remaining_ticks": 1})
        _, _, terminated, truncated, info = env.step(6)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["departure_reason"], "closing")
        self.assertEqual(info["accounting"]["bill"], 10)

    def test_low_stamina_and_spirit_failure_success_and_refill_boundaries(self):
        for spirit, allow, failed in ((29, False, True), (30, False, True),
                                      (31, False, False), (30, True, False)):
            config = replace(Config.load(), allow_zero_spirit_after_refill=allow)
            env = CatInteractionEnv(config)
            env.reset(options={"stamina": 8, "spirit": spirit, "remaining_ticks": 3})
            obs, _, terminated, truncated, info = env.step(0)
            with self.subTest(spirit=spirit, allow=allow):
                self.assertEqual(terminated, failed)
                self.assertFalse(truncated)
                self.assertTrue(env.observation_space.contains(obs))
                self.assertEqual(info["reward_breakdown"]["spirit"], -6 if spirit >= 30 else 0)
                self.assertEqual(info["metrics"]["spirit_spent"], 30 if spirit >= 30 else 0)
                self.assertEqual(info["reward_breakdown"]["failure"], -30 if failed else 0)
                self.assertEqual(env.core.cat.spirit, spirit - 30 if spirit >= 30 else spirit)

    def test_perfect_success_precedes_failure_and_closing_on_last_tick(self):
        env = CatInteractionEnv(replace(Config.load(), satisfaction_target=12), max_steps=1)
        env.reset(options={"stamina": 8, "spirit": 1, "remaining_ticks": 1})
        _, reward, terminated, truncated, info = env.step(0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["departure_reason"], "success")
        self.assertTrue(info["metrics"]["perfect"])
        self.assertEqual(info["accounting"]["bill"], 210)
        self.assertEqual(info["reward_breakdown"]["spirit"], 0)
        self.assertEqual(info["reward_breakdown"]["failure"], 0)
        self.assertEqual(env.core.cat.spirit, 1)
        self.assertAlmostEqual(reward, sum(info["reward_breakdown"].values()))

    def test_zero_spirit_is_only_allowed_by_existing_rule(self):
        with self.assertRaises(ValueError):
            CatInteractionEnv().reset(options={"spirit": 0})
        env = CatInteractionEnv(replace(Config.load(), allow_zero_spirit_after_refill=True))
        obs, _ = env.reset(options={"spirit": 0, "stamina": 8})
        self.assertTrue(env.observation_space.contains(obs))
        _, _, terminated, _, info = env.step(0)
        self.assertTrue(terminated)
        self.assertEqual(info["departure_reason"], "failure")
        self.assertEqual(info["reward_breakdown"]["spirit"], 0)

    def test_invalid_reset_is_transactional(self):
        env = CatInteractionEnv()
        env.reset(seed=42)
        env.step(6)
        original = env.core
        snapshot, rng = copy.deepcopy(env.core.snapshot()), copy.deepcopy(env.np_random.bit_generator.state)
        for options in ({"stamina": 0}, {"stamina": -1}, {"stamina": 101}, {"stamina": True},
                        {"stamina": float("nan")}, {"spirit": float("inf")}, {"spirit": -1},
                        {"spirit": 101}, {"remaining_ticks": 0}, {"remaining_ticks": 41},
                        {"remaining_ticks": 1.5}, {"remaining_ticks": True}, {"unknown": 1},
                        {"preferences": (-1, 1)}, [], 12):
            with self.subTest(options=options), self.assertRaises(ValueError):
                env.reset(seed=99, options=options)
            self.assertIs(env.core, original)
            self.assertEqual(env.core.snapshot(), snapshot)
            self.assertEqual(env.np_random.bit_generator.state, rng)
        self.assertEqual(env._elapsed_steps, 1)

    def test_omitting_options_restores_defaults_and_history(self):
        env = CatInteractionEnv()
        env.reset(seed=42, options={"stamina": 50, "spirit": 40, "remaining_ticks": 5, "preferences": (0, 2)})
        env.step(1)
        obs, info = env.reset(seed=42)
        np.testing.assert_equal(obs["resources"], [0, 1, 1])
        self.assertEqual(obs["remaining_ticks"], 40)
        self.assertEqual(obs["interaction_streak"], 0)
        self.assertEqual(obs["previous_action"], 7)
        self.assertEqual(info["elapsed_steps"], 0)
        self.assertEqual(env.core.config.preferences, (1, 1))
        self.assertEqual(env.core.start_state, StartState(100, 100, 0))

    def test_same_seed_options_and_actions_match_core_and_replay(self):
        env = CatInteractionEnv()
        options = {"stamina": 20, "spirit": 31, "remaining_ticks": 4, "preferences": (.8, 1.2)}
        runs = []
        for _ in range(2):
            env.reset(seed=42, options=options)
            core = SimulationCore(env.core.config, seed=env.core.seed, start_state=env.core.start_state)
            for step, action in enumerate((1, 4, 6, 4)):
                obs, reward, terminated, truncated, info = env.step(action)
                _, events = core.step(Command("assign", "guest-1") if step == 0 else Command(), cat_action=action)
                self.assertEqual(env.core.snapshot(), core.snapshot())
                self.assertEqual(info["events"], events)
                self.assertTrue(env.observation_space.contains(obs))
                self.assertAlmostEqual(reward, sum(info["reward_breakdown"].values()))
                if terminated or truncated:
                    break
            runs.append(copy.deepcopy(env.core.records))
        self.assertEqual(runs[0], runs[1])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late.json"
            save(env.core, path)
            self.assertEqual(verify(path).records, env.core.records)

    def test_numpy_scalars_are_accepted_and_replayable(self):
        env = CatInteractionEnv()
        env.reset(options={"stamina": np.float32(8), "spirit": np.float64(29), "remaining_ticks": np.int64(1)})
        env.step(0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "numpy.json"
            save(env.core, path)
            self.assertEqual(verify(path).records, env.core.records)
