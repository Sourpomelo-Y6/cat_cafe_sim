import copy
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, outcome_result, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_quiet_customer import CUSTOMER_ID, description, evaluate, rules, schedule, unlocked_day
from cat_cafe_sim.core.cafe_seat_equipment import catalog
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class QuietCustomerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sequence = 0

    def game(self, seats=2, mode='popularity', legacy=False):
        self.sequence += 1
        selected = starting_conditions(mode)
        selected.pop('intake_request')
        selected['seat_count'] = seats
        selected['goal']['target'] = 105
        if legacy:
            selected.pop('quiet_customer')
        return create_game(Path(self.temp.name) / str(self.sequence), selected)

    def unlock(self, s, advance=False):
        while not s.core.closed:
            s.automatic_step()
        self.assertEqual(s.core.goal['status'], 'cleared')
        (s.advance_goal if advance else s.continue_goal)()
        s.next_day()
        return s

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(s.core.snapshot(), loaded.core.snapshot())
        return loaded

    def prepare(self, seats=2, equipped=True):
        s = self.unlock(self.game(seats))
        if equipped:
            s.purchase_seat_equipment('seat-1', next(row for row in catalog() if row['id']=='quiet_space'))
        s.step()
        s.start(CUSTOMER_ID, 'cat-sora', 'seat-1')
        return s

    def quiet_actions(self, s, count=3):
        s.step('switch', 'voice')
        for _ in range(count):
            s.step('direct')
        s.finish()
        return outcome_result(list(s.core.outcomes.values())[-1])

    def test_unlock_preview_history_rest_and_replay(self):
        s = self.game()
        row = next(row for row in directory(s) if row['customer_id']==CUSTOMER_ID)
        self.assertIn('未解放', row['status'])
        self.assertIsNone(row['arrival_tick'])
        self.assertIn('静かな交流スペース', description(s.core))
        self.assertIsNone(unlocked_day(s.core))
        self.unlock(s, advance=True)
        self.assertEqual(unlocked_day(s.core), 1)
        self.assertEqual(schedule(s.core, 2), {CUSTOMER_ID:0})
        self.assertEqual(sum(e['kind']=='quiet_customer_unlocked' for e in s.core.events), 1)
        s.day_off()
        self.assertNotIn(CUSTOMER_ID, s.core.visits)
        self.reload(s)
        lowered = copy.deepcopy(s.core)
        lowered.management['popularity'] = 1
        self.assertEqual(schedule(lowered, 3), {CUSTOMER_ID:0})
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_success_single_multi_seat_finance_save_and_equipment_movement(self):
        for seats in (1, 2):
            s = self.prepare(seats)
            s = self.reload(s)
            result = self.quiet_actions(s)
            row = evaluate(s.core, result)
            self.assertTrue(row['success'])
            self.assertEqual(row['quiet_count'], 3)
            self.assertEqual(row['bonus'], 150)
            event = next(e for e in s.core.events if e['kind']=='quiet_customer_result')
            self.assertIn('追加人気 3', event['text'])
            from cat_cafe_sim.core.cafe_customer_satisfaction import evaluate as satisfaction
            visit = s.core.visits[CUSTOMER_ID]
            self.assertEqual(visit.bill, visit.seated_ticks*s.core.config.time_price + result['bonus_funds'] + 150 + satisfaction(s.core,result)['bonus'])
            funds = s.core.funds
            s.finish()
            self.assertEqual(s.core.funds, funds)
            s = self.reload(s)
            while not s.core.closed:
                s.step()
            self.assertGreaterEqual(s.core.goal['days'][-1]['gain'], 3)
            s = self.reload(s)
            s.next_day()
            s.equip_seat('seat-1')
            self.assertTrue(evaluate(s.core,result)['success'])
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_missing_equipment_wrong_equipment_and_insufficient_count(self):
        for equipment, count in ((None,3),('toys',3),('quiet_space',2),('quiet_space',0)):
            s = self.unlock(self.game())
            if equipment:
                s.purchase_seat_equipment('seat-1', next(row for row in catalog() if row['id']==equipment))
            s.step(); s.start(CUSTOMER_ID,'cat-sora','seat-1')
            result = self.quiet_actions(s,count)
            row = evaluate(s.core,result)
            self.assertFalse(row['success'])
            self.assertEqual(row['bonus'],0)
            self.assertEqual(row['quiet_count'],count)
            self.reload(s)

    def test_normal_actions_only_and_policy_prioritizes_quiet_over_mastery(self):
        config = replace(RelationshipConfig(),quiet_service=True,equipment_group='quiet',equipment_engagement_multiplier=1.35,
                         mastery_group='play',mastery_engagement_multiplier=1.1)
        active = RelationshipInteraction(config, tension=100)
        active.step('connect'); active.step('switch','voice'); active.step('pause')
        result = active.finish()
        self.assertEqual(sum(result['type_actions'].values()),0)
        self.assertTrue(result['quiet_equipment'])
        self.assertEqual(verify_relationship(active.log()).result(), result)
        fresh = RelationshipInteraction(config)
        action, target = AutomaticInteractionPolicy().choose(fresh.observation(),fresh.valid_actions(),config)
        self.assertEqual(action,'switch')
        self.assertIn(target,('voice','presence'))
        legacy = RelationshipInteraction(RelationshipConfig()); legacy.finish()
        self.assertNotIn('quiet_service', legacy.log()['config']['rules'])
        self.assertNotIn('quiet_equipment',legacy.result())

    def test_automatic_assignment_selects_equipped_free_seat_and_actual_service(self):
        s = self.unlock(self.game())
        s.purchase_seat_equipment('seat-2', next(row for row in catalog() if row['id']=='quiet_space'))
        s.step()
        # Serve the earlier arrivals in turn, leaving the quiet customer waiting.
        while s.core.queue[0] != CUSTOMER_ID:
            guest = s.core.queue[0]
            s.start(guest, 'cat-mike','seat-1'); s.finish()
        s.automatic_step()
        self.assertEqual(s.active_interactions['seat-2'].customer_id, CUSTOMER_ID)
        self.assertTrue(s.active_interactions['seat-2'].config.quiet_service)
        while s.active_interactions:
            s.automatic_step()
        result = next(outcome_result(value) for value in s.core.outcomes.values()
                      if outcome_result(value)['customer_id']==CUSTOMER_ID)
        self.assertTrue(evaluate(s.core,result)['success'])
        self.reload(s)

    def test_unserved_and_save_failure_do_not_award_or_duplicate(self):
        s = self.unlock(self.game()); s.step()
        while not s.core.closed:
            s.step()
        self.assertFalse(any(e['kind']=='quiet_customer_result' for e in s.core.events))
        self.reload(s)
        s = self.prepare()
        s.step('switch','presence')
        for _ in range(3): s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):
                s.finish()
        self.assertTrue(s.pending)
        funds = s.core.funds
        save_game(s,s.checkpoint_path)
        loaded,_ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.funds,funds)
        loaded.persist()
        self.assertFalse(loaded.pending)
        self.assertEqual(loaded.core.funds,funds)
        self.assertEqual(sum(e['kind']=='quiet_customer_result' for e in loaded.core.events),1)

    def test_legacy_and_other_modes_do_not_introduce_customer(self):
        for mode, legacy in (('popularity',True),('patron',False),('bond',False),('free',False)):
            s = self.game(mode=mode,legacy=legacy)
            self.assertIsNone(s.core.quiet_customer)
            self.assertFalse(any(row['customer_id']==CUSTOMER_ID for row in directory(s)))
            self.assertNotIn('quiet_customer',s.core.snapshot())
            self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_frozen_rules_and_corruption_rejection(self):
        s = self.prepare(); original = checkpoint(s.core,set())
        with patch('cat_cafe_sim.core.cafe_quiet_customer.rules', side_effect=lambda data: rules(data)):
            self.reload(s)
        for change in (dict(equipment='toys'),dict(quiet_count=0),dict(quiet_count=True),dict(bonus=0),dict(popularity_bonus=float('inf'))):
            with self.assertRaises(ValueError): rules(dict(rules(),**change))
        for mutate in (
                lambda state: state['quiet_customer'].update(equipment='toys'),
                lambda state: state['interactions']['seat-1']['config']['rules'].pop('quiet_service')):
            bad=copy.deepcopy(original); mutate(bad['state'])
            bad['digest']=digest({key:value for key,value in bad.items() if key!='digest'})
            with self.assertRaises(ValueError): restore(bad)
        result=self.quiet_actions(s); original=checkpoint(s.core,set())
        bad=copy.deepcopy(original); bad['state']['quiet_customer']['bonus']+=1
        bad['digest']=digest({key:value for key,value in bad.items() if key!='digest'})
        with self.assertRaises(ValueError): restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','set CAT_CAFE_TEST_GUI=1 on a desktop')
class QuietCustomerGuiTests(unittest.TestCase):
    setUp=QuietCustomerTests.setUp
    game=QuietCustomerTests.game
    unlock=QuietCustomerTests.unlock
    prepare=QuietCustomerTests.prepare
    quiet_actions=QuietCustomerTests.quiet_actions

    def test_directory_conditions_latest_result_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_customers_gui import CafeCustomersWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.game(); w=CafeCustomersWindow(root,s)
        w.customers.selection_set(CUSTOMER_ID); w.select()
        self.assertIn('第1段階',w.details.get())
        self.assertIn('合計3回',w.details.get())
        self.assertIn('追加料金＋150・人気＋3',w.details.get())
        w.window.destroy()
        s=self.prepare(); self.quiet_actions(s)
        w=CafeCustomersWindow(root,s); w.customers.selection_set(CUSTOMER_ID); w.select()
        self.assertIn('直近の接客：達成',w.details.get())
        self.assertIn('静かな交流 3/3回',w.details.get())
        w.window.geometry('660x520'); root.update()
        self.assertGreater(w.cats.winfo_height(),0)
