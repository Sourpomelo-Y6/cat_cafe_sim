import copy
import io
from contextlib import redirect_stdout
import unittest
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay import AutoPlayer, main
from cat_cafe_sim.cafe_autoplay_staffing import plan, expansion_reason


class PolicyTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp
    session = fixtures.AutoPlayTests.session
    compare_reloads = fixtures.AutoPlayTests.compare_reloads

    def test_concentrated_work_uses_distinct_policy_limits(self):
        s = self.session(funds=1)
        s.core.config = replace(s.core.config, opening_ticks=40, arrival_ticks=(0, 20))
        s.interaction_config = replace(s.interaction_config, ticks=20)
        s.core.cats['a'].fatigue = 25
        s.core.cats['b'].fatigue = s.core.cats['c'].fatigue = 30
        s.core.day_results = [dict(day=1, cats={'a': dict(service_ticks=40)})]
        before = copy.deepcopy(s.core.snapshot())
        safe, fast = plan(s, 'clear'), plan(s, 'fast')
        self.assertEqual(safe['predictions']['a']['actions'], 40)
        self.assertNotIn('a', safe['workers'])
        self.assertIn('a', fast['workers'])
        self.assertEqual(s.core.snapshot(), before)

    def test_preference_concentration_is_readonly(self):
        s = self.session(funds=1)
        s.core.config = replace(s.core.config, opening_ticks=40, arrival_ticks=(0, 20))
        s.interaction_config = replace(s.interaction_config, ticks=20)
        s.core.cat_features = {'a': ['white']}
        s.core.customer_preferences = dict(rules=dict(pool=['white'], tension_multiplier=1), customers={})
        before = copy.deepcopy(s.core.snapshot())
        with patch('cat_cafe_sim.core.cafe_preferences.customer_preference', return_value='white'):
            safe, fast = plan(s, 'clear'), plan(s, 'fast')
        self.assertEqual(safe['predictions']['a']['actions'], 40)
        self.assertEqual(fast['predictions']['a']['actions'], 40)
        self.assertEqual(s.core.snapshot(), before)

    def test_fast_limits_avoid_exhausted_and_sick_cats(self):
        s = self.session(funds=1)
        s.core.cats['a'].fatigue = 56
        s.core.cats['b'].health_status = 'sick'
        s.core.cats['c'].stamina = 0
        self.assertEqual(plan(s, 'fast')['workers'], [])

    def test_fast_invests_for_rotation_and_waiting_visitors(self):
        s = self.session(funds=1)
        s.core.config = replace(s.core.config, opening_ticks=40, arrival_ticks=(0, 20, 39))
        s.interaction_config = replace(s.interaction_config, ticks=20)
        s.core.cats['a'].fatigue = 50
        staffing = plan(s, 'fast')
        self.assertTrue(expansion_reason(s.core, staffing))
        self.assertEqual(expansion_reason(s.core, staffing, mode='fast'), '')
        s.core.cats['a'].health_status = 'sick'
        self.assertTrue(expansion_reason(s.core, plan(s, 'fast'), mode='fast'))

    def test_fast_resume_and_decision_log_match_continuous_run(self):
        self.compare_reloads('fast')

    def test_normal_fast_reaches_three_stages_and_roundtrips(self):
        from cat_cafe_sim.cafe_new_game import create_game
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        s = create_game(Path(self.temp.name)/'normal-fast')
        player = AutoPlayer(s, mode='fast')
        result = player.run()
        self.assertEqual((result.reason, result.days), ('completed', 39))
        self.assertEqual([r['resolved_day'] for r in s.core.goal['history']], [11, 26])
        self.assertEqual(s.core.management['popularity'], 650)
        self.assertEqual(len(s.core.seats), 5)
        self.assertFalse(s.core.management['events'])
        save_game(s, s.checkpoint_path)
        self.assertEqual(load_game(s.checkpoint_path)[0].core.snapshot(), s.core.snapshot())

    def test_cli_fast_can_resume_existing_save(self):
        s = self.session()
        before = copy.deepcopy(s.core.goal['rules'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--resume', str(s.checkpoint_path), '--mode', 'fast', '--days', '1']), 0)
        from cat_cafe_sim.storage.cafe_saves import load_game
        loaded = load_game(s.checkpoint_path)[0]
        self.assertEqual(loaded.core.goal['rules'], before)
        self.assertIn('積極経営', s.checkpoint_path.with_name('autoplay.log').read_text())

    def test_policy_names_and_cancellation(self):
        for mode, name in (('basic', '基礎営業'), ('clear', '安定経営'), ('fast', '積極経営')):
            s = self.session(mode)
            lines = []
            player = AutoPlayer(s, mode=mode, emit=lines.append)
            self.assertIn(name, lines[0])
            before = copy.deepcopy(s.core.snapshot())
            player.cancel()
            self.assertFalse(player.step())
            self.assertEqual(s.core.snapshot(), before)
