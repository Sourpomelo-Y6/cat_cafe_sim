import io
import signal
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import test_cafe_autoplay as fixtures
from cat_cafe_sim.cafe_autoplay import AutoPlayer, main
from cat_cafe_sim.cafe_autoplay_strategy import prepare, reserve
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ClearAutoPlayTests(unittest.TestCase):
    setUp = fixtures.AutoPlayTests.setUp
    session = fixtures.AutoPlayTests.session
    compare_reloads = fixtures.AutoPlayTests.compare_reloads

    def test_normal_rules_clear_and_basic_baseline(self):
        for mode, expected in (('basic', 'expired'), ('clear', 'completed')):
            s = create_game(Path(self.temp.name)/mode)
            player = AutoPlayer(s, mode=mode)
            while player.step():
                operation = s.core.operations[-1]['operation']['kind']
                if operation in ('purchase_rest_space', 'upgrade_rest_space', 'soundproof_rest_space',
                                 'expand_seats', 'purchase_seat_equipment'):
                    self.assertGreaterEqual(s.core.funds, reserve(s.core))
            self.assertEqual(player.result.reason, expected)
            self.assertEqual(player.result.days, 16)
            self.assertGreater(s.core.funds, 0)
            if mode=='clear':
                self.assertEqual([row['resolved_day'] for row in s.core.goal['history']], [4, 9])
                self.assertEqual(s.core.management['popularity'], 300)
                self.assertLessEqual(len(s.core.seats), 8)
                self.assertIn('upgrade', s.core.rest_space)
                self.assertIn('soundproof', s.core.rest_space)
                self.assertEqual(s.core.reservation['request']['status'], 'accepted')
            else:
                self.assertIsNone(s.core.rest_space)
                self.assertEqual(len(s.core.seats), 2)
                self.assertEqual(s.core.management['popularity'], 195)
            save_game(s, s.checkpoint_path)
            self.assertEqual(load_game(s.checkpoint_path)[0].core.snapshot(), s.core.snapshot())

    def test_clear_reload_matches_decisions_and_purchases(self):
        self.compare_reloads('clear')

    def test_no_purchase_below_reserve_and_cancel_before_purchase(self):
        s = self.session(funds=599)
        before = s.core.snapshot()
        label, action = prepare(s, None, lambda key: key)
        self.assertIn('営業開始', label)
        self.assertEqual(s.core.snapshot(), before)
        player = AutoPlayer(s, mode='clear')
        player.cancel()
        self.assertFalse(player.step())
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(player.result.reason, 'cancelled')

    def test_first_day_and_rest_day_do_not_predict_zero_service(self):
        s = self.session(funds=1)
        lines = []
        prepare(s, lines.append, lambda key: key)
        self.assertTrue(any('疲労 20' in line for line in lines))
        self.assertFalse(any('疲労 0 /' in line for line in lines))

    def test_cli_clear_resume_explicit_and_signal_boundary(self):
        s = self.session()
        original = signal.getsignal(signal.SIGINT)

        def interrupt(*args, **kwargs):
            path = save_game(*args, **kwargs)
            signal.raise_signal(signal.SIGINT)
            return path

        with redirect_stdout(io.StringIO()), patch('cat_cafe_sim.storage.cafe_saves.save_game', side_effect=interrupt):
            self.assertEqual(main(['--resume', str(s.checkpoint_path), '--mode', 'clear']), 0)
        self.assertEqual(signal.getsignal(signal.SIGINT), original)
        loaded = load_game(s.checkpoint_path)[0]
        self.assertIsNotNone(loaded.core.rest_space)
        self.assertEqual(loaded.core.tick, 0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--resume', str(s.checkpoint_path), '--mode', 'clear']), 0)
        self.assertEqual(load_game(s.checkpoint_path)[0].core.goal['status'], 'cleared')
        text = s.checkpoint_path.with_name('autoplay.log').read_text(encoding='utf-8')
        self.assertIn('クリアを目指す', text)
        self.assertIn('予備資金', text)

    def test_clear_tiny_game_replay_and_invalid_mode(self):
        s = self.session()
        self.assertEqual(AutoPlayer(s, mode='clear').run().reason, 'completed')
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        with self.assertRaises(ValueError):
            AutoPlayer(s, mode='unknown')

    def test_deadline_skips_long_term_investment(self):
        s = self.session(days=1, funds=1000)
        label, action = prepare(s, None, lambda key: key)
        self.assertIn('おもちゃセット', label)
        action()
        self.assertIsNone(s.core.rest_space)

    def test_reservation_visit_must_fit_current_stage_deadline(self):
        for days, expected in ((1, 'declined'), (3, 'accepted')):
            s = self.session(str(days), days=days)
            s.core.initialize_preferences({key: ['long_hair'] for key in s.core.cats})
            s.core.initialize_reservation()
            self.assertEqual(AutoPlayer(s, max_days=2).run().reason, 'day_limit')
            s.advance_goal()
            s.next_day()
            player = AutoPlayer(s, mode='clear')
            self.assertTrue(player.step())
            self.assertEqual(s.core.reservation['request']['status'], expected)
