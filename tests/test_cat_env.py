from dataclasses import asdict, replace
import unittest

from cat_cafe_sim.core import Command, SimulationCore
from cat_cafe_sim.core.config import Config

try:
    import numpy as np
    from gymnasium.utils.env_checker import check_env
    from cat_cafe_sim.envs import CatInteractionEnv
    from cat_cafe_sim.envs.rewards import CatRewards
except ModuleNotFoundError as error:
    if error.name not in ("gymnasium", "numpy"):
        raise
    CatInteractionEnv = None


@unittest.skipIf(CatInteractionEnv is None, "install requirements-env.txt for Gymnasium tests")
class CatEnvTests(unittest.TestCase):
    def env(self, **kwargs):
        return CatInteractionEnv(replace(Config.load(), arrival_ticks=(0,), **kwargs))

    def test_official_checker(self):
        check_env(CatInteractionEnv(), skip_render_check=True)

    def test_matches_core_for_identical_actions(self):
        env = self.env()
        env.reset(seed=11)
        core = SimulationCore(env.core.config, seed=env.core.seed)
        actions = [1, 1, 6, 4, 4, 2] * 7
        for index, action in enumerate(actions):
            observation, reward, terminated, truncated, info = env.step(action)
            _, events = core.step(Command("assign", "guest-1") if index == 0 else Command(), cat_action=action)
            self.assertEqual(env.core.snapshot(), core.snapshot())
            self.assertEqual(info["events"], events)
            self.assertAlmostEqual(reward, sum(info["reward_breakdown"].values()))
            self.assertTrue(env.observation_space.contains(observation))
            if terminated or truncated:
                break
        self.assertTrue(terminated)

    def test_success_perfect_closing_and_reward_priority(self):
        env = self.env(opening_ticks=1, max_stamina=15, satisfaction_target=20)
        observation, info = env.reset(seed=4)
        self.assertEqual(observation["remaining_ticks"], 1)
        _, reward, terminated, truncated, info = env.step(1)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["departure_reason"], "success")
        self.assertEqual(info["accounting"], {"base_charge": 10, "bonus": 200, "bill": 210})
        self.assertEqual(info["reward_breakdown"]["spirit"], 0)
        self.assertEqual(info["reward_breakdown"]["perfect"], 10)
        self.assertAlmostEqual(reward, 58)
        self.assertFalse(info["action_mask"].any())
        before = env.core.snapshot()
        with self.assertRaises(RuntimeError):
            env.step(1)
        self.assertEqual(env.core.snapshot(), before)

    def test_refill_failure_boundaries(self):
        for spirit, allow, failed in [(29, False, True), (30, False, True), (30, True, False), (31, False, False)]:
            with self.subTest(spirit=spirit, allow=allow):
                env = self.env(max_stamina=15, max_spirit=spirit, allow_zero_spirit_after_refill=allow)
                env.reset()
                observation, reward, terminated, truncated, info = env.step(1)
                self.assertEqual(terminated, failed)
                self.assertFalse(truncated)
                self.assertTrue(env.observation_space.contains(observation))
                self.assertEqual(info["reward_breakdown"]["spirit"], -6 if spirit >= 30 else 0)
                self.assertEqual(info["reward_breakdown"]["failure"], -30 if failed else 0)
                self.assertEqual(info["reward_breakdown"]["discontent"], -5 if failed else 0)

    def test_closing_terminates_without_failure_reward(self):
        env = self.env(opening_ticks=2)
        env.reset()
        env.step(6)
        _, _, terminated, truncated, info = env.step(6)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["departure_reason"], "closing")
        self.assertEqual(info["accounting"]["bill"], 20)
        self.assertEqual(info["reward_breakdown"]["failure"], 0)
        self.assertEqual(info["reward_breakdown"]["discontent"], 0)

    def test_external_limit_truncates_without_settlement(self):
        env = CatInteractionEnv(max_steps=1)
        env.reset()
        observation, _, terminated, truncated, info = env.step(6)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertIsNone(info["departure_reason"])
        self.assertEqual(info["accounting"]["bill"], 0)
        self.assertEqual(observation["remaining_ticks"], 39)
        self.assertFalse(env.core.closed)
        with self.assertRaises(RuntimeError):
            env.step(6)
        env.reset()
        self.assertEqual(env.core.tick, 0)

    def test_task_end_takes_priority_over_external_limit(self):
        env = CatInteractionEnv(replace(Config.load(), satisfaction_target=20), max_steps=1)
        env.reset()
        _, _, terminated, truncated, _ = env.step(1)
        self.assertTrue(terminated)
        self.assertFalse(truncated)

    def test_negative_reward_is_signed_and_stamina_is_actual_consumption(self):
        base = Config.load()
        actions = list(base.actions)
        actions[0] = replace(actions[0], satisfaction=-50, stamina_cost=200)
        env = CatInteractionEnv(replace(base, actions=tuple(actions)))
        env.reset()
        env.step(1)
        _, _, _, _, info = env.step(0)
        self.assertEqual(info["reward_breakdown"]["satisfaction"], -20)
        self.assertEqual(info["reward_breakdown"]["stamina"], -8.5)
        self.assertEqual(info["reward_breakdown"]["spirit"], -6)

    def test_reward_uses_clipped_gain_not_raw_effect(self):
        env = self.env(satisfaction_target=5)
        env.reset()
        _, _, _, _, info = env.step(1)
        self.assertEqual(info["reward_breakdown"]["satisfaction"], 5)

    def test_private_preferences_not_in_observation_or_info(self):
        env = CatInteractionEnv()
        observation, info = env.reset(seed=5, options={"preferences": (0, 2)})
        other = CatInteractionEnv()
        other_observation, _ = other.reset(seed=5)
        for key in observation:
            np.testing.assert_equal(observation[key], other_observation[key])
        self.assertNotIn("preferences", info)
        _, _, _, _, info = env.step(1)
        self.assertEqual(info["metrics"]["satisfaction"], 0)
        self.assertNotIn("preferences", info)
        env.reset(seed=5)
        self.assertEqual(env.core.config.preferences, env.config.preferences)

    def test_invalid_action_does_not_mutate_state(self):
        env = CatInteractionEnv()
        with self.assertRaises(RuntimeError):
            env.step(0)
        env.reset()
        before = env.core.snapshot()
        for action in (-1, 7, 1.5, True, "1", None):
            with self.subTest(action=action), self.assertRaises(ValueError):
                env.step(action)
            self.assertEqual(env.core.snapshot(), before)
        env.step(np.int64(1))

    def test_reset_clears_history_and_all_returns_are_in_space(self):
        env = CatInteractionEnv()
        for seed in range(10):
            observation, info = env.reset(seed=seed)
            self.assertEqual(observation["previous_action"], 7)
            self.assertEqual(observation["last_interaction_kind"], 2)
            self.assertEqual(observation["interaction_streak"], 0)
            self.assertEqual(info["metrics"]["seated_ticks"], 0)
            env.action_space.seed(seed)
            while True:
                self.assertTrue(env.observation_space.contains(observation))
                observation, _, terminated, truncated, _ = env.step(env.action_space.sample())
                if terminated or truncated:
                    self.assertTrue(env.observation_space.contains(observation))
                    break

    def test_seed_and_action_sequence_reproduces_every_step(self):
        env = CatInteractionEnv()
        runs = []
        for _ in range(2):
            env.reset(seed=42)
            steps = []
            for action in [1, 1, 6, 4, 4, 2] * 7:
                obs, reward, term, trunc, info = env.step(action)
                steps.append((obs, reward, term, trunc, info))
                if term or trunc:
                    break
            runs.append(steps)
        self.assertEqual(len(runs[0]), len(runs[1]))
        for left, right in zip(*runs):
            for key in left[0]:
                np.testing.assert_equal(left[0][key], right[0][key])
            self.assertEqual(left[1:4], right[1:4])
            np.testing.assert_equal(left[4]["action_mask"], right[4]["action_mask"])
            self.assertEqual(left[4]["events"], right[4]["events"])

    def test_config_and_reset_option_validation(self):
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                CatInteractionEnv(max_steps=limit)
        env = CatInteractionEnv()
        with self.assertRaises(ValueError):
            env.reset(options={"unknown": 1})
        with self.assertRaises(ValueError):
            env.reset(options={"preferences": (-1, 1)})
        for coefficient in (-1, float("nan"), True):
            data = asdict(CatRewards.load())
            data["time"] = coefficient
            with self.assertRaises(ValueError):
                CatRewards(**data)
