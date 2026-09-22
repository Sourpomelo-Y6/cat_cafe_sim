import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_preferences import validate_features, match, rules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.storage.relationships import RelationshipStore


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name) / 'relations.json')
        for key in ('white', 'black', 'unconfigured'):
            self.store.register_cat(key, key, Personality())
        self.path = Path(self.temp.name) / 'game.json'

    def session(self, seats=2):
        return CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=8, arrival_ticks=(0, 0), initial_funds=1000),
            interaction_config=replace(RelationshipConfig(), ticks=5))

    def enable(self, s):
        s.core.initialize_preferences({'white': ['white', 'long_hair'], 'black': ['black', 'short_hair']},
                                     dict(pool=['white'], tension_multiplier=1.25))

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def test_features_and_rules_validation(self):
        self.assertEqual(validate_features(['white', 'long_hair']), ['white', 'long_hair'])
        for values in (['white', 'black'], ['short_hair', 'long_hair'], ['white', 'white'], ['unknown'], 'white', [True]):
            with self.assertRaises(ValueError):
                validate_features(values)
        for data in (dict(pool=['white', 'white'], tension_multiplier=1.25),
                     dict(pool=[], tension_multiplier=1.25),
                     dict(pool=['white'], tension_multiplier=True),
                     dict(pool=['white'], tension_multiplier=float('inf'))):
            with self.assertRaises(ValueError):
                rules(data)

    def test_positive_normal_only_and_forced_threshold_replay(self):
        base = RelationshipConfig(ticks=5)
        boosted = replace(base, customer_tension_multiplier=1.25)
        normal = RelationshipInteraction(base, session_id='same', tension=86)
        buff = RelationshipInteraction(boosted, session_id='same', tension=86)
        normal.step('direct')
        row = buff.step('direct')
        self.assertEqual(row['tension_effect'], 15)
        self.assertEqual(normal.state['tension'], 98)
        self.assertEqual(buff.state['tension'], 100)
        self.assertTrue(buff.state['connect_pending'])
        self.assertFalse(normal.state['connect_pending'])
        self.assertEqual(row['tension_overflow'], 1)
        self.assertEqual(buff.state['engagement'], normal.state['engagement'])
        self.assertEqual(buff.state['affinity_pending'], normal.state['affinity_pending'])
        self.assertEqual(verify_relationship(buff.log()).log(), buff.log())
        for kwargs, action in ((dict(stamina=10), 'direct'), ({}, 'pause'),
                               (dict(tension=100), 'connect'), (dict(engagement=100), 'direct')):
            a = RelationshipInteraction(base, **kwargs)
            b = RelationshipInteraction(boosted, **kwargs)
            self.assertEqual(a.step(action)['tension_effect'], b.step(action)['tension_effect'])
        self.assertNotIn('customer_tension_multiplier', base.to_dict()['rules'])
        legacy = RelationshipInteraction(base)
        legacy.step('direct')
        self.assertEqual(verify_relationship(legacy.log()).log(), legacy.log())

    def test_seat_modes_matching_start_midplay_save_and_replay(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.session(seats)
                self.enable(s)
                s.step()  # first arrival fixes customer preferences
                before = s.core.snapshot()
                choices = {row['cat_id']: row for row in s.cat_choices('guest-1')}
                self.assertTrue(choices['white']['compatibility']['matched'])
                self.assertFalse(choices['black']['compatibility']['matched'])
                self.assertIn('特徴未設定', choices['unconfigured']['compatibility']['text'])
                self.assertEqual(s.core.snapshot(), before)
                s.start('guest-1', 'white')
                if seats == 2:
                    s.start('guest-2', 'black')
                active = {item.cat_id: item for item in s.active_interactions.values()}
                self.assertEqual(active['white'].config.customer_tension_multiplier, 1.25)
                if seats == 2:
                    self.assertEqual(active['black'].config.customer_tension_multiplier, 1)
                s = self.reload(s)
                s.automatic_step()
                s = self.reload(s)
                while not s.core.closed:
                    s.automatic_step()
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                self.reload(s)
                prefs = copy.deepcopy(s.core.customer_preferences)
                s.next_day()
                with patch('cat_cafe_sim.core.cafe_preferences.rules', side_effect=AssertionError('reload config')):
                    s.step()
                self.assertEqual(s.core.customer_preferences, prefs)
                self.reload(s)

    def test_new_game_features_and_recruitment_preserved(self):
        s = create_game(Path(self.temp.name) / 'games')
        self.assertEqual(s.core.cat_features['cat-sora'], ['white', 'long_hair'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s.open_recruitment()
        key = next(iter(s.core.recruitment['candidates']))
        features = list(s.core.recruitment['candidates'][key]['features'])
        s.recruit_cat(key)
        self.assertEqual(s.core.cat_features[key], features)
        self.reload(s)

    def test_old_save_old_candidates_and_player_have_no_buff(self):
        s = self.reload(self.session())
        self.assertIsNone(s.core.customer_preferences)
        self.assertIsNone(s.core.cat_features)
        s.open_recruitment()
        key = next(iter(s.core.recruitment['candidates']))
        s.recruit_cat(key)
        self.assertIsNone(s.core.customer_preferences)
        self.assertTrue(s.core.cat_features[key])
        s = self.reload(s)
        s.play_with_player(key)
        self.assertNotIn('customer_tension_multiplier', s.core.player_bond['active']['config']['rules'])
        s.player_command('direct')
        s.player_command(finish=True)
        self.reload(s)
        old = self.session()
        from cat_cafe_sim.core.cafe_recruitment import candidates
        rows = candidates(old.core.cats)
        for row in rows.values():
            row.pop('features', None)
        old.core.open_recruitment(rows)
        other = list(rows)[-1]
        old.recruit_cat(other)
        self.assertIsNone(old.core.cat_features)
        self.reload(old)

    def test_checkpoint_rejects_preferences_features_and_wrong_match_factor(self):
        s = self.session()
        self.enable(s)
        s.step()
        s.start('guest-1', 'white')
        source = checkpoint(s.core, set())
        for change in (
            lambda state: state['cat_features'].update(white=['white', 'black']),
            lambda state: state['customer_preferences']['customers'].update({'guest-1': 'black'}),
            lambda state: state['customer_preferences']['customers'].clear(),
            lambda state: state['interactions']['seat-1']['config']['rules'].update(customer_tension_multiplier=1),
        ):
            bad = copy.deepcopy(source)
            change(bad['state'])
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
