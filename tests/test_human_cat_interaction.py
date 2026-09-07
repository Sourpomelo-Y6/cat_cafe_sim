import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cat_cafe_sim.core.human_cat_interaction import HumanCatInteraction, InteractionConfig, save, verify
from cat_cafe_sim.human_cat_demo import compare, choose


class HumanCatTests(unittest.TestCase):
    def test_hand_calculated_sequence(self):
        s = HumanCatInteraction()
        for action, gain, stamina in [('direct', 12, 95), ('direct', 10.2, 90), ('pause', 0, 92), ('feint', 12.6, 84)]:
            record = s.step(action)
            self.assertAlmostEqual(record['engagement_delta'], gain)
            self.assertEqual(s.state['stamina'], stamina)
        self.assertEqual(s.state['interaction_streak'], 3)

    def test_all_reactions_and_thresholds(self):
        for prefs, stamina, action, expected in [
            ((0, 1), 20, 'direct', 'turn_away'),
            ((1, 1), 20, 'intense', 'listless'),
            ((.4, 1), 100, 'direct', 'confused'),
            ((.5, 1), 100, 'direct', 'neutral'),
            ((1, 1), 100, 'adapt', 'favorable'),
            ((1.5, 1), 100, 'direct', 'enthusiastic'),
            ((1, 1), 100, 'pause', 'neutral')]:
            with self.subTest(expected=expected):
                s = HumanCatInteraction(InteractionConfig(preferences=prefs), stamina=stamina)
                r = s.step(action)
                self.assertEqual(r['reaction'], expected)
                if expected in ('listless', 'turn_away'):
                    self.assertEqual(r['engagement_delta'], 0)
                if expected == 'confused':
                    self.assertAlmostEqual(r['engagement_delta'], 2.4)

    def test_adapt_uses_previous_reaction(self):
        s = HumanCatInteraction(InteractionConfig(preferences=(.4, 1)))
        s.step('direct')
        r = s.step('adapt')
        self.assertEqual(r['diagnostic']['base_gain'], 8)
        self.assertEqual(r['stamina_spent'], 2)
        first = HumanCatInteraction(stamina=20).step('adapt')
        self.assertEqual(first['reaction'], 'listless')
        self.assertEqual(first['stamina_spent'], 5)

    def test_switch_preference_and_history(self):
        s = HumanCatInteraction(InteractionConfig(preferences=(0, 1)))
        self.assertEqual(s.step('direct')['reaction'], 'turn_away')
        s.step('switch')
        self.assertEqual(s.step('direct')['engagement_delta'], 12)
        s.step('switch')
        s.step('switch')
        self.assertAlmostEqual(s.step('direct')['engagement_delta'], 10.2)

    def test_combo_is_one_step_and_not_accumulated(self):
        for sequence, gain in [(['pause', 'feint'], 10),
                               (['direct', 'pause', 'feint'], 18),
                               (['direct', 'pause', 'pause', 'feint'], 10),
                               (['direct', 'pause', 'switch', 'switch', 'feint'], 10),
                               (['direct', 'pause', 'feint', 'feint'], 10)]:
            s = HumanCatInteraction()
            for a in sequence:
                r = s.step(a)
            self.assertEqual(r['diagnostic']['base_gain'], gain)

    def test_pause_recovery_and_no_progress_loops(self):
        for action in ('pause', 'switch'):
            s = HumanCatInteraction(stamina=20)
            while not s.state['end_reason']:
                s.step(action)
            self.assertEqual(s.state['engagement'], 0)
            self.assertEqual(s.state['end_reason'], 'timeout')
            self.assertEqual(s.state['stamina'], 60 if action == 'pause' else 20)
        s = HumanCatInteraction(stamina=99)
        self.assertEqual(s.step('pause')['stamina_recovered'], 1)
        s = HumanCatInteraction(stamina=20)
        self.assertEqual(s.step('pause')['reaction'], 'listless')
        self.assertEqual(s.step('direct')['reaction'], 'favorable')

    def test_boredom_floor_and_pause_keeps_history(self):
        s = HumanCatInteraction(InteractionConfig(target=1000))
        for _ in range(6):
            s.step('direct')
        s.step('pause')
        self.assertEqual(s.step('direct')['diagnostic']['boredom_multiplier'], .4)

    def test_invalid_actions_atomic_and_end_rejected(self):
        s = HumanCatInteraction()
        s.step('switch')
        for a in ('intense', 'feint', 'connect', None, [], 1):
            before = s.log()
            with self.assertRaises(ValueError):
                s.step(a)
            self.assertEqual(s.log(), before)
        s = HumanCatInteraction(InteractionConfig(ticks=1))
        s.step('pause')
        before = s.log()
        self.assertEqual(s.valid_actions(), ())
        with self.assertRaises(ValueError):
            s.step('direct')
        self.assertEqual(s.log(), before)

    def test_end_priority_and_actual_deltas(self):
        for cost, expected in ((100, 'exhausted'), (5, 'success')):
            s = HumanCatInteraction(InteractionConfig(ticks=1, target=10, direct_cost=cost))
            r = s.step('direct')
            self.assertEqual(s.state['end_reason'], expected)
            self.assertEqual(r['engagement_delta'], 10)
            self.assertEqual(r['reaction'], 'favorable')
        s = HumanCatInteraction(InteractionConfig(direct_cost=200))
        self.assertEqual(s.step('direct')['stamina_spent'], 100)

    def test_config_validation_and_start_validation(self):
        self.assertEqual(InteractionConfig.load(), InteractionConfig())
        for kwargs in ({'ticks': True}, {'ticks': 0}, {'target': 0}, {'preferences': (1, 3)},
                       {'preferences': (True, 1)}, {'direct_gain': float('nan')},
                       {'pause_recovery': -1}, {'boredom_floor': 2},
                       {'low_stamina': 101}, {'confused_threshold': 11},
                       {'intense_gain': 1.7e308}):
            with self.assertRaises(ValueError):
                InteractionConfig(**kwargs)
        for stamina in (0, -1, 101, True, float('nan')):
            with self.assertRaises(ValueError):
                HumanCatInteraction(stamina=stamina)

    def test_observation_separation_and_copy(self):
        s = HumanCatInteraction()
        obs = s.observation()
        self.assertNotIn('preferences', obs)
        self.assertNotIn('score', obs)
        self.assertIsNone(obs['previous_reaction'])
        obs['stamina'] = 0
        r = s.step('direct')
        r['after']['stamina'] = 0
        self.assertEqual(s.state['stamina'], 95)
        self.assertEqual(s.records[0]['after']['stamina'], 95)
        self.assertEqual(choose('responsive', HumanCatInteraction(stamina=20).observation(), 0), 'pause')

    def test_replay_partial_complete_and_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'log.json'
            s = HumanCatInteraction(InteractionConfig(ticks=2))
            for a in ('direct', 'pause'):
                s.step(a)
                save(s, p)
                self.assertEqual(verify(p).log(), s.log())
            for field in ('reaction', 'summary', 'version', 'mode'):
                data = copy.deepcopy(s.log())
                if field == 'reaction':
                    data['records'][0]['reaction'] = 'neutral'
                elif field == 'summary':
                    data['summary']['engagement'] += 1
                elif field == 'version':
                    data['rule_version'] = 2
                else:
                    data['mode_id'] = 'cat-interaction'
                p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    verify(p)

    def test_cli_without_site_packages(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / 'session.json')
            base = [sys.executable, '-S', '-m', 'cat_cafe_sim.human_cat_demo']
            result = subprocess.run(base + ['run', '--actions', 'direct', 'pause', 'feint', '--output', path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(base + ['replay', path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(base + ['run', '--actions', 'switch', 'intense', '--output', path], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_comparison_cases_and_replays(self):
        with tempfile.TemporaryDirectory() as d:
            rows = compare(InteractionConfig(), Path(d) / 'compare.json')
            self.assertEqual(len(rows), 48)
            self.assertEqual(len({(r['policy'], tuple(r['preferences']), r['initial_stamina']) for r in rows}), 48)
            for r in rows:
                s = verify(r['log'])
                self.assertEqual(r['end_reason'], s.state['end_reason'])
                if r['policy'] == 'pause':
                    self.assertEqual(r['engagement'], 0)
