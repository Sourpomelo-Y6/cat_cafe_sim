import copy
import unittest
from dataclasses import replace
from unittest.mock import patch
import test_cafe_patron as fixtures
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.cafe_activities import destinations, waiting_events, reward
from cat_cafe_sim.core.cafe_dispatch_encounters import waiting, pending, definition, for_destination
from cat_cafe_sim.core.cafe_traits import definitions
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.cafe_saves import save_game


class DispatchEncounterTests(unittest.TestCase):
    setUp=fixtures.PatronTests.setUp
    reload=fixtures.PatronTests.reload

    def session(self, management=True):
        s=CafeInteractionSession(store=self.store,cafe_config=replace(Config.load(),opening_ticks=3,arrival_ticks=()))
        keys=list(s.core.cats)
        s.core.initialize_traits({keys[0]:definitions()['hospitality'],keys[1]:definitions()['outgoing']})
        if management:s.enable_management()
        return s

    def event(self,s,index=1):
        key=list(s.core.cats)[index-1]
        s.dispatch(key,destinations()[index])
        return s.core.activities['events'][f'dispatch-{s.core.day}-{key}']

    def test_extra_work_answer_blocks_progress_persists_and_pays_once(self):
        for off in (False,True):
            s=self.session()
            e=self.event(s)
            event_id=e['id'];key=e['cat_id']
            self.assertEqual(e['encounter']['status'],'scheduled')
            s=self.reload(s)
            if off:s.day_off()
            else:
                while not s.core.closed:s.automatic_step()
            e=s.core.activities['events'][event_id]
            self.assertTrue(pending(e))
            self.assertEqual(e['remaining'],1)
            self.assertEqual(e['encounter']['occurred_day'],1)
            for action in (s.day_off,s.next_day,s.automatic_step,lambda:s.resolve_activity(event_id)):
                before=s.core.snapshot()
                with self.assertRaises(ValueError):action()
                self.assertEqual(s.core.snapshot(),before)
            s=self.reload(s)
            s.resolve_dispatch_choice(event_id,'accept')
            self.assertEqual(s.core.cats[key].fatigue,10)
            self.assertEqual(s.core.management['stress'][key],5)
            self.assertEqual(s.core.funds,1000)
            before=s.core.snapshot()
            s.resolve_dispatch_choice(event_id,'accept')
            self.assertEqual(s.core.snapshot(),before)
            with self.assertRaises(ValueError):s.resolve_dispatch_choice(event_id,'decline')
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,self.path)
            self.assertEqual(s.core.snapshot(),before)
            s=self.reload(s)
            if s.core.closed:s.next_day()
            s.day_off()
            s.resolve_activity(event_id)
            s.resolve_activity(event_id)
            self.assertEqual(s.core.funds,1360)
            self.assertEqual(s.core.cats[key].fatigue,10)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.reload(s)

    def test_rest_and_normal_options_and_no_management(self):
        for management in (True,False):
            for choice in ('rest','continue'):
                s=self.session(management)
                e=self.event(s,2);key=e['cat_id']
                s.day_off()
                s.resolve_dispatch_choice(e['id'],choice)
                self.assertEqual(s.core.cats[key].fatigue,0)
                if not management:self.assertIsNone(e['encounter']['changes']['stress_after'])
                s=self.reload(s)
                for _ in range(2):s.day_off()
                s.resolve_activity(e['id'])
                expected=512.5 if choice=='rest' else 562.5
                self.assertEqual(s.core.funds,(1000 if management else 0)+expected)
                if management:self.assertEqual(s.core.management['stress'][key],10)
                self.reload(s)

    def test_multiple_choices_and_returns_independent_of_popularity_result(self):
        s=self.session()
        s.enable_goal(dict(days=1,target=150,cap=300,gain_per_success=5))
        first=self.event(s,1);second=self.event(s,2)
        third=list(s.core.cats)[2]
        s.dispatch(third)
        s.day_off()
        self.assertEqual(len(waiting_events(s.core)),3)
        s.resolve_dispatch_choice(first['id'],'decline')
        self.assertEqual(len(waiting(s.core)),1)
        with self.assertRaises(ValueError):s.day_off()
        s.resolve_dispatch_choice(second['id'],'rest')
        s.resolve_activity(f'dispatch-1-{third}')
        s=self.reload(s)
        s.continue_goal()
        s.day_off()
        s.resolve_activity(first['id'])
        s.day_off()
        s.resolve_activity(second['id'])
        self.assertEqual(s.core.funds,1872.5)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_legacy_started_trip_remains_without_event_and_frozen_rules(self):
        s=self.session()
        key=next(iter(s.core.cats))
        # Old replay operations and already-started trips have no encounter definition.
        s.core.dispatch(key,destinations()[1])
        s=self.reload(s)
        self.assertNotIn('encounter',next(iter(s.core.activities['events'].values())))
        s.day_off();self.assertFalse(waiting(s.core))
        s.day_off();s.resolve_activity(f'dispatch-1-{key}')
        self.assertEqual(s.core.funds,1260)
        s=self.session()
        e=self.event(s)
        with patch('cat_cafe_sim.core.cafe_dispatch_encounters.for_destination',side_effect=AssertionError('config reload')):
            s=self.reload(s)
            s.day_off()
            s.resolve_dispatch_choice(e['id'],'accept')
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_invalid_state_effects_and_game_over(self):
        s=self.session()
        e=self.event(s)
        with self.assertRaises(ValueError):s.resolve_dispatch_choice(e['id'],'accept')
        s.day_off()
        source=checkpoint(s.core,set())
        for change in (dict(status='resolved'),dict(occurred_day=2),dict(choice='accept'),dict(resolved_day=2)):
            bad=copy.deepcopy(source)
            bad['state']['activities']['events'][e['id']]['encounter'].update(change)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        with self.assertRaises(ValueError):s.resolve_dispatch_choice(e['id'],'unknown')
        s.core.management['game_over']=dict(reason='funds',day=s.core.day)
        before=s.core.snapshot()
        with self.assertRaises(ValueError):s.resolve_dispatch_choice(e['id'],'accept')
        self.assertEqual(s.core.snapshot(),before)
        spec=for_destination(destinations()[1])
        for value in (True,float('inf'),101):
            bad=copy.deepcopy(spec);bad['choices'][0]['fatigue']=value
            with self.assertRaises(ValueError):definition(bad)

    def test_rest_reduces_existing_fatigue_and_stress_and_preserves_return_trait(self):
        s=self.session()
        key=list(s.core.cats)[1]
        trip=dict(destinations()[1],required_trait='outgoing',required_trait_name='外出好き')
        s.dispatch(key,trip)
        first=f'dispatch-1-{key}'
        s.day_off();s.resolve_dispatch_choice(first,'accept')
        s.day_off();s.resolve_activity(first)
        self.assertEqual(s.core.cats[key].fatigue,10)
        self.assertEqual(s.core.management['stress'][key],15)
        s.dispatch(key,destinations()[2])
        second=f'dispatch-3-{key}'
        s.day_off();s.resolve_dispatch_choice(second,'rest')
        self.assertEqual(s.core.cats[key].fatigue,0)
        self.assertEqual(s.core.management['stress'][key],5)
        s=self.reload(s)
        s.day_off();s.day_off();s.resolve_activity(second)
        self.assertEqual(s.core.management['stress'][key],15)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
