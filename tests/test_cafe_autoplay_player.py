import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import starting_conditions
from cat_cafe_sim.cafe_autoplay_player import player_action, _initial_plan, _short_action
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.core.human_cat_types import Personality


class PlayerPlanningTests(unittest.TestCase):
    def interaction(self, key='cat-sora', *, stamina=100, personality=None, **metadata):
        profile = starting_conditions('bond')['profiles']['cats'][key]
        config = replace(RelationshipConfig.load(), ticks=10,
                         personality=Personality.from_dict(personality or profile['personality']))
        return RelationshipInteraction(config, stamina=stamina, **metadata)

    def finish(self, interaction, choose=player_action):
        while not interaction.state['end_reason']:
            before = copy.deepcopy(interaction.log())
            action, target = choose(interaction)
            self.assertEqual(interaction.log(), before)
            self.assertIn(action, interaction.valid_actions())
            interaction.step(action, target)
        return interaction.result()

    def test_sora_reaches_simultaneous_activation_within_ten_turns(self):
        interaction = self.interaction()
        result = self.finish(interaction)
        self.assertGreaterEqual(result['affinity_delta'], 7.5)
        self.assertGreaterEqual(result['simultaneous_count'], 1)
        self.assertEqual(result['ticks'], 10)
        self.assertGreater(result['stamina'], 0)
        self.assertGreater(result['type_actions']['tunnel'], 0)

    def test_all_initial_personalities_do_not_lose_existing_set_gain(self):
        for key in starting_conditions('bond')['profiles']['cats']:
            old, new = self.interaction(key), self.interaction(key)
            baseline = self.finish(old, _short_action)
            actual = self.finish(new)
            self.assertGreaterEqual(actual['affinity_pending'], baseline['affinity_pending'], key)
            if actual['affinity_pending']==baseline['affinity_pending']:
                self.assertGreaterEqual(actual['stamina'], baseline['stamina'], key)

    def test_quiet_preferences_can_select_voice_or_presence_without_cat_id_rules(self):
        personality = copy.deepcopy(starting_conditions('bond')['profiles']['cats']['cat-sora']['personality'])
        personality['type_preferences'] = dict.fromkeys(personality['type_preferences'], 0)
        personality['type_preferences'].update(voice=2, presence=2)
        personality['intensity_preferences']['standard'] = 1.2
        interaction = self.interaction(personality=personality, cat_id='unseen-cat')
        result = self.finish(interaction)
        self.assertGreater(result['type_actions']['voice']+result['type_actions']['presence'], 0)
        self.assertGreater(result['affinity_delta'], 2)

    def test_cold_cache_resume_chooses_identical_remaining_actions(self):
        direct = self.interaction(cat_id='resume-cat')
        for _ in range(4):
            direct.step(*player_action(direct))
        resumed = verify_relationship(direct.log())
        _initial_plan.cache_clear()
        while not direct.state['end_reason']:
            self.assertEqual(player_action(direct), player_action(resumed))
            action, target = player_action(direct)
            direct.step(action, target)
            resumed.step(action, target)
        self.assertEqual(direct.log(), resumed.log())

    def test_manual_deviation_replans_from_current_state_and_keeps_log_unchanged(self):
        interaction = self.interaction()
        interaction.step('switch', 'presence')
        before = copy.deepcopy(interaction.log())
        action, target = player_action(interaction)
        self.assertEqual(interaction.log(), before)
        self.assertIn(action, interaction.valid_actions())
        interaction.step(action, target)
        result = self.finish(interaction)
        self.assertGreater(result['stamina'], 0)

    def test_low_stamina_rest_and_forced_connect_remain_valid(self):
        interaction = self.interaction(stamina=1)
        self.assertEqual(player_action(interaction), ('pause', None))
        result = self.finish(interaction)
        self.assertNotEqual(result['end_reason'], 'exhausted')
        forced = self.interaction(stamina=1, tension=100, engagement=100)
        self.assertEqual(player_action(forced), ('connect', None))
        self.assertGreaterEqual(self.finish(forced)['simultaneous_count'], 1)

    def test_planning_does_not_generate_random_session_ids(self):
        interaction = self.interaction()
        _initial_plan.cache_clear()
        with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=AssertionError('random ID')):
            self.assertIn(player_action(interaction)[0], interaction.valid_actions())

    def test_no_action_selected_after_completion(self):
        interaction = self.interaction()
        self.finish(interaction)
        with self.assertRaises(ValueError):
            player_action(interaction)
