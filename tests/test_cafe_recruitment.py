import copy
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.cafe_recruitment import candidates, expenses
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class RecruitmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name) / 'relations.json')
        for key in ('a', 'b', 'c'):
            self.store.register_cat(key, key, Personality())
        self.path = Path(self.temp.name) / 'cafe.json'

    def session(self, seats=2, **config):
        return CafeInteractionSession(store=self.store, cat_ids=['a', 'b', 'c'], seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=2, arrival_ticks=(0,), **config),
            interaction_config=replace(RelationshipConfig(), ticks=1))

    def prepare(self, s):
        s.open_recruitment()
        return next(iter(s.core.recruitment['candidates']))

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def rejected(self, s, action, error=ValueError):
        before, profiles = s.core.log(), self.store._read()
        with self.assertRaises(error):
            action()
        self.assertEqual(s.core.log(), before)
        self.assertEqual(self.store._read(), profiles)

    def close(self, s):
        while not s.core.closed:
            s.automatic_step()

    def test_fixed_candidates_old_save_cost_and_replay_in_both_seat_modes(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.session(seats, initial_funds=1000)
                self.assertNotIn('recruitment', checkpoint(s.core, set())['state'])
                s = self.reload(s)
                key = self.prepare(s)
                original = copy.deepcopy(s.core.recruitment)
                s.open_recruitment()
                s = self.reload(s)
                with patch('cat_cafe_sim.core.cafe_recruitment.candidates', side_effect=AssertionError('reroll')):
                    s.open_recruitment()
                self.assertEqual(s.core.recruitment, original)
                s.recruit_cat(key)
                self.assertEqual(s.core.funds, 800)
                self.assertEqual(s.core.summary()['recruitment_expenses'], 200)
                self.assertEqual(len(s.core.cats), 4)
                self.assertNotIn(key, s.core.working_cats)
                self.assertEqual(s.core.cats[key].stamina, 100)
                self.assertEqual(dict(cat_details(s, key)['basic'])['加入日'], '1日目')
                self.assertEqual(s.profiles[key]['name'], original['candidates'][key]['name'])
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                s = self.reload(s)
                self.rejected(s, lambda: s.recruit_cat(key))
                self.close(s)
                s.next_day()
                self.assertEqual(s.core.summary()['recruitment_expenses'], 0)
                self.assertEqual(s.core.day_results[0]['summary']['recruitment_expenses'], 200)
                self.reload(s)

    def test_no_base_replay_and_default_single_cat_core(self):
        core = CafeInteractionCore(replace(Config.load(), initial_funds=1000), compact=True)
        core.set_shifts(['cat-1'])
        core.enable_health(asdict(HealthRules.load()))
        core.open_recruitment(candidates(core.cats))
        core.recruit_cat('rescue-1')
        self.assertIsNone(core.roster_ids)
        self.assertEqual(verify_cafe_interaction(core.log()).snapshot(), core.snapshot())
        self.assertEqual(restore(checkpoint(core, set())).snapshot(), core.snapshot())

    def test_initializes_optional_states_and_uses_profile_in_player_and_cafe(self):
        s = self.session(initial_funds=1000)
        s.enable_management()
        s.configure_adoption(True)
        s.dispatch('c')
        s.play_with_player('a'); s.player_command(finish=True)
        key = self.prepare(s)
        s.recruit_cat(key)
        self.assertEqual(s.core.management['stress'][key], 0)
        self.assertEqual(s.core.activities['day_locations'][key], 'cafe')
        for field in ('affinity', 'today', 'total'):
            self.assertEqual(s.core.player_bond[field][key], 0)
        s.play_with_player(key)
        profile = s.core.recruitment['candidates'][key]['personality']
        self.assertEqual(s.core.player_bond['active']['config']['personality'], profile)
        s.player_command('direct'); s.player_command(finish=True)
        s.set_shifts([key])
        s.automatic_step(); s.automatic_step()
        self.assertEqual(s.store.snapshot(key, 'guest-1')['revision'], 1)
        log = next(v for v in s.core.outcomes.values() if v['result']['cat_id'] == key)
        self.assertEqual(log['result']['cat_id'], key)
        self.reload(s)

    def test_recruited_cat_can_dispatch_and_return(self):
        s = self.session(initial_funds=1000)
        key = self.prepare(s)
        s.recruit_cat(key); s.dispatch(key)
        s = self.reload(s)
        s.day_off()
        s.resolve_activity(f'dispatch-1-{key}')
        self.assertEqual(s.core.activity(key), 'cafe')
        self.assertEqual(s.core.funds, 900)
        self.assertEqual(s.core.day_results[0]['cats'][key]['activity'], 'dispatched')
        self.reload(s)

    def test_funds_must_remain_positive_with_or_without_management(self):
        for managed in (False, True):
            for funds in (0, 199, 200, 201):
                with self.subTest(managed=managed, funds=funds):
                    s = self.session(initial_funds=funds)
                    if managed:
                        s.enable_management(dict(management_rules(), starting_funds=max(1, funds)))
                    key = self.prepare(s)
                    if funds <= 200:
                        self.rejected(s, lambda: s.recruit_cat(key))
                    else:
                        s.recruit_cat(key)
                        self.assertEqual(s.core.funds, 1)
                        self.reload(s)

    def test_registration_failure_changes_neither_roster_nor_money_and_retry_once(self):
        s = self.session(initial_funds=1000)
        key = self.prepare(s)
        s = self.reload(s)
        with patch.object(s.store, '_write', side_effect=OSError('full')):
            self.rejected(s, lambda: s.recruit_cat(key), OSError)
        s.recruit_cat(key)
        self.assertEqual(s.core.funds, 800)
        with patch.object(RelationshipStore, '_write', side_effect=OSError('full')):
            self.rejected(s, lambda: save_game(s, self.path), OSError)
        s = self.reload(s)
        self.rejected(s, lambda: s.recruit_cat(key))
        self.assertEqual(expenses(s.core), 200)

    def test_older_save_and_external_profile_changes_are_rejected(self):
        s = self.session(initial_funds=1000)
        key = self.prepare(s)
        save_game(s, self.path)
        s.recruit_cat(key)
        with self.assertRaises(ValueError):
            load_game(self.path)
        s = self.reload(s)
        data = s.store._read()
        data['cats'][key]['name'] = 'changed'
        s.store._write(data)
        with self.assertRaises(ValueError):
            load_game(self.path)
        with self.assertRaises(ValueError):
            save_game(s, self.path)

    def test_candidate_ids_do_not_reuse_registered_or_former_relationship_cats(self):
        self.store.register_cat('rescue-1', 'existing', Personality())
        s = self.session(initial_funds=1000)
        self.assertEqual(self.prepare(s), 'rescue-2')
        self.store.register_cat('rescue-2', 'external', Personality())
        self.rejected(s, lambda: s.recruit_cat('rescue-2'))
        self.assertNotIn('rescue-2', s.core.cats)

    def test_no_join_during_business_player_interaction_pending_event_or_game_over(self):
        s = self.session(initial_funds=1000)
        key = self.prepare(s)
        s.play_with_player('a')
        self.rejected(s, lambda: s.recruit_cat(key))
        s.player_command(finish=True)
        s.dispatch('c'); s.day_off()
        self.rejected(s, lambda: s.recruit_cat(key))
        s.resolve_activity('dispatch-1-c')
        s.automatic_step()
        self.rejected(s, lambda: s.recruit_cat(key))
        self.close(s)
        self.rejected(s, lambda: s.recruit_cat(key))
        s = self.session(initial_funds=1000)
        key = self.prepare(s)
        s.enable_management(dict(management_rules(), runaway_threshold=1, return_stress=0, popularity_loss=100))
        self.close(s)
        self.assertIsNotNone(s.core.management['game_over'])
        self.rejected(s, lambda: s.recruit_cat(key))

    def test_pending_relationship_write_blocks_recruitment(self):
        s = self.session(initial_funds=1000)
        key = self.prepare(s)
        s.automatic_step()
        with patch.object(s.store, 'apply', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                s.automatic_step()
        self.assertTrue(s.pending)
        self.rejected(s, lambda: s.recruit_cat(key))
        s.persist(); s.next_day(); s.recruit_cat(key)
        self.reload(s)
        self.assertNotIn(key, s.core.day_results[0]['cats'])

    def test_malformed_join_record_accounting_and_profile_are_rejected(self):
        s = self.session(initial_funds=1000)
        key = self.prepare(s); s.recruit_cat(key)
        source = checkpoint(s.core, set())
        changes = [lambda d: d['state']['recruitment']['accepted'].update({key: 2}),
                   lambda d: d['state']['recruitment']['accepted'].clear(),
                   lambda d: d['state']['recruitment']['candidates'][key].update(cost=-1),
                   lambda d: d['state']['recruitment']['candidates'][key].update(cost=100),
                   lambda d: d['state']['recruitment']['candidates'][key].update(cost=True),
                   lambda d: d['state']['recruitment'].update(opened_day=0)]
        for mutate in changes:
            bad = copy.deepcopy(source); mutate(bad)
            bad['digest'] = digest({k: v for k, v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
