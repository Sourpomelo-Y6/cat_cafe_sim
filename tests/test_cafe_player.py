import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, verify_relationship
from cat_cafe_sim.core.cafe_player import state, remaining, current, legacy_play
from cat_cafe_sim.core.cafe_activities import waiting_events
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relations.json')
        add_playtest_cats(self.store)
        self.path = Path(self.temp.name)/'cafe.json'

    def session(self, seats=2):
        return CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=4, arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(), ticks=2))

    def reload(self, session):
        save_game(session, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(session.core.snapshot(), loaded.core.snapshot())
        return loaded

    def close(self, session):
        while not session.core.closed:
            session.automatic_step()

    def rejected(self, session, action):
        before = session.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(before, session.core.log())

    def test_three_sets_ten_commands_shared_with_customer_rules_and_resume(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.session(seats)
                keys = list(s.core.cats)
                s.set_shifts([])
                original = self.store.path.read_bytes()
                s.play_with_player(keys[0])
                self.assertEqual(remaining(s.core), 2)
                self.assertEqual(current(s.core).config.ticks, 10)
                reference = verify_relationship(current(s.core).log())
                for action, target in [('switch','voice'),('direct',None),('adapt',None)]:
                    reference.step(action, target)
                    s.player_command(action, target)
                s = self.reload(s)
                self.assertEqual(current(s.core).log(), reference.log())
                while not reference.state['end_reason']:
                    reference.step('direct')
                    s.player_command('direct')
                result = reference.result()
                self.assertIsNone(current(s.core))
                self.assertEqual(s.core.player_bond['last'], reference.log())
                self.assertEqual(state(s.core)['affinity'][keys[0]], result['affinity_after'])
                self.assertEqual(s.core.cats[keys[0]].stamina, result['stamina'])
                self.assertEqual(s.core.tick, 0)
                self.assertEqual(s.core.funds, 0)
                self.assertEqual(self.store.path.read_bytes(), original)
                s = self.reload(s)
                for key in keys[1:3]:
                    s.play_with_player(key)
                    s.player_command('direct')
                    s.player_command(finish=True)
                self.assertEqual(remaining(s.core), 0)
                self.rejected(s, lambda:s.play_with_player(keys[3]))
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                self.reload(s)

    def test_active_blocks_other_progress_and_invalid_commands_are_atomic(self):
        s = self.session()
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        for action in (lambda:s.play_with_player(key), lambda:s.dispatch(key), lambda:s.day_off(),
                       lambda:s.set_shifts([]), lambda:s.automatic_step(), lambda:s.core.step({}),
                       lambda:s.core.dispatch(key), lambda:s.player_command('switch','unknown'),
                       lambda:s.player_command('invalid'), lambda:s.next_day()):
            self.rejected(s, action)
        before = s.core.log()
        cat_details(s, key)
        self.assertEqual(before, s.core.log())
        s.player_command(finish=True)
        after = s.core.log()
        s.player_command(finish=True)
        self.assertEqual(after, s.core.log())
        self.assertEqual(remaining(s.core), 2)
        self.assertEqual(state(s.core)['affinity'][key], 0)

    def test_normal_close_and_day_off_replenish_only_on_new_day(self):
        s = self.session()
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        s.player_command('direct')
        s.player_command(finish=True)
        s.set_shifts([])
        s.automatic_step()
        self.rejected(s, lambda:s.play_with_player(key))
        self.close(s)
        self.rejected(s, lambda:s.play_with_player(key))
        s.next_day()
        self.assertEqual(remaining(s.core), 3)
        s.play_with_player(key)
        s.player_command(finish=True)
        s.day_off()
        self.assertEqual(s.core.day, 3)
        self.assertEqual(remaining(s.core), 3)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_dispatch_waiting_return_and_unavailable_cats(self):
        s = self.session()
        a, b = list(s.core.cats)[:2]
        self.rejected(s, lambda:s.play_with_player('unknown'))
        s.dispatch(a)
        self.rejected(s, lambda:s.play_with_player(a))
        s.day_off()
        self.rejected(s, lambda:s.play_with_player(b))
        s.resolve_activity(waiting_events(s.core)[0]['id'])
        s.play_with_player(a)
        s.player_command(finish=True)
        for status in ('missing', 'adopted'):
            s.core.activities['cats'][b] = status
            self.rejected(s, lambda:s.play_with_player(b))
        s.core.activities['cats'][b] = 'cafe'
        s.core.cats[b].health_status = 'sick'
        self.rejected(s, lambda:s.play_with_player(b))
        s.core.cats[b].health_status = 'healthy'
        s.core.cats[b].stamina = 0
        self.rejected(s, lambda:s.play_with_player(b))

    def test_affinity_cap_still_allows_testing_and_exhaustion_ends_set(self):
        s = self.session()
        s.interaction_config = replace(s.interaction_config, affinity_favorable=100, affinity_enthusiastic=100)
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        s.player_command('direct')
        s.player_command(finish=True)
        self.assertEqual(state(s.core)['affinity'][key], 100)
        s.play_with_player(key)
        while current(s.core):
            s.player_command('intense')
        self.assertEqual(s.core.cats[key].stamina, 0)
        self.assertTrue(s.core.cats[key].cannot_continue)
        self.assertEqual(s.core.player_bond['last']['summary']['end_reason'], 'exhausted')
        self.rejected(s, lambda:s.play_with_player(key))
        self.reload(s)

    def test_special_actions_and_personality_match_without_cafe_income(self):
        from cat_cafe_sim.core.human_cat_types import Personality
        s = self.session()
        s.interaction_config = replace(s.interaction_config, direct_gain=100,
                                       tension_enthusiastic=100, tension_favorable=100)
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        self.assertEqual(current(s.core).config.personality,
                         Personality.from_dict(s.profiles[key]['personality']))
        s.player_command('direct')
        self.assertEqual(current(s.core).valid_actions(), ('connect',))
        self.rejected(s, lambda:s.player_command('direct'))
        s = self.reload(s)
        s.player_command('connect')
        self.assertEqual(current(s.core).state['simultaneous_count'], 1)
        s.player_command(finish=True)
        self.assertGreater(s.core.player_bond['last']['summary']['bonus_funds'], 0)
        self.assertEqual(s.core.funds, 0)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_save_failure_keeps_active_turn_and_retry_does_not_replay(self):
        s = self.session()
        key = next(iter(s.core.cats))
        s.play_with_player(key)
        s.player_command('direct')
        before = s.core.log()
        with patch.object(RelationshipStore, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_game(s, self.path)
        self.assertEqual(before, s.core.log())
        s = self.reload(s)
        self.assertEqual(len(current(s.core).records), 1)
        self.assertEqual(remaining(s.core), 2)

    def test_pending_results_and_changed_relationship_file_block_commands(self):
        s = self.session()
        key = next(iter(s.core.cats))
        with patch.object(type(s), 'pending', new_callable=lambda: property(lambda _: {'pending'})):
            self.rejected(s, lambda:s.play_with_player(key))
        s.play_with_player(key)
        with patch('cat_cafe_sim.storage.cafe_saves.check_link', side_effect=ValueError('changed')):
            self.rejected(s, lambda:s.player_command('direct'))

    def test_legacy_save_and_active_checkpoint_validation(self):
        s = self.session()
        old = checkpoint(s.core, set())
        self.assertNotIn('player_bond', old['state'])
        self.assertIsNone(restore(old).player_bond)
        key = next(iter(s.core.cats))
        legacy_play(s.core, key)
        s = self.reload(s)
        self.assertEqual(state(s.core)['affinity'][key], 5)
        s.play_with_player(key)
        self.assertEqual(remaining(s.core), 1)
        self.assertEqual(current(s.core).state['affinity_start'], 5)
        source = checkpoint(s.core, set())
        for field, value in (('today', 4), ('today', -1), ('total', 0), ('affinity', 101),
                             ('affinity', True), ('affinity', float('inf'))):
            bad = copy.deepcopy(source)
            bad['state']['player_bond'][field][key] = value
            with self.assertRaises(ValueError):
                bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
                restore(bad)
        self.assertEqual(restore(source).snapshot(), s.core.snapshot())
        bad = copy.deepcopy(source)
        bad['state']['player_bond']['active']['records'].append({})
        bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
        with self.assertRaises((ValueError,KeyError)):
            restore(bad)
