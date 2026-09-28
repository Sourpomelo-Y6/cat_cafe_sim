import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_customer_discontent import rules, row
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_weekdays import schedule
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class CustomerDiscontentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relationships.json')
        add_playtest_cats(self.store)

    def session(self, selected=None, arrivals=(0,0)):
        config = replace(Config.load(), opening_ticks=4, arrival_ticks=arrivals, queue_capacity=1, max_wait_ticks=2)
        s = CafeInteractionSession(store=self.store, seat_count=2, cafe_config=config,
            interaction_config=replace(RelationshipConfig(), ticks=2))
        s.core.initialize_weekdays(dict(start_weekday=0, patterns=[list(range(7))]))
        s.core.initialize_preferences({key:[] for key in s.core.cats}, dict(pool=['white'], tension_multiplier=1.25))
        s.core.initialize_customer_loyalty(dict(gain=25, threshold=100))
        s.core.initialize_customer_discontent(selected or rules())
        return s

    def reload(self, s):
        path = Path(self.temp.name)/'cafe.json'
        save_game(s, path); loaded,_ = load_game(path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def test_queue_full_suspends_seven_days_then_returns_at_fifty(self):
        selected = dict(rules(), waiting_gain=100)
        s = self.session(selected)
        s.step()
        self.assertEqual(s.core.visits['guest-2'].departure_reason, 'queue_full')
        self.assertEqual(row(s.core,'guest-2')['score'],100)
        self.assertEqual(row(s.core,'guest-2')['suspended_until'],8)
        self.assertNotIn('guest-2',schedule(s.core,2))
        event=next(e for e in s.core.events if e['kind']=='customer_discontent_changed')
        self.assertTrue(event['suspended']);self.assertEqual(event['suspended_until'],8)
        while not s.core.closed:s.step()
        s=self.reload(s);s.next_day()
        for day in range(2,9):
            self.assertNotIn('guest-2',schedule(s.core))
            s.day_off()
        self.assertEqual(s.core.day,9)
        self.assertIn('guest-2',schedule(s.core))
        self.assertEqual(row(s.core,'guest-2')['score'],50)
        self.assertIsNone(row(s.core,'guest-2')['suspended_until'])
        listing=next(r for r in directory(s) if r['customer_id']=='guest-2')
        self.assertEqual(listing['discontent'],50)
        s.step()
        self.assertEqual(row(s.core,'guest-2')['score'],100)
        self.assertEqual(row(s.core,'guest-2')['suspended_until'],16)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_wait_timeout_and_good_service_reduces_discontent(self):
        s=self.session(arrivals=(0,))
        s.step();s.step()  # guest-1は待機期限で不満25
        self.assertEqual(s.core.visits['guest-1'].departure_reason,'wait_timeout')
        self.assertEqual(row(s.core,'guest-1')['score'],25)
        while not s.core.closed:s.step()
        s.next_day();s.step()
        self.assertIn('guest-1',s.core.queue)
        s.start('guest-1',next(iter(s.core.cats)))
        while s.active_interactions:s.automatic_step()
        self.assertEqual(row(s.core,'guest-1')['score'],0)
        self.assertTrue(any(e['kind']=='customer_discontent_changed' and e['reason']=='good_service' for e in s.core.events))
        self.reload(s)

    def test_advanced_failure_suspends_without_good_recovery(self):
        selected=starting_conditions();selected.pop('intake_request');selected['goal']['target']=105
        selected['customer_discontent']=dict(rules(),advanced_failure_gain=100,good_service_recovery=0)
        s=create_game(Path(self.temp.name)/'games',selected)
        while not s.core.closed:s.automatic_step()
        s.continue_goal();s.next_day();s.step()
        from cat_cafe_sim.core.cafe_advanced_customers import CUSTOMER_ID
        s.start(CUSTOMER_ID,'cat-sora');s.finish()
        self.assertEqual(row(s.core,CUSTOMER_ID)['score'],100)
        self.assertEqual(row(s.core,CUSTOMER_ID)['suspended_until'],9)
        self.assertNotIn(CUSTOMER_ID,schedule(s.core,3))
        self.reload(s)

    def test_legacy_and_corrupt_records(self):
        selected=starting_conditions('free');selected.pop('intake_request');selected.pop('customer_discontent')
        selected.pop('customer_satisfaction')
        old=create_game(Path(self.temp.name)/'old',selected)
        while not old.core.closed:old.automatic_step()
        self.assertIsNone(old.core.customer_discontent)
        self.assertNotIn('customer_outcomes',old.core.day_result())
        self.reload(old)
        s=self.session(dict(rules(),waiting_gain=100));s.step()
        source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['customer_discontent']['customers']['guest-2'].update(score=0),
            lambda d:d['state']['customer_discontent']['customers']['guest-2']['suspensions'][0].update(until=99),
            lambda d:d['state']['customer_discontent']['rules'].update(waiting_gain=50),
        ):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        while not s.core.closed:s.step()
        s.next_day()
        historical=checkpoint(s.core,set())
        del historical['state']['day_results'][0]['customer_outcomes']
        historical['digest']=digest({k:v for k,v in historical.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(historical)
        with patch('cat_cafe_sim.core.cafe_customer_discontent.rules',side_effect=lambda value=None:rules(value) if value is not None else self.fail('設定の再読込')):
            self.reload(s)

    def test_invalid_rules(self):
        base=rules()
        for change in (dict(waiting_gain=-1),dict(suspension_days=True),dict(suspension_days=0),
                       dict(return_score=100),dict(threshold=0),dict(advanced_failure_gain=101)):
            with self.assertRaises(ValueError):rules(dict(base,**change))
