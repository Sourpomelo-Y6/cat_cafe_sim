import copy
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_expansion import (SIXTH_CUSTOMER_ID, FIFTH_CUSTOMER_ID, EXTRA_CUSTOMER_ID,
    extra_schedule, final_popularity_cleared, next_step, reason, rules, six_seat_purchase)
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_operating_cost import estimate
from cat_cafe_sim.core.cafe_reservation import waiting
from cat_cafe_sim.core.cafe_seat_equipment import catalog
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class SixSeatExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        selected=starting_conditions(); selected.pop('intake_request')
        # 3日で解放する増設テストは旧来店設定で、猫の状態と同時接客条件を固定する。
        selected['weekdays'].pop('popular_customer_count')
        selected['store_events']['probability']=0
        selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=10,target=115)])
        self.session=create_game(Path(self.temp.name)/'games',selected)

    def reload(self,s):
        save_game(s,s.checkpoint_path); loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(s.core.snapshot(),loaded.core.snapshot()); return loaded

    def rejected(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(s.core.log(),before)

    def five_seats(self):
        s=self.session; s.expand_seats()
        for step in (4,5):
            while not s.core.closed:s.automatic_step()
            self.assertEqual(s.core.goal['status'],'cleared')
            s.advance_goal(); s.next_day()
            if waiting(s.core):s.resolve_reservation('decline')
            s.expand_seats(); self.assertEqual(len(s.core.seats),step)
        return s

    def unlocked(self):
        s=self.five_seats()
        self.assertFalse(final_popularity_cleared(s.core))
        self.rejected(s,s.expand_seats)
        self.assertIn('最終段階',reason(s.core,rules()))
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.goal['status'],'cleared')
        self.assertTrue(final_popularity_cleared(s.core))
        self.rejected(s,s.expand_seats)
        s.continue_goal(); self.rejected(s,s.expand_seats)
        s.next_day()
        if waiting(s.core):s.resolve_reservation('decline')
        return s

    def buy(self):
        s=self.unlocked(); before=s.core.funds; s.expand_seats()
        self.assertEqual(s.core.funds,before-1500); return s

    def test_unlock_cost_history_next_day_arrival_save_and_replay(self):
        s=self.buy(); self.assertEqual(len(s.core.seats),6)
        self.assertEqual(s.core.summary()['seat_count'],6)
        self.assertEqual(s.core.summary()['expansion_expenses'],1500)
        self.assertEqual(six_seat_purchase(s.core),dict(day=4,cost=1500,seats=6))
        row=next(row for row in directory(s) if row['customer_id']==SIXTH_CUSTOMER_ID)
        self.assertEqual(row['name'], '藤田さん'); self.assertIn('6席目',row['description']); self.assertIsNone(row['arrival_tick']); self.assertEqual(row['tomorrow_tick'],12)
        self.assertIsNotNone(row['preference'])
        self.assertNotIn(SIXTH_CUSTOMER_ID,extra_schedule(s.core,4))
        self.assertEqual(extra_schedule(s.core,5),{EXTRA_CUSTOMER_ID:0,FIFTH_CUSTOMER_ID:6,SIXTH_CUSTOMER_ID:12})
        s=self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.day_off(); self.assertEqual(s.core.day_results[-1]['customer_visits'],[])
        self.assertEqual(s.core.operating_cost['charges'][-1]['seat_count'],6)
        self.assertEqual(s.core.operating_cost['charges'][-1]['total'],100)
        self.assertEqual(s.core.day_results[-1]['summary']['expansion_expenses'],1500)
        while s.core.tick<=12:s.step()
        self.assertIn(SIXTH_CUSTOMER_ID,s.core.visits)
        self.assertEqual(s.core.visits[SIXTH_CUSTOMER_ID].arrival_tick,12)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_sixth_seat_equipment_service_automatic_assignment_and_history(self):
        s=self.buy(); self.assertIn('seat-6',s.free_seats)
        s.purchase_seat_equipment('seat-6',next(row for row in catalog() if row['id']=='grooming_brush'))
        s.step(); guest=s.core.queue[0]; cat=s.available_cats()[0].id
        s.start(guest,cat,'seat-6'); s=self.reload(s)
        self.assertEqual(s.active_interactions['seat-6'].customer_id,guest)
        self.rejected(s,lambda:s.start(s.core.queue[0],cat,'seat-1'))
        s.automatic_step(); s.finish(); self.reload(s)
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.summary()['seat_count'],6)
        s.next_day()
        # Automatic assignment can use the new seat as the only free choice.
        with patch.object(type(s),'free_seats',property(lambda session:['seat-6'] if 'seat-6' not in session.active_interactions else [])):
            s.automatic_step(); s.automatic_step()
        self.assertIn('seat-6',s.active_interactions)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_six_simultaneous_interactions_share_clock_and_resume(self):
        s=self.buy(); s.purchase_housing(); s.open_recruitment()
        while len(s.core.cats)<6:
            candidate=next(key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted'])
            s.recruit_cat(candidate)
        s.day_off(); s.set_shifts(list(s.core.cats))
        s.interaction_config=replace(s.interaction_config,ticks=30)
        while not s.core.closed and len(s.active_interactions)<6:
            while s.core.queue and s.free_seats and s.available_cats():
                s.start(s.core.queue[0],s.available_cats()[0].id,s.free_seats[0])
            if len(s.active_interactions)==6:break
            s.core.step({key:('pause',None) for key in s.active_interactions}); s.persist()
        self.assertEqual(set(s.active_interactions),{f'seat-{i}' for i in range(1,7)})
        self.assertEqual(len({row.cat_id for row in s.active_interactions.values()}),6)
        s=self.reload(s); tick=s.core.tick; s.automatic_step()
        self.assertEqual(s.core.tick,tick+1)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_dispatch_requires_extra_cat_and_new_cat_remains_compatible(self):
        s=self.buy(); cat=next(iter(s.core.cats))
        self.rejected(s,lambda:s.dispatch(cat))
        s.purchase_housing(); s.open_recruitment()
        while len(s.core.cats)<7:
            candidate=next(key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted'])
            s.recruit_cat(candidate)
        self.assertEqual(len(s.core.cats),7)
        s.dispatch(cat)
        other=next(key for key in s.core.cats if key!=cat)
        self.rejected(s,lambda:s.dispatch(other))
        self.reload(s)

    def test_funds_boundary_save_failure_and_legacy_six_seat_limit(self):
        s=self.unlocked(); self.assertEqual(estimate(s.core,6)-estimate(s.core),10)
        s.core.funds=1500; self.rejected(s,s.expand_seats)
        s.core.funds=1501; s.core.recorded_digest=None; s.expand_seats()
        self.assertEqual(s.core.funds,1); self.rejected(s,s.expand_seats)
        old=rules(); old.pop('seven_seat_cost'); old.pop('eight_seat_cost')
        self.assertIsNone(next_step(s.core,old)); self.assertIn('現在追加できる席',reason(s.core,old))
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        self.assertEqual(s.core.funds,1)
        self.assertEqual(len(s.core.expansion['purchases']),4)

    def test_failed_save_retries_without_duplicate_purchase_or_expense(self):
        s=self.buy(); funds=s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        self.assertEqual(s.core.funds,funds)
        s=self.reload(s); self.assertEqual(len(s.core.expansion['purchases']),4)
        old=rules(); old.pop('seven_seat_cost'); old.pop('eight_seat_cost')
        self.rejected(s,lambda:s.expand_seats(old))
        self.assertEqual(s.core.summary()['expansion_expenses'],1500)

    def test_old_rules_single_stage_and_other_modes_do_not_unlock_sixth(self):
        s=self.unlocked(); old=rules(); old.pop('six_seat_cost'); old.pop('seven_seat_cost'); old.pop('eight_seat_cost')
        self.assertIsNone(next_step(s.core,old)); self.rejected(s,lambda:s.expand_seats(old))
        self.assertNotIn(SIXTH_CUSTOMER_ID,extra_schedule(s.core,s.core.day+1))
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        core=copy.deepcopy(s.core); core.goal['rules'].pop('stages')
        self.assertFalse(final_popularity_cleared(core))
        for value in (None,dict(core.goal,tracking_only=True),dict(core.goal,status='expired')):
            other=copy.deepcopy(core); other.goal=value
            self.assertFalse(final_popularity_cleared(other))
        for invalid in (0,True,float('nan')):
            with self.assertRaises(ValueError):rules(dict(rules(),six_seat_cost=invalid))

    def test_corrupt_six_seat_record_goal_history_and_cost_are_rejected(self):
        s=self.buy(); source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['expansion']['purchases'][3].update(seats=7),
            lambda d:d['state']['expansion']['purchases'][3].update(day=3),
            lambda d:d['state']['expansion']['purchases'][3].update(cost=1400),
            lambda d:d.update(seat_count=5),lambda d:d['state']['seats'].pop('seat-6'),
            lambda d:d['state']['goal'].update(status='active',resolved_day=None),
            lambda d:d['state']['goal']['history'].pop(),
        ):
            bad=copy.deepcopy(source); mutate(bad); bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class SixSeatExpansionGuiTests(unittest.TestCase):
    setUp=SixSeatExpansionTests.setUp
    rejected=SixSeatExpansionTests.rejected
    five_seats=SixSeatExpansionTests.five_seats
    unlocked=SixSeatExpansionTests.unlocked

    def test_unlock_purchase_confirmation_layout_and_operating_cost_display(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_expansion_gui import CafeExpansionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.unlocked(); changed=[]; w=CafeExpansionWindow(root,s,lambda:changed.append(True))
        self.assertIn('5席 → 6席',w.details.get()); self.assertIn('1500',w.details.get())
        self.assertIn('90 → 100',w.details.get()); self.assertFalse(w.purchase_button.instate(['disabled']))
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):w.purchase_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.purchase_button.invoke()
        self.assertEqual(len(s.core.seats),6); self.assertTrue(changed)
        w.window.geometry('500x300'); root.update()
        self.assertIn('6席 → 7席',w.details.get())
        self.assertGreater(w.purchase_button.winfo_width(),0); w.window.destroy()
