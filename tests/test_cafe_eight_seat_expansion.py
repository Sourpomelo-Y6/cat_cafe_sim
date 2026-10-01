import copy
import os
import tempfile
from pathlib import Path
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_six_seat_expansion as six
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_expansion import (EIGHTH_CUSTOMER_ID, extra_schedule,
    next_step, reason, rules, eight_seat_purchase)
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_operating_cost import estimate
from cat_cafe_sim.core.cafe_seat_equipment import catalog
from cat_cafe_sim.storage.cafe_saves import save_game


class EightSeatExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        selected=starting_conditions(); selected.pop('intake_request')
        # 3日で解放する増設テストは旧来店設定で、猫の状態と同時接客条件を固定する。
        selected['weekdays'].pop('popular_customer_count')
        selected['store_events']['probability']=0
        selected['management']['starting_funds']=20000
        selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=10,target=115)])
        self.session=create_game(Path(self.temp.name)/'games',selected)
    reload=six.SixSeatExpansionTests.reload
    rejected=six.SixSeatExpansionTests.rejected
    five_seats=six.SixSeatExpansionTests.five_seats
    unlocked=six.SixSeatExpansionTests.unlocked
    def seven_seats(self):
        s=self.unlocked(); old=rules(); old.pop('eight_seat_cost')
        s.expand_seats(old); s.expand_seats(old); return s

    def buy(self):
        s=self.seven_seats(); before=s.core.funds; s.expand_seats()
        self.assertEqual(s.core.funds,before-2500)
        return s

    def test_purchase_immediate_seat_next_day_guest_history_and_replay(self):
        s=self.buy(); day=s.core.day
        self.assertEqual(len(s.core.seats),8); self.assertIn('seat-8',s.free_seats)
        self.assertEqual(eight_seat_purchase(s.core),dict(day=day,cost=2500,seats=8))
        self.assertEqual(s.core.summary()['expansion_expenses'],6000)
        row=next(row for row in directory(s) if row['customer_id']==EIGHTH_CUSTOMER_ID)
        self.assertEqual(row['name'], '上田さん'); self.assertIn('8席目',row['description']); self.assertIsNone(row['arrival_tick']); self.assertEqual(row['tomorrow_tick'],24)
        self.assertIsNotNone(row['preference']); preferred=row['preference']
        self.assertNotIn(EIGHTH_CUSTOMER_ID,extra_schedule(s.core,day))
        self.assertEqual(extra_schedule(s.core,day+1)[EIGHTH_CUSTOMER_ID],24)
        s=self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.day_off(); self.assertEqual(s.core.day_results[-1]['customer_visits'],[])
        self.assertEqual(s.core.operating_cost['charges'][-1]['seat_count'],8)
        self.assertEqual(s.core.operating_cost['charges'][-1]['total'],120)
        self.assertEqual(s.core.day_results[-1]['summary']['expansion_expenses'],6000)
        self.assertTrue(all(result['summary']['seat_count']<8 for result in s.core.day_results[:-1]))
        while s.core.tick<=24:s.step()
        self.assertEqual(s.core.visits[EIGHTH_CUSTOMER_ID].arrival_tick,24)
        self.assertEqual(s.core.customer_preferences['customers'][EIGHTH_CUSTOMER_ID],preferred)
        s=self.reload(s); s.finish(); self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_different_day_purchase_charge_once_and_daily_finance(self):
        s=self.seven_seats(); s.day_off()
        before=s.core.funds; s.expand_seats()
        self.assertEqual(s.core.funds,before-2500)
        self.assertEqual(s.core.summary()['expansion_expenses'],2500)
        self.assertEqual(estimate(s.core),120)
        s.day_off(); self.assertEqual(s.core.day_results[-1]['summary']['expansion_expenses'],2500)
        self.assertEqual(s.core.summary()['expansion_expenses'],0)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_eighth_seat_equipment_manual_and_automatic_assignment(self):
        s=self.buy(); item=next(row for row in catalog() if row['id']=='grooming_brush')
        s.purchase_seat_equipment('seat-8',item)
        s.step(); guest=s.core.queue[0]; cat=s.available_cats()[0].id
        s.start(guest,cat,'seat-8'); s=self.reload(s)
        self.assertEqual(s.active_interactions['seat-8'].config.equipment_group,'contact')
        self.rejected(s,lambda:s.start(s.core.queue[0],cat,'seat-1'))
        s.automatic_step(); s.finish()
        while not s.core.closed:s.automatic_step()
        s.next_day()
        with patch.object(type(s),'free_seats',property(lambda session:['seat-8'] if 'seat-8' not in session.active_interactions else [])):
            s.automatic_step(); s.automatic_step()
        self.assertIn('seat-8',s.active_interactions)
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_eight_simultaneous_services_share_clock_and_resume(self):
        s=self.buy(); s.purchase_housing(); s.open_recruitment()
        while len(s.core.cats)<8:
            candidate=next(key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted'])
            s.recruit_cat(candidate)
        s.day_off(); s.set_shifts(list(s.core.cats)); s.interaction_config=replace(s.interaction_config,ticks=30)
        while not s.core.closed and len(s.active_interactions)<8:
            while s.core.queue and s.free_seats and s.available_cats():
                s.start(s.core.queue[0],s.available_cats()[0].id,s.free_seats[0])
            if len(s.active_interactions)==8:break
            s.core.step({key:('pause',None) for key in s.active_interactions}); s.persist()
        self.assertEqual(set(s.active_interactions),{f'seat-{i}' for i in range(1,9)})
        self.assertEqual(len({row.cat_id for row in s.active_interactions.values()}),8)
        s=self.reload(s); tick=s.core.tick; s.automatic_step()
        self.assertEqual(s.core.tick,tick+1)
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_dispatch_needs_nine_cats_and_housing_expansion(self):
        s=self.buy(); s.purchase_housing(); s.open_recruitment()
        while len(s.core.cats)<8:
            candidate=next(key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted'])
            s.recruit_cat(candidate)
        cat=next(iter(s.core.cats)); self.rejected(s,lambda:s.dispatch(cat))
        candidate=next(key for key in s.core.pet_shop['candidates'] if key not in s.core.pet_shop['accepted'])
        s.purchase_cat(candidate); s.dispatch(cat)
        other=next(key for key in s.core.cats if key!=cat)
        self.rejected(s,lambda:s.dispatch(other)); self.reload(s)

    def test_cost_boundary_preparation_restrictions_and_no_ninth_purchase(self):
        s=self.seven_seats(); self.assertEqual(estimate(s.core,8)-estimate(s.core),10)
        s.core.funds=2500; self.rejected(s,s.expand_seats)
        s.core.funds=2501; s.core.recorded_digest=None; s.expand_seats()
        self.assertEqual(s.core.funds,1); self.rejected(s,s.expand_seats)
        self.assertIsNone(next_step(s.core)); self.assertIn('現在追加できる席',reason(s.core,rules()))
        self.assertEqual(len(s.core.expansion['purchases']),6)

    def test_failed_save_retries_and_old_seven_seat_game_can_buy_explicitly(self):
        s=self.seven_seats(); old=rules(); old.pop('eight_seat_cost')
        self.assertIsNone(next_step(s.core,old)); self.rejected(s,lambda:s.expand_seats(old))
        self.assertNotIn(EIGHTH_CUSTOMER_ID,extra_schedule(s.core,s.core.day+1))
        s=self.reload(s); self.assertEqual(len(s.core.seats),7)
        s.expand_seats(); funds=s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        self.assertEqual(s.core.funds,funds)
        s=self.reload(s); self.assertEqual(len(s.core.expansion['purchases']),6)
        self.rejected(s,s.expand_seats)
        self.assertEqual(s.core.funds,funds)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_active_dispatch_survives_expansion_and_business_blocks_purchase(self):
        s=self.seven_seats(); s.purchase_housing(); s.open_recruitment()
        while len(s.core.cats)<8:
            candidate=next(key for key in s.core.recruitment['candidates'] if key not in s.core.recruitment['accepted'])
            s.recruit_cat(candidate)
        cat=next(iter(s.core.cats)); s.dispatch(cat)
        s.expand_seats(); self.assertEqual(s.core.activity(cat),'dispatched')
        s=self.reload(s); self.assertEqual(s.core.activity(cat),'dispatched')
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.step(); self.rejected(s,s.expand_seats)
        self.assertIn('営業準備中',reason(s.core,rules()))
        s.finish(); self.rejected(s,s.expand_seats)

    def test_corrupt_record_goal_history_seats_income_and_invalid_cost_rejected(self):
        for invalid in (0,True,float('nan'),-1):
            with self.assertRaises(ValueError):rules(dict(rules(),eight_seat_cost=invalid))
        s=self.buy(); source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['expansion']['purchases'][5].update(seats=9),
            lambda d:d['state']['expansion']['purchases'][5].update(day=3),
            lambda d:d['state']['expansion']['purchases'][5].update(cost=2400),
            lambda d:d['state']['expansion']['purchases'][3].update(day=3),
            lambda d:d.update(seat_count=7),lambda d:d['state']['seats'].pop('seat-8'),
            lambda d:d['state']['goal'].update(status='active',resolved_day=None),
            lambda d:d['state']['goal']['history'].pop(),
        ):
            bad=copy.deepcopy(source); mutate(bad); bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class EightSeatExpansionGuiTests(unittest.TestCase):
    setUp=EightSeatExpansionTests.setUp
    reload=EightSeatExpansionTests.reload
    rejected=EightSeatExpansionTests.rejected
    five_seats=EightSeatExpansionTests.five_seats
    unlocked=EightSeatExpansionTests.unlocked
    seven_seats=EightSeatExpansionTests.seven_seats

    def test_purchase_cancel_confirm_layout_history_and_operating_cost(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_expansion_gui import CafeExpansionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.seven_seats(); changed=[]; w=CafeExpansionWindow(root,s,lambda:changed.append(True))
        self.assertIn('7席 → 8席',w.details.get()); self.assertIn('2500',w.details.get())
        self.assertIn('110 → 120',w.details.get()); self.assertFalse(w.purchase_button.instate(['disabled']))
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):w.purchase_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.purchase_button.invoke()
        self.assertEqual(len(s.core.seats),8); self.assertTrue(changed)
        w.window.geometry('500x300'); root.update()
        self.assertTrue(w.purchase_button.instate(['disabled']))
        self.assertIn('8席（2500）',w.details.get())
        for button in (w.purchase_button,w.close_button):
            self.assertGreater(button.winfo_width(),0)
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
        w.window.destroy()
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        app=CafeInteractionWindow(root,s)
        root.update()
        self.assertIn('8席',app.status.get())
        self.assertIn('seat-8',app.seat_selector.cget('values'))
