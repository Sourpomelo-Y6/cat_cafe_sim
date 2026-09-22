import copy
import unittest
from unittest.mock import patch
from dataclasses import replace
import test_cafe_patron as fixtures
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.cafe_weekdays import rules, schedule, day_label
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game


class WeekdayTests(unittest.TestCase):
    setUp = fixtures.PatronTests.setUp
    reload = fixtures.PatronTests.reload

    def session(self, seats=2):
        return CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=4, arrival_ticks=(0,0,2), queue_capacity=1))

    def test_schedule_stable_ids_counts_and_resume_single_and_multi_seat(self):
        for seats in (1,2):
            s = self.session(seats)
            s.core.initialize_weekdays()
            s.enable_management()
            self.assertEqual(schedule(s.core), {'guest-1':0,'guest-3':2})
            self.assertEqual(schedule(s.core,2), {'guest-2':0})
            self.assertEqual(schedule(s.core,7), {'guest-1':0,'guest-2':0,'guest-3':2})
            self.assertEqual(schedule(s.core,8), schedule(s.core))
            initial = directory(s)
            s.step()
            self.assertEqual(set(s.core.visits), {'guest-1'})
            s = self.reload(s)
            while not s.core.closed:
                s.step()
            self.assertEqual(set(s.core.visits), {'guest-1','guest-3'})
            self.assertEqual(s.core.summary()['arrivals'],2)
            self.assertEqual([r['visits'] for r in directory(s)],[1,0,1])
            s.next_day()
            self.assertEqual(s.core.day_results[0]['customer_visits'], ['guest-1','guest-3'])
            self.assertEqual([r['arrival_tick'] for r in directory(s)], [r['tomorrow_tick'] for r in initial])
            s.step()
            self.assertEqual(set(s.core.visits), {'guest-2'})
            self.assertTrue(s.core.visits['guest-2'].first_visit)
            while not s.core.closed:
                s.step()
            s.next_day()
            s.step()
            self.assertFalse(s.core.visits['guest-1'].first_visit)
            self.assertEqual([r['visits'] for r in directory(s)],[2,1,1])
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.reload(s)

    def test_day_off_wrap_and_empty_day(self):
        s = self.session()
        s.core.initialize_weekdays()
        s.enable_management()
        for _ in range(7):
            s.day_off()
            s = self.reload(s)
        self.assertEqual(day_label(s.core), '8日目（月）')
        self.assertTrue(all(r['visits']==0 for r in directory(s)))
        self.assertTrue(all(r['customer_visits']==[] for r in s.core.day_results))
        s = self.session()
        s.core.initialize_weekdays(dict(start_weekday=0, patterns=[[1]]))
        s.enable_management()
        while not s.core.closed:
            s.step()
        self.assertEqual(s.core.summary()['arrivals'],0)
        s.next_day()
        s.step()
        self.assertEqual(set(s.core.visits), {'guest-1','guest-2'})
        self.assertEqual(s.core.visits['guest-2'].departure_reason,'queue_full')
        self.reload(s)

    def test_new_game_preferences_frozen_settings_and_legacy_unchanged(self):
        s = create_game(self.temp.name)
        self.assertIsNotNone(s.core.weekdays)
        preview = directory(s)
        before = s.core.snapshot()
        directory(s)
        self.assertEqual(s.core.snapshot(),before)
        s.automatic_step()
        for key in s.core.visits:
            self.assertEqual(s.core.customer_preferences['customers'][key],next(r['preference'] for r in preview if r['customer_id']==key))
        with patch('cat_cafe_sim.core.cafe_weekdays.rules', side_effect=lambda data=None: rules(data) if data is not None else self.fail('設定の再読込')):
            self.reload(s)
        old = self.reload(self.session())
        self.assertIsNone(old.core.weekdays)
        self.assertNotIn('weekdays',checkpoint(old.core,set())['state'])
        self.assertEqual(schedule(old.core,1),schedule(old.core,2))
        self.assertEqual(day_label(old.core),'1日目')

    def test_invalid_configuration_history_and_start_timing(self):
        for value in (dict(start_weekday=True,patterns=[[0]]),dict(start_weekday=7,patterns=[[0]]),
                      dict(start_weekday=0,patterns=[]),dict(start_weekday=0,patterns=[[0,0]]),dict(start_weekday=0,patterns=[[7]])):
            with self.assertRaises(ValueError):
                rules(value)
        s = self.session()
        s.core.initialize_weekdays()
        before=s.core.snapshot()
        with self.assertRaises(ValueError):
            s.core.initialize_weekdays()
        self.assertEqual(before,s.core.snapshot())
        while not s.core.closed:
            s.step()
        s.next_day()
        source=checkpoint(s.core,set())
        for mutation in ('history','start','missing'):
            bad=copy.deepcopy(source)
            if mutation=='history':
                bad['state']['day_results'][0]['customer_visits']=['guest-2']
            elif mutation=='start':
                bad['state']['weekdays']['start_weekday']=1
            else:
                del bad['state']['weekdays']
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        old=self.session()
        old.step()
        with self.assertRaises(ValueError):
            old.core.initialize_weekdays()
