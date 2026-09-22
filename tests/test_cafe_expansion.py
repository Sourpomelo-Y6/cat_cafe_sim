import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_expansion import rules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relations.json')
        add_playtest_cats(self.store)
        self.path = Path(self.temp.name)/'cafe.json'

    def session(self, seats=2, funds=1000):
        return CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=6, arrival_ticks=(0,0,0), initial_funds=funds),
            interaction_config=replace(RelationshipConfig(), ticks=4))

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def rejected(self, s, action):
        before = s.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(before, s.core.log())

    def test_purchase_three_simultaneous_seats_save_replay_and_next_day(self):
        s = self.session()
        s.expand_seats()
        self.assertEqual(s.core.funds, 500)
        self.assertEqual(s.core.summary()['seat_count'], 3)
        self.assertEqual(s.core.summary()['expansion_expenses'], 500)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s = self.reload(s)
        s.step()
        for i, cat in enumerate(list(s.core.cats)[:3], 1):
            s.start(f'guest-{i}', cat, f'seat-{i}')
        self.assertEqual(len(s.active_interactions), 3)
        s = self.reload(s)
        self.rejected(s, lambda: s.start('guest-3', list(s.core.cats)[-1], 'seat-3'))
        s.automatic_step()
        s = self.reload(s)
        while not s.core.closed:
            s.automatic_step()
        self.assertEqual(s.core.summary()['completed_interactions'], 3)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s.next_day()
        self.assertEqual(s.core.day_results[0]['summary']['expansion_expenses'], 500)
        self.assertEqual(s.core.summary()['expansion_expenses'], 0)
        self.assertEqual(len(s.free_seats), 3)
        self.reload(s)

    def test_auto_assignment_uses_third_seat_and_dispatch_retains_three_cats(self):
        s = self.session()
        s.expand_seats()
        keys = list(s.core.cats)
        s.dispatch(keys[0])
        s.dispatch(keys[1])
        self.rejected(s, lambda: s.dispatch(keys[2]))
        s.automatic_step()
        s.automatic_step()
        self.assertEqual(len(s.active_interactions), 3)
        self.assertEqual(set(s.active_interactions), {'seat-1','seat-2','seat-3'})
        self.reload(s)

    def test_funds_boundary_repeat_and_old_single_seat(self):
        for funds in (0,499,500,501):
            s = self.session(funds=funds)
            if funds <= 500:
                self.rejected(s, s.expand_seats)
            else:
                s.expand_seats()
                self.assertEqual(s.core.funds, 1)
                self.rejected(s, s.expand_seats)
                self.reload(s)
        s = self.reload(self.session(seats=1))
        self.rejected(s, s.expand_seats)
        self.assertIsNone(s.core.expansion)
        s = self.reload(self.session())
        self.assertNotIn('expansion', checkpoint(s.core, set())['state'])
        s.expand_seats()
        self.reload(s)

    def test_preparation_only_and_waiting_events_and_player(self):
        s = self.session()
        s.play_with_player(next(iter(s.core.cats)))
        self.rejected(s, s.expand_seats)
        s.player_command(finish=True)
        key = next(iter(s.core.cats))
        s.dispatch(key)
        s.day_off()
        self.rejected(s, s.expand_seats)
        s.resolve_activity(f'dispatch-1-{key}')
        s.expand_seats()
        self.reload(s)
        another = self.session()
        another.automatic_step()
        self.rejected(another, another.expand_seats)
        while not another.core.closed:
            another.automatic_step()
        self.rejected(another, another.expand_seats)

    def test_day_off_history_and_failed_save_no_double_payment(self):
        s = self.session()
        s.day_off()
        s.expand_seats()
        self.assertEqual(s.core.day_results[0]['summary']['seat_count'], 2)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s, self.path)
        self.assertEqual(s.core.funds, 500)
        s = self.reload(s)
        s.day_off()
        self.assertEqual(s.core.day_results[1]['summary']['seat_count'], 3)
        self.assertEqual(s.core.day_results[1]['summary']['expansion_expenses'], 500)
        self.reload(s)

    def test_invalid_cost_seat_count_and_accounting_rejected(self):
        for cost in (0, -1, True, float('inf')):
            with self.assertRaises(ValueError):
                rules(dict(cost=cost))
        s = self.session()
        s.expand_seats()
        source = checkpoint(s.core, set())
        for mutate in (
            lambda d: d['state'].pop('expansion'),
            lambda d: d['state']['expansion'].update(cost=400),
            lambda d: d['state']['expansion'].update(day=2),
            lambda d: d.update(seat_count=2),
            lambda d: d['state']['seats'].pop('seat-3'),
        ):
            bad = copy.deepcopy(source)
            mutate(bad)
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
