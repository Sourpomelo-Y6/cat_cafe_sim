import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core import cafe_intake_request, cafe_regular_introduction, cafe_store_events
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class StoreAnswerOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def waiting_game(self, seed, day):
        session = create_game(self.root/'game', seed=seed)
        player = AutoPlayer(session, mode='clear')
        while session.core.day < day:
            self.assertTrue(player.step(), player.result)
        self.assertIsNotNone(cafe_store_events.waiting(session.core))
        save_game(session, self.root/'waiting.json')
        return session

    def check_modes(self, seed, day, pending, kind, choice):
        original = self.waiting_game(seed, day)
        self.assertTrue(pending(original.core))
        original_snapshot = original.core.snapshot()
        for mode in ('basic', 'clear', 'fast'):
            with self.subTest(mode=mode):
                direct, _ = load_game(self.root/'waiting.json')
                resumed, _ = load_game(self.root/'waiting.json')
                a, b = AutoPlayer(direct, mode=mode), AutoPlayer(resumed, mode=mode)
                for expected in ('resolve_store_event', kind):
                    self.assertTrue(a.step(), a.result)
                    self.assertTrue(b.step(), b.result)
                    self.assertEqual(direct.core.operations[-1]['operation']['kind'], expected)
                    self.assertEqual(direct.core.snapshot(), b.session.core.snapshot())
                    save_game(b.session, self.root/f'{mode}.json')
                    b.session = load_game(self.root/f'{mode}.json')[0]
                    self.assertEqual(direct.core.snapshot(), b.session.core.snapshot())
                    self.assertEqual(verify_cafe_interaction(b.session.core.log()).snapshot(), direct.core.snapshot())
                    if expected == 'resolve_store_event':
                        self.assertIsNone(cafe_store_events.waiting(direct.core))
                        self.assertTrue(pending(direct.core))
                        self.assertEqual(cafe_store_events.row(direct.core)['choice'], choice)
                self.assertFalse(pending(direct.core))
                self.assertEqual(direct.core.day, day)
                self.assertIsNone(a.result)
        self.assertEqual(original.core.snapshot(), original_snapshot)

    def test_support_before_intake_in_all_modes_and_save_replay(self):
        self.check_modes(1, 4, cafe_intake_request.pending, 'resolve_intake_request', 'decline')

    def test_trouble_before_regular_introduction_in_all_modes_and_save_replay(self):
        self.check_modes(5, 8, cafe_regular_introduction.pending, 'resolve_regular_introduction', 'repair')

    def test_unpersisted_and_player_interaction_keep_priority(self):
        session = self.waiting_game(1, 4)
        player = AutoPlayer(session, mode='clear')
        before = session.core.snapshot()
        with patch.object(type(session), 'pending', new=property(lambda _: True)):
            label, action = player._answer()
            self.assertEqual(action, session.persist)
        with patch('cat_cafe_sim.cafe_autoplay.cafe_player.active', return_value=True), \
             patch.object(session, 'player_command') as command:
            label, action = player._answer()
            action()
            command.assert_called_once_with(finish=True)
        self.assertEqual(session.core.snapshot(), before)

    def test_cancel_keeps_both_answers_pending(self):
        session = self.waiting_game(1, 4)
        before = session.core.snapshot()
        for mode in ('basic', 'clear', 'fast'):
            player = AutoPlayer(session, mode=mode)
            player.cancel()
            self.assertFalse(player.step())
            self.assertEqual(player.result.reason, 'cancelled')
            self.assertEqual(session.core.snapshot(), before)
            self.assertTrue(cafe_intake_request.pending(session.core))
            self.assertIsNotNone(cafe_store_events.waiting(session.core))
