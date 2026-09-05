from dataclasses import replace
import math
import unittest

from cat_cafe_sim.core.config import Config
from cat_cafe_sim.training.encoding import StateEncoder
from cat_cafe_sim.training.q_learning import QLearningAgent
from cat_cafe_sim.training.settings import TrainingSettings


def encoder():
    settings = TrainingSettings.load()
    return StateEncoder.for_config(Config.load(), settings.resource_edges, settings.time_edges)


def observation(**overrides):
    return {"resources": [0.0, 1.0, 1.0], "last_interaction_kind": 2,
            "interaction_streak": 0, "remaining_ticks": 40, **overrides}


class EncodingTests(unittest.TestCase):
    def test_state_budget_and_json_roundtrip(self):
        enc = encoder()
        self.assertEqual(enc.dimensions, (6, 6, 6, 11, 6))
        self.assertEqual(enc.summary()["state_upper_bound"], 14256)
        self.assertEqual(enc.summary()["dense_float64_bytes"], 798336)
        self.assertEqual(StateEncoder.from_dict(enc.to_dict()), enc)

    def test_resources_preserve_zero_maximum_and_edges(self):
        enc = encoder()
        for value, bucket in ((0, 0), (.00001, 1), (.25, 1), (.25001, 2),
                              (.5, 2), (.50001, 3), (.75, 3), (.75001, 4), (1, 5)):
            with self.subTest(value=value):
                self.assertEqual(enc.encode(observation(resources=[value] * 3))[:3], (bucket,) * 3)

    def test_history_keeps_kinds_and_only_caps_after_effect_saturation(self):
        enc = encoder()
        states = [enc.encode(observation(last_interaction_kind=0, interaction_streak=i)) for i in range(1, 7)]
        self.assertEqual(len(set(states[:5])), 5)
        self.assertEqual(states[4], states[5])
        self.assertNotEqual(states[0], enc.encode(observation(last_interaction_kind=1, interaction_streak=1)))
        late_switch = replace(Config.load(), switch_min_streak=9)
        self.assertEqual(StateEncoder.for_config(late_switch, (), ()).streak_cap, 9)
        disabled = replace(Config.load(), boredom_decay=0)
        self.assertEqual(StateEncoder.for_config(disabled, (), ()).streak_cap, 2)

    def test_clock_end_and_last_tick_are_distinct(self):
        enc = encoder()
        self.assertEqual([enc.encode(observation(remaining_ticks=t))[-1] for t in (0, 1, 2, 5, 6, 10, 11, 20, 21)],
                         [0, 1, 2, 2, 3, 3, 4, 4, 5])

    def test_observation_extras_do_not_leak_into_state(self):
        enc = encoder()
        self.assertEqual(enc.encode(observation()), enc.encode(observation(preferences=[0, 2], seed=999)))
        first = observation(last_interaction_kind=0, interaction_streak=2, previous_action=1)
        rest = {**first, "previous_action": 6}
        self.assertEqual(enc.encode(first), enc.encode(rest))

    def test_bad_observations_and_edges_rejected(self):
        enc = encoder()
        for obs in (observation(resources=[float("nan")] * 3), observation(resources=[-1, 1, 1]),
                    observation(resources=[0, 2, 1]), observation(remaining_ticks=41),
                    observation(last_interaction_kind=2, interaction_streak=1),
                    observation(last_interaction_kind=0, interaction_streak=0)):
            with self.assertRaises(ValueError):
                enc.encode(obs)
        with self.assertRaises(ValueError):
            StateEncoder((.5, .25), (1,), 2, 40)


class QLearningTests(unittest.TestCase):
    def setUp(self):
        self.agent = QLearningAgent(encoder(), learning_rate=.5, discount=.9, seed=42)
        self.state = (0, 5, 5, 0, 5)
        self.next = (1, 4, 5, 1, 5)
        self.mask = [1] * 7

    def test_q_update_uses_only_valid_future_actions(self):
        self.agent.table[self.state] = [2.0] * 7
        self.agent.table[self.next] = [1000, 10, 4, 2, 0, 0, 0]
        result = self.agent.update(self.state, 2, 1, self.next, terminated=False, truncated=False,
                                   next_mask=[0, 1, 1, 0, 0, 0, 0])
        self.assertAlmostEqual(result, 6)
        self.assertEqual(self.agent.values(self.state)[0], 2)
        self.assertEqual(self.agent.updates, 1)

    def test_terminal_update_ignores_future_values_and_empty_mask(self):
        self.agent.table[self.next] = [1000] * 7
        result = self.agent.update(self.state, 0, -10, self.next, terminated=True, truncated=False,
                                   next_mask=[0] * 7)
        self.assertEqual(result, -5)

    def test_truncation_bootstraps(self):
        self.agent.table[self.next] = [10] * 7
        result = self.agent.update(self.state, 0, 1, self.next, terminated=False, truncated=True,
                                   next_mask=self.mask)
        self.assertEqual(result, 5)
        with self.assertRaises(ValueError):
            self.agent.update(self.state, 0, 1, self.next, terminated=False, truncated=True,
                              next_mask=[0] * 7)
        self.assertEqual(self.agent.updates, 1)

    def test_greedy_and_exploration_never_select_masked_actions(self):
        self.agent.table[self.state] = [1000, 2, 3, 2000, 3000, 4000, 5000]
        mask = [0, 1, 1, 0, 0, 0, 0]
        self.assertEqual(self.agent.act(self.state, mask), 2)
        self.assertEqual({self.agent.act(self.state, mask, epsilon=1) for _ in range(100)}, {1, 2})
        with self.assertRaises(ValueError):
            self.agent.act(self.state, [0] * 7)

    def test_evaluation_does_not_change_table_or_rng_even_for_unseen_state(self):
        rng = self.agent.rng.getstate()
        self.assertEqual(self.agent.act(self.state, self.mask), 0)
        self.assertEqual(self.agent.table, {})
        self.assertEqual(rng, self.agent.rng.getstate())

    def test_seed_reproduces_exploration_and_random_ties(self):
        other = QLearningAgent(encoder(), learning_rate=.5, discount=.9, seed=42)
        self.assertEqual([self.agent.act(self.state, self.mask, epsilon=.5, random_ties=True) for _ in range(50)],
                         [other.act(self.state, self.mask, epsilon=.5, random_ties=True) for _ in range(50)])

    def test_reject_nonfinite_values_without_mutation(self):
        for reward in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                self.agent.update(self.state, 0, reward, self.next, terminated=True, truncated=False,
                                  next_mask=[0] * 7)
        self.assertEqual(self.agent.table, {})
        with self.assertRaises(ValueError):
            self.agent.values((999, 0, 0, 0, 0))


class TrainingSettingsTests(unittest.TestCase):
    def test_split_conditions_and_seed_overlap_rejected(self):
        settings = TrainingSettings.load()
        for overrides in ({"test_preferences": settings.train_preferences},
                          {"validation_seeds": (settings.scenario_seed,)},
                          {"test_seeds": settings.validation_seeds}, {"episodes": 0},
                          {"epsilon_end": 2}, {"learning_rate": 0}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                replace(settings, **overrides)

    def test_epsilon_schedule_and_settings_roundtrip(self):
        settings = TrainingSettings.load()
        self.assertEqual(TrainingSettings.from_dict(settings.to_dict()), settings)
        self.assertEqual(settings.epsilon(0), settings.epsilon_start)
        self.assertAlmostEqual(settings.epsilon(settings.episodes - 1), settings.epsilon_end)
        values = [settings.epsilon(i) for i in range(settings.episodes)]
        self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))
