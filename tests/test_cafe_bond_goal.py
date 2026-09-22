import copy
from unittest.mock import patch

import test_cafe_patron as patron_tests
from cat_cafe_sim.core.cafe_bond_goal import rules, pending, qualifying, evaluate
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_player import legacy_play, state
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.core.cafe_activities import ensure


# Reuse fixture helpers without inheriting another feature's tests.
import unittest
class BondGoalTests(unittest.TestCase):
    setUp = patron_tests.PatronTests.setUp
    session = patron_tests.PatronTests.session
    reload = patron_tests.PatronTests.reload

    def test_six_cats_boundary_save_replay_and_continue(self):
        self.store.register_cat('sixth', '六匹目', Personality())
        s = self.session()
        s.enable_management()
        s.enable_bond_goal()
        keys = list(s.core.cats)
        self.assertEqual(len(keys), 6)
        for index, key in enumerate(keys):
            for turn in range(16):
                if sum(state(s.core)['today'].values()) == 3:
                    s.day_off()
                legacy_play(s.core, key)
                if turn == 14:
                    self.assertNotIn(key, qualifying(s.core))
                    self.assertFalse(pending(s.core))
            self.assertEqual(len(qualifying(s.core)), index + 1)
            self.assertEqual(pending(s.core), index == 5)
        s = self.reload(s)
        achieved_day = s.core.bond_goal['resolved_day']
        for action in (s.day_off, s.automatic_step, lambda: s.play_with_player(keys[0]), s.enable_bond_goal):
            before = s.core.snapshot()
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s.continue_bond_goal()
        with self.assertRaises(ValueError):
            s.continue_bond_goal()
        s.day_off()
        self.assertEqual(s.core.bond_goal['resolved_day'], achieved_day)
        self.assertFalse(pending(s.core))
        self.reload(s)

    def test_real_exchange_only_counts_after_completion_and_frozen_rules(self):
        s = self.session()
        s.enable_management()
        s.enable_bond_goal(dict(target=1, affinity=.5))
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        s.player_command('direct')
        self.assertFalse(pending(s.core))
        s = self.reload(s)
        s.player_command(finish=True)
        self.assertTrue(pending(s.core))
        self.assertEqual(s.core.bond_goal['achieved_cats'], [key])
        def frozen(data=None):
            self.assertIsNotNone(data)
            return rules(data)
        with patch('cat_cafe_sim.core.cafe_bond_goal.rules', side_effect=frozen):
            s = self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_old_save_optional_and_start_with_existing_affinity(self):
        s = self.reload(self.session())
        self.assertNotIn('bond_goal', checkpoint(s.core, set())['state'])
        self.assertIsNone(s.core.bond_goal)
        with self.assertRaises(ValueError):
            s.enable_bond_goal()
        s.enable_management()
        key = next(iter(s.core.cats))
        legacy_play(s.core, key)
        s.enable_bond_goal(dict(target=1, affinity=5))
        self.assertTrue(pending(s.core))
        self.reload(s)

    def test_membership_and_game_over_priority_and_latched_achievement(self):
        s = self.session()
        s.enable_management()
        s.enable_bond_goal()
        core = s.core
        # Isolated evaluator fixture: boundary and membership combinations.
        core.player_bond = state(core)
        keys = list(core.cats)
        core.player_bond['affinity'].update(dict(zip(keys, (80, 80, 80, 100, 79.9))))
        ensure(core)
        core.activities['cats'].update(dict(zip(keys, ('cafe','dispatched','missing','adopted','cafe'))))
        self.assertEqual(qualifying(core), sorted(keys[:3]))
        core.bond_goal['rules']['target'] = 3
        core.management['game_over'] = dict(reason='funds', day=core.day)
        evaluate(core)
        self.assertEqual(core.bond_goal['status'], 'active')
        self.assertFalse(pending(core))
        core.management['game_over'] = None
        evaluate(core)
        self.assertTrue(pending(core))
        achieved = copy.deepcopy(core.bond_goal)
        core.activities['cats'][keys[0]] = 'adopted'
        core.player_bond['affinity'][keys[1]] = 0
        evaluate(core)
        self.assertEqual(core.bond_goal, achieved)
        self.assertEqual(len(qualifying(core)), 1)

    def test_invalid_rules_and_checkpoint(self):
        for change in (dict(target=0),dict(target=True),dict(affinity=0),dict(affinity=101),dict(affinity=float('nan'))):
            with self.assertRaises(ValueError):
                rules(dict(rules(), **change))
        s = self.session()
        s.enable_management()
        s.enable_bond_goal()
        source = checkpoint(s.core, set())
        for change in (dict(status='cleared'), dict(continued=True),dict(started_day=0),
                       dict(resolved_day=1),dict(achieved_cats=['absent'])):
            bad = copy.deepcopy(source)
            bad['state']['bond_goal'].update(change)
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)

    def test_goals_remain_independent_and_pending_blocks_direct_core_play(self):
        from cat_cafe_sim.core.cafe_patron import pending as patron_pending
        from cat_cafe_sim.core.cafe_goal import pending as popularity_pending
        s = self.session()
        s.enable_management()
        s.enable_goal(dict(days=1, target=150, cap=300, gain_per_success=5))
        s.enable_patron()
        s.enable_bond_goal(dict(target=1, affinity=5))
        key = next(iter(s.core.cats))
        legacy_play(s.core, key)
        self.assertTrue(pending(s.core))
        self.assertFalse(patron_pending(s.core))
        self.assertFalse(popularity_pending(s.core))
        with self.assertRaises(ValueError):
            legacy_play(s.core, key)
        s.continue_bond_goal()
        s.day_off()
        self.assertTrue(popularity_pending(s.core))
        s = self.reload(s)
        s.continue_goal()
        s.day_off()
        self.assertEqual(s.core.patron['status'], 'active')
        self.assertTrue(s.core.bond_goal['continued'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
