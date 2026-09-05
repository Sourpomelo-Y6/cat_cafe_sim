from dataclasses import replace
import unittest

from cat_cafe_sim.core import Command, SimulationCore
from cat_cafe_sim.core.config import Config


def run_actions(actions, **kwargs):
    core = SimulationCore(replace(Config.load(), arrival_ticks=(0,), satisfaction_target=10000,
                                  max_stamina=10000, **kwargs))
    for index, action in enumerate(actions):
        command = Command("assign", "guest-1") if index == 0 else Command()
        core.step(command, cat_action=action)
    return core, [e for e in core.events if e["kind"] == "action"]


class InteractionTests(unittest.TestCase):
    def test_speed_changes_do_not_reset_boredom(self):
        core, events = run_actions([0, 1, 2, 0, 1, 2])
        self.assertEqual([e["interaction_streak"] for e in events], [1, 2, 3, 4, 5, 6])
        for event, expected in zip(events, [1, .85, .7, .55, .4, .4]):
            self.assertAlmostEqual(event["boredom_multiplier"], expected)
        self.assertEqual(core.visits["guest-1"].last_interaction_kind, "play")

    def test_rest_preserves_history_and_does_not_earn_bonus(self):
        core, events = run_actions([1, 1, 6, 1, 6, 4])
        self.assertEqual([e["interaction_streak"] for e in events], [1, 2, 2, 3, 3, 1])
        self.assertEqual([e["switch_bonus"] for e in events], [0, 0, 0, 0, 0, 4])
        self.assertEqual(core.visits["guest-1"].previous_action, 4)

    def test_alternating_every_tick_never_earns_switch_bonus(self):
        _, events = run_actions([1, 4] * 8)
        self.assertTrue(all(e["switch_bonus"] == 0 for e in events))
        self.assertTrue(all(e["interaction_streak"] == 1 for e in events))

    def test_qualified_switch_bonus_only_on_switch(self):
        _, events = run_actions([1, 1, 4, 4, 1])
        self.assertEqual([e["switch_bonus"] for e in events], [0, 0, 4, 0, 4])
        self.assertEqual([e["interaction_streak"] for e in events], [1, 2, 1, 2, 1])
        self.assertAlmostEqual(events[2]["satisfaction_delta"], 20)

    def test_zero_preference_does_not_receive_bonus(self):
        _, events = run_actions([1, 1, 4], preferences=(1, 0))
        self.assertEqual(events[-1]["satisfaction_delta"], 0)
        self.assertEqual(events[-1]["switch_bonus"], 0)

    def test_history_resets_for_next_customer(self):
        core = SimulationCore(replace(Config.load(), arrival_ticks=(0, 1), satisfaction_target=12))
        core.step(Command("assign", "guest-1"), cat_action=0)
        core.step(Command("assign", "guest-2"), cat_action=0)
        events = [e for e in core.events if e["kind"] == "action"]
        self.assertEqual([e["boredom_multiplier"] for e in events], [1, 1])
        self.assertEqual([e["interaction_streak"] for e in events], [1, 1])

    def test_disable_effects_restores_original_amounts(self):
        _, events = run_actions([1, 1, 4, 4, 1], boredom_decay=0, switch_bonus=0)
        self.assertEqual([e["satisfaction_delta"] for e in events], [20, 20, 16, 16, 20])

    def test_config_validation_and_round_trip(self):
        config = Config.load()
        self.assertEqual(Config.from_dict(config.to_dict()), config)
        for kwargs in ({"boredom_decay": -1}, {"boredom_decay": float("nan")},
                       {"boredom_decay": 2}, {"boredom_min_multiplier": 2},
                       {"switch_bonus": -1}, {"switch_min_streak": 0},
                       {"boredom_free_actions": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(config, **kwargs).validate()
