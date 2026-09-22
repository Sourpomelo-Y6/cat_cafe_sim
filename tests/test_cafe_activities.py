import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.cafe_activities import destination, waiting_events
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relations.json');add_playtest_cats(self.store)
        self.path=Path(self.temp.name)/'cafe.json'

    def session(self, seats=2):
        return CafeInteractionSession(store=self.store,seat_count=seats,
            cafe_config=replace(Config.load(),opening_ticks=4,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=2))

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def reload(self,s):
        save_game(s,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(s.core.snapshot(),loaded.core.snapshot())
        return loaded

    def test_roundtrip_depart_wait_resolve_and_next_day(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                s=self.session(seats);key=next(iter(s.core.cats))
                s.dispatch(key);s=self.reload(s)
                self.assertNotIn(key,[cat.id for cat in s.available_cats()])
                self.assertNotIn(key,s.core.working_cats)
                with self.assertRaises(ValueError):s.set_shifts([key])
                self.close(s)
                event=waiting_events(s.core)[0]
                before=s.core.funds
                with self.assertRaises(ValueError):s.next_day()
                s=self.reload(s)
                s.resolve_activity(event['id'])
                s.resolve_activity(event['id'])
                self.assertEqual(s.core.funds,before+100)
                self.assertEqual(s.core.activity(key),'cafe')
                self.assertEqual(s.core.day_result()['cats'][key]['activity'],'dispatched')
                self.assertEqual(s.core.summary()['dispatch_income'],100)
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
                s=self.reload(s);s.next_day();s.set_shifts([key])
                self.assertIn(key,[cat.id for cat in s.available_cats()])

    def test_day_off_advances_trip_without_rest_recovery_and_waits(self):
        s=self.session();key=next(iter(s.core.cats));s.core.cats[key].fatigue=40
        # Record a normal command after arranging a test starting fatigue.
        s.set_shifts(list(s.core.cats))
        s.dispatch(key,dict(destination(),days=2))
        s.day_off()
        self.assertEqual(s.core.day,2)
        self.assertFalse(waiting_events(s.core))
        self.assertEqual(s.core.cats[key].fatigue,40)
        s=self.reload(s);s.day_off()
        self.assertEqual(s.core.day,3)
        self.assertEqual(s.core.day_results[-1]['day_type'],'day_off')
        with self.assertRaises(ValueError):s.automatic_step()
        with self.assertRaises(ValueError):s.day_off()
        s=self.reload(s);e=waiting_events(s.core)[0];s.resolve_activity(e['id'])
        s=self.reload(s)
        self.assertEqual(s.core.funds,100)
        self.assertEqual(s.core.activities['day_locations'][key],'cafe')
        s.set_shifts([key]);s.automatic_step()

    def test_departure_limits_and_invalid_commands_do_not_mutate(self):
        s=self.session();keys=list(s.core.cats)
        for key in keys[:3]:s.dispatch(key)
        before=s.core.log()
        for action in (lambda:s.dispatch(keys[3]),lambda:s.dispatch(keys[0]),lambda:s.dispatch('unknown'),
                       lambda:s.resolve_activity('unknown'),lambda:s.core.resolve_activity(next(iter(s.core.activities['events'])),'invalid')):
            with self.assertRaises(ValueError):action()
            self.assertEqual(before,s.core.log())
        s.automatic_step();before=s.core.log()
        with self.assertRaises(ValueError):s.dispatch(keys[4])
        self.assertEqual(before,s.core.log())

    def test_multiple_returns_block_until_all_received_and_replay_without_checkpoint(self):
        s=self.session()
        for key in list(s.core.cats)[:2]:s.dispatch(key)
        self.close(s)
        events=waiting_events(s.core)
        s.resolve_activity(events[0]['id'])
        with self.assertRaises(ValueError):s.next_day()
        s.resolve_activity(events[1]['id'])
        s.next_day();s.day_off()
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertEqual(s.core.day_results[0]['summary']['dispatch_income'],200)
        self.assertEqual(s.core.day_results[1]['summary']['dispatch_income'],0)
        self.reload(s)

    def test_unhealthy_and_excess_fatigue_rejected(self):
        s=self.session();key=next(iter(s.core.cats))
        s.core.cats[key].health_status='sick'
        with self.assertRaises(ValueError):s.dispatch(key)
        s.core.cats[key].health_status='healthy';s.core.cats[key].fatigue=61
        with self.assertRaises(ValueError):s.dispatch(key)
        self.assertIsNone(s.core.activities)

    def test_pending_relationships_block_event_resolution(self):
        s=self.session();s.dispatch(next(iter(s.core.cats)))
        s.automatic_step();s.automatic_step()
        with patch.object(self.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.automatic_step()
        before=s.core.log()
        with self.assertRaises(ValueError):s.resolve_activity(next(iter(s.core.activities['events'])))
        self.assertEqual(before,s.core.log());s.persist();self.close(s)
        s.resolve_activity(waiting_events(s.core)[0]['id'])

    def test_old_checkpoint_has_no_extension_and_new_corruption_is_rejected(self):
        s=self.session();old=checkpoint(s.core,set())
        self.assertNotIn('activities',old['state'])
        restored=restore(old)
        self.assertEqual(restored.snapshot(),s.core.snapshot())
        key=next(iter(s.core.cats));s.dispatch(key);data=checkpoint(s.core,set())
        for field,value in (('status','resolved'),('remaining',0),('destination',dict(destination(),reward=-1))):
            bad=copy.deepcopy(data);e=next(iter(bad['state']['activities']['events'].values()));e[field]=value
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        s.day_off();s.resolve_activity(waiting_events(s.core)[0]['id'])
        data=checkpoint(s.core,set());data['state']['funds']+=100
        data['summary']['funds']+=100;data['digest']=digest({k:v for k,v in data.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(data)


    def test_destinations_different_durations_rewards_and_frozen_saved_rules(self):
        from cat_cafe_sim.core.cafe_activities import destinations, dispatch_reason
        from cat_cafe_sim.core.cafe_traits import definitions
        s = self.session()
        keys = list(s.core.cats)
        traits = definitions()
        s.core.initialize_traits({keys[1]: traits['hospitality'], keys[2]: traits['outgoing']})
        rules = destinations()
        self.assertEqual(len(rules), 3)
        for key, rule in zip(keys, rules):
            self.assertEqual(dispatch_reason(s.core, key, rule), '')
            s.dispatch(key, rule)
        s = self.reload(s)
        total = 0
        for index, expected in enumerate((100, 260, 562.5)):
            s.day_off()
            from cat_cafe_sim.core.cafe_dispatch_encounters import waiting as choices
            for event in choices(s.core):
                s.resolve_dispatch_choice(event['id'], event['encounter']['rules']['choices'][1]['id'])
            events = waiting_events(s.core)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['cat_id'], keys[index])
            with patch('cat_cafe_sim.core.cafe_activities.destinations', side_effect=AssertionError('config reload')):
                s = self.reload(s)
            s.resolve_activity(events[0]['id'])
            total += expected
            self.assertEqual(s.core.funds, total)
            s.resolve_activity(events[0]['id'])
            self.assertEqual(s.core.funds, total)
        self.assertEqual(len(s.core.activities['events']), 3)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_required_trait_and_fatigue_boundaries_do_not_mutate_on_rejection(self):
        from cat_cafe_sim.core.cafe_activities import destinations, dispatch_reason
        from cat_cafe_sim.core.cafe_traits import definitions
        for rule in destinations()[1:]:
            s = self.session()
            key = next(iter(s.core.cats))
            self.assertIn(rule['required_trait_name'], dispatch_reason(s.core, key, rule))
            before = s.core.log()
            with self.assertRaises(ValueError):
                s.dispatch(key, rule)
            self.assertEqual(s.core.log(), before)
            s.core.initialize_traits({key: definitions()[rule['required_trait']]})
            s.core.cats[key].fatigue = rule['max_fatigue'] + 1
            self.assertIn('疲労', dispatch_reason(s.core, key, rule))
            before = s.core.snapshot()
            with self.assertRaises(ValueError):
                s.dispatch(key, rule)
            self.assertEqual(s.core.snapshot(), before)
            s.core.cats[key].fatigue = rule['max_fatigue']
            self.assertEqual(dispatch_reason(s.core, key, rule), '')
            s.dispatch(key, rule)

    def test_destination_condition_validation_and_legacy_rules(self):
        from cat_cafe_sim.core.cafe_activities import destinations
        legacy = destination()
        self.assertNotIn('required_trait', legacy)
        for change in ({'required_trait': 'outgoing'},
                       {'required_trait': '', 'required_trait_name': '外出好き'},
                       {'required_trait': 'outgoing', 'required_trait_name': None},
                       {'days': True}, {'reward': float('inf')}):
            with self.assertRaises(ValueError):
                destination(dict(legacy, **change))
        self.assertEqual(destinations()[0], legacy)
