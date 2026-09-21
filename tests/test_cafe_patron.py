import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_patron import rules, pending
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class PatronTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name) / 'relationships.json')
        add_playtest_cats(self.store)
        self.path = Path(self.temp.name) / 'cafe.json'

    def session(self):
        return CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(), opening_ticks=4, arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(), ticks=2))

    def reload(self, session):
        save_game(session, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
        return loaded

    def trip(self, s, key):
        s.dispatch(key, s.core.patron['rules']['destination'])
        event = list(s.core.activities['events'].values())[-1]
        while event['status'] == 'travelling':
            s.day_off()
        return event['id']

    def test_four_returns_clear_save_replay_and_continue_without_popularity_goal(self):
        s = self.session()
        s.enable_management()
        s.enable_patron()
        key = next(iter(s.core.cats))
        for i in range(4):
            event_id = self.trip(s, key)
            self.assertEqual(s.core.patron['satisfaction'], i * 25)
            s = self.reload(s)
            s.resolve_activity(event_id)
            s.resolve_activity(event_id)
            self.assertEqual(s.core.patron['satisfaction'], (i+1)*25)
            self.assertEqual(s.core.funds, 1000+(i+1)*200)
        self.assertTrue(pending(s.core))
        self.assertIsNone(s.core.goal)
        self.assertEqual(s.core.patron['resolved_day'], 9)
        with self.assertRaises(ValueError):
            s.day_off()
        def saved_rules_only(value=None):
            if value is None:
                raise AssertionError('保存済みの設定を使う必要があります。')
            return rules(value)
        with patch('cat_cafe_sim.core.cafe_patron.rules', side_effect=saved_rules_only):
            s = self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s.continue_patron()
        with self.assertRaises(ValueError):
            s.continue_patron()
        event_id = self.trip(s, key)
        s.resolve_activity(event_id)
        self.assertEqual(s.core.patron['satisfaction'], 100)
        self.assertEqual(s.core.patron['resolved_day'], 9)
        self.assertFalse(pending(s.core))
        self.assertEqual(s.core.funds, 2000)
        self.reload(s)

    def test_optional_old_save_and_normal_dispatch_does_not_score(self):
        s = self.reload(self.session())
        self.assertIsNone(s.core.patron)
        self.assertNotIn('patron', checkpoint(s.core, set())['state'])
        with self.assertRaises(ValueError):
            s.enable_patron()
        s.enable_management()
        with self.assertRaises(ValueError):
            s.dispatch(next(iter(s.core.cats)), rules()['destination'])
        s.enable_patron()
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        key = next(iter(s.core.cats))
        s.dispatch(key)
        s.day_off()
        s.resolve_activity(f'dispatch-1-{key}')
        self.assertEqual(s.core.patron['satisfaction'], 0)
        before = s.core.snapshot()
        with self.assertRaises(ValueError):
            s.enable_patron()
        self.assertEqual(s.core.snapshot(), before)
        self.reload(s)

    def test_simultaneous_popularity_result_and_multiple_returns_can_be_confirmed(self):
        s = self.session()
        s.enable_management()
        s.enable_goal(dict(days=1, target=150, cap=300, gain_per_success=5))
        config = rules()
        config['target'] = 25
        config['destination']['days'] = 1
        s.enable_patron(config)
        keys = list(s.core.cats)[:2]
        for key in keys:
            s.dispatch(key, config['destination'])
        s.day_off()
        s.resolve_activity(f'dispatch-1-{keys[0]}')
        with self.assertRaises(ValueError):
            s.continue_patron()
        s.resolve_activity(f'dispatch-1-{keys[1]}')
        self.assertEqual(s.core.patron['satisfaction'], 25)
        s = self.reload(s)
        s.continue_patron()
        with self.assertRaises(ValueError):
            s.day_off()
        s.continue_goal()
        s.day_off()
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_game_over_blocks_receiving(self):
        s = self.session()
        s.enable_management(dict(management_rules(), runaway_threshold=1, return_stress=0, popularity_loss=100))
        config = rules()
        config['destination']['days'] = 1
        s.enable_patron(config)
        key = list(s.core.cats)[-1]
        s.dispatch(key, config['destination'])
        while not s.core.closed:
            s.automatic_step()
        self.assertIsNotNone(s.core.management['game_over'])
        before = s.core.snapshot()
        with self.assertRaises(ValueError):
            s.resolve_activity(f'dispatch-1-{key}')
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(s.core.patron['satisfaction'], 0)
        self.reload(s)

    def test_frozen_destination_and_invalid_state_rejected(self):
        s = self.session()
        s.enable_management()
        s.enable_patron()
        key = next(iter(s.core.cats))
        altered = dict(rules()['destination'], reward=999)
        with self.assertRaises(ValueError):
            s.dispatch(key, altered)
        event_id = self.trip(s, key)
        s.resolve_activity(event_id)
        source = checkpoint(s.core, set())
        for change in (dict(satisfaction=100), dict(status='cleared'), dict(resolved_day=1),
                       dict(started_day=3), dict(continued=True)):
            bad = copy.deepcopy(source)
            bad['state']['patron'].update(change)
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_invalid_rules(self):
        for change in (dict(target=0), dict(gain=True), dict(gain=float('inf')), dict(name='')):
            with self.assertRaises(ValueError):
                rules(dict(rules(), **change))
