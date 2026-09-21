import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.core.cafe_adoption import waiting
from cat_cafe_sim.core.cafe_activities import waiting_events
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relations.json')
        for key in ('a','b','c'):
            self.store.register_cat(key, key, Personality())
        self.path = Path(self.temp.name)/'cafe.json'

    def warm(self, cat='a', guest='guest-1', affinity=80):
        interaction = self.store.begin(replace(RelationshipConfig(), ticks=1,
            affinity_favorable=affinity, affinity_enthusiastic=affinity), cat, guest)
        interaction.step('direct')
        self.store.apply(interaction)

    def session(self, seats=2, *, arrivals=(0,), ticks=6):
        return CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=ticks, arrival_ticks=arrivals),
            interaction_config=replace(RelationshipConfig(), ticks=1))

    def offer(self, s):
        s.configure_adoption(True)
        s.automatic_step()
        s.automatic_step()
        return waiting(s.core)[0]['id']

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(s.core.snapshot(), loaded.core.snapshot())
        return loaded

    def close(self, s):
        while not s.core.closed:
            s.automatic_step()

    def rejected(self, s, action):
        before = s.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(s.core.log(), before)

    def test_threshold_and_default_off_preserve_legacy_save(self):
        self.warm(affinity=79.5)
        s = self.session()
        self.assertNotIn('adoption', checkpoint(s.core, set())['state'])
        s.automatic_step();s.automatic_step()
        self.assertFalse(waiting(s.core))
        self.assertIsNone(self.reload(s).core.adoption)
        s = self.session()
        self.offer(s)
        self.assertGreaterEqual(waiting(s.core)[0]['guest_affinity'], 80)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_below_threshold_and_player_equal_or_higher_prevent_offer(self):
        for affinity, player in ((79,0),(79.5,80),(80,100)):
            with self.subTest(affinity=affinity, player=player):
                store = RelationshipStore(Path(self.temp.name)/f'{affinity}-{player}.json')
                store.register_cat('a','a',Personality())
                interaction = store.begin(replace(RelationshipConfig(), ticks=1,
                    affinity_favorable=affinity), 'a', 'guest-1')
                interaction.step('direct');store.apply(interaction)
                s = CafeInteractionSession(store=store,
                    cafe_config=replace(Config.load(), opening_ticks=4, arrival_ticks=(0,)),
                    interaction_config=replace(RelationshipConfig(), ticks=1))
                if player:
                    s.interaction_config = replace(s.interaction_config, affinity_favorable=player)
                    s.play_with_player('a');s.player_command('direct');s.player_command(finish=True)
                    s.interaction_config = replace(s.interaction_config, affinity_favorable=.5)
                s.configure_adoption(True)
                s.automatic_step();s.automatic_step()
                self.assertFalse(waiting(s.core))
                self.reload(s)

    def test_accept_preserves_relationships_history_and_excludes_all_work(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                if seats == 1:
                    self.warm()
                s = self.session(seats)
                event_id = self.offer(s)
                s = self.reload(s)
                self.assertTrue(waiting(s.core))
                before_funds = s.core.funds
                before_store = self.store.path.read_bytes()
                s.resolve_adoption(event_id, 'accept')
                after = s.core.log()
                s.resolve_adoption(event_id, 'accept')
                self.assertEqual(s.core.log(), after)
                self.rejected(s, lambda:s.resolve_adoption(event_id,'decline'))
                self.assertEqual(s.core.activity('a'), 'adopted')
                self.assertEqual(s.core.funds, before_funds)
                self.assertEqual(self.store.path.read_bytes(), before_store)
                self.assertNotIn('a', [c.id for c in s.available_cats()])
                view = dict(cat_details(s, 'a')['basic'])
                self.assertEqual(view['活動'], '譲渡済み')
                self.assertEqual(view['譲渡先'], 'guest-1')
                self.close(s)
                self.assertEqual(s.core.day_result()['cats']['a']['activity'], 'adopted')
                stamina = s.core.cats['a'].stamina
                s.next_day()
                self.assertEqual(s.core.cats['a'].stamina, stamina)
                self.rejected(s, lambda:s.set_shifts(['a']))
                self.rejected(s, lambda:s.dispatch('a'))
                self.rejected(s, lambda:s.play_with_player('a'))
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                self.reload(s)

    def test_waiting_blocks_progress_and_multiple_offers_resolve_independently(self):
        self.warm();self.warm('b','guest-2')
        s = self.session(arrivals=(0,0))
        event_id = self.offer(s)
        self.assertEqual(len(waiting(s.core)), 2)
        for action in (lambda:s.automatic_step(), lambda:s.finish(), lambda:s.next_day(),
                       lambda:s.day_off(), lambda:s.dispatch('c'), lambda:s.play_with_player('c'),
                       lambda:s.configure_adoption(False), lambda:s.set_shifts([]),
                       lambda:s.resolve_adoption(event_id,'unknown')):
            self.rejected(s, action)
        s.resolve_adoption(event_id,'decline')
        self.assertEqual(s.core.activity('a'),'cafe')
        self.rejected(s, lambda:s.automatic_step())
        second = waiting(s.core)[0]['id']
        s.resolve_adoption(second,'accept')
        self.assertFalse(waiting(s.core))
        s = self.reload(s)
        self.close(s)
        s.next_day();s.configure_adoption(False)
        self.assertEqual(len(s.core.adoption['events']),2)
        self.reload(s)

    def test_decline_suppresses_same_day_but_allows_future_day(self):
        self.warm();self.warm('a','guest-2')
        s = self.session(arrivals=(0,3), ticks=7)
        s.set_shifts(['a'])
        event_id = self.offer(s)
        s.resolve_adoption(event_id,'decline')
        self.close(s)
        self.assertEqual(len(s.core.adoption['events']),1)
        s.next_day()
        s.automatic_step();s.automatic_step()
        self.assertEqual(len(waiting(s.core)),1)
        self.assertEqual(waiting(s.core)[0]['day'],2)
        self.reload(s)

    def test_save_failure_pending_results_must_be_persisted_before_resolving(self):
        self.warm()
        s = self.session()
        s.configure_adoption(True);s.automatic_step()
        with patch.object(self.store, 'apply', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                s.automatic_step()
        event_id = waiting(s.core)[0]['id']
        self.rejected(s, lambda:s.resolve_adoption(event_id,'accept'))
        s = self.reload(s)
        self.assertTrue(s.pending)
        s.persist()
        s.resolve_adoption(event_id,'accept')
        self.reload(s)

    def test_other_seat_and_dispatch_return_survive_offer(self):
        self.warm()
        s = self.session(arrivals=(0,0), ticks=4)
        s.dispatch('c');s.configure_adoption(True);s.automatic_step()
        s.start('guest-1','a','seat-1')
        s.interaction_config = replace(s.interaction_config,ticks=3)
        s.start('guest-2','b','seat-2')
        s.automatic_step()
        self.assertIn('seat-2',s.active_interactions)
        s = self.reload(s)
        s.resolve_adoption(waiting(s.core)[0]['id'],'decline')
        self.close(s)
        self.assertTrue(waiting_events(s.core))
        s.resolve_activity(waiting_events(s.core)[0]['id'])
        s.next_day()
        self.reload(s)

    def test_manual_finish_stops_before_next_seat_and_replays(self):
        self.warm();self.warm('b','guest-2')
        s = self.session(arrivals=(0,0))
        s.configure_adoption(True);s.automatic_step()
        s.start('guest-1','a','seat-1');s.start('guest-2','b','seat-2')
        s.finish()
        self.assertEqual(len(waiting(s.core)),1)
        self.assertIn('seat-2',s.active_interactions)
        self.rejected(s,lambda:s.core.finish('seat-2'))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.resolve_adoption(waiting(s.core)[0]['id'],'decline')
        s.finish()
        self.assertEqual(len(waiting(s.core)),1)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_closing_tick_has_both_dispatch_return_and_adoption(self):
        self.warm()
        s = self.session(ticks=2)
        s.dispatch('c')
        event_id = self.offer(s)
        self.assertTrue(s.core.closed)
        self.assertEqual(len(waiting_events(s.core)),2)
        s = self.reload(s)
        s.resolve_adoption(event_id,'accept')
        self.rejected(s, lambda:s.next_day())
        s.resolve_activity(waiting_events(s.core)[0]['id'])
        s.next_day()
        self.assertEqual(s.core.activity('a'),'adopted')
        self.assertEqual(s.core.activity('c'),'cafe')
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_all_cats_adopted_can_take_day_off(self):
        self.warm()
        s = CafeInteractionSession(store=self.store, cat_ids=['a'], seat_count=1,
            cafe_config=replace(Config.load(),opening_ticks=3,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        event_id = self.offer(s);s.resolve_adoption(event_id,'accept')
        self.close(s);s.next_day()
        s.day_off()
        self.assertEqual(s.core.day,3)
        self.assertEqual(s.core.working_cats,set())
        self.reload(s)

    def test_checkpoint_rejects_invalid_event_and_adopted_state(self):
        self.warm()
        s = self.session();event_id = self.offer(s)
        source = checkpoint(s.core, s.pending)
        for field, value in (('guest_affinity',0),('player_affinity',100),('source','unknown'),
                             ('day',2),('choice','accept'),('threshold',float('nan'))):
            bad = copy.deepcopy(source)
            bad['state']['adoption']['events'][event_id][field] = value
            with self.assertRaises(ValueError):
                bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
                restore(bad)
        s.resolve_adoption(event_id,'accept')
        bad = checkpoint(s.core,set())
        bad['state']['activities']['cats']['a'] = 'cafe'
        bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):
            restore(bad)
