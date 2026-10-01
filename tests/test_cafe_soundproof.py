"""人気第2段階の防音改修・回復・費用・保存の回帰。"""
import copy
import os
import unittest
from unittest.mock import patch,PropertyMock
import test_cafe_equipment as fixtures
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.cafe_equipment import soundproof_rules,stress_bonus,expenses
from cat_cafe_sim.cafe_shift_forecast import shift_forecast
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,restore,digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game


class SoundproofTests(unittest.TestCase):
    setUp=fixtures.EquipmentTests.setUp
    session=fixtures.EquipmentTests.session
    close=fixtures.EquipmentTests.close
    reload=fixtures.EquipmentTests.reload
    rejected=fixtures.EquipmentTests.rejected

    def unlocked(self,seats=2):
        s=self.session(funds=10000,seats=seats)
        s.enable_management(dict(management_rules(),starting_funds=10000,stress_per_service_tick=0))
        s.enable_goal(dict(days=10,target=105,cap=300,gain_per_success=5,stages=[dict(days=10,target=110),dict(days=10,target=200)]))
        s.purchase_rest_space();self.close(s);s.advance_goal();s.next_day()
        self.rejected(s,s.soundproof_rest_space)
        self.close(s);s.advance_goal();s.next_day();return s

    def test_purchase_stress_forecast_fatigue_and_finance(self):
        for seats in (1,2):
            s=self.unlocked(seats);original=copy.deepcopy(s.core.rest_space);funds=s.core.funds
            s.soundproof_rest_space();self.assertEqual(s.core.funds,funds-1000)
            self.assertEqual(s.core.rest_space['rules'],original['rules']);self.assertEqual(expenses(s.core),1400)
            self.assertEqual(s.core.summary()['equipment_expenses'],1000);self.rejected(s,s.soundproof_rest_space)
            s.core.management['stress']['a']=50
            before=s.core.snapshot();value=shift_forecast(s.core,'a')
            self.assertEqual(value['rest_stress'],20);self.assertEqual(s.core.snapshot(),before)
            s.day_off();self.assertEqual(s.core.management['stress']['a'],20)
            self.assertEqual(s.core.day_results[-1]['summary']['equipment_expenses'],1000)
            # 手動の状態調整を含まない購入の保存・再生も検証する。
            s=self.unlocked(seats);s.soundproof_rest_space();s.day_off();s=self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_rules_preconditions_funds_pending_and_working_exclusion(self):
        s=self.session();self.rejected(s,s.soundproof_rest_space)
        for funds in (1000,999):
            s=self.unlocked();s.core.funds=funds;self.rejected(s,s.soundproof_rest_space)
        s=self.unlocked();s.core.funds=1001;s.soundproof_rest_space();self.assertEqual(s.core.funds,1)
        s=self.unlocked()
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):self.rejected(s,s.soundproof_rest_space)
        s.soundproof_rest_space();s.core.management['stress']['a']=50
        self.close(s);self.assertEqual(s.core.management['stress']['a'],50)
        for field,value in (('cost',True),('cost',0),('stress_recovery_bonus',101),('stress_recovery_bonus',float('nan'))):
            with self.assertRaises(ValueError):soundproof_rules(dict(soundproof_rules(),**{field:value}))

    def test_absent_and_sick_recovery_and_lower_limit(self):
        s=self.unlocked();s.soundproof_rest_space();s.core.cats['a'].fatigue=0;s.dispatch('a');s.core.management['stress']['a']=50
        self.assertEqual(stress_bonus(s.core,'a'),0);s.day_off();self.assertEqual(s.core.management['stress']['a'],50)
        s=self.unlocked();s.soundproof_rest_space();s.core.cats['a'].health_status='sick';s.core.cats['a'].recovery_days_remaining=2;s.core.initial_health['a']=dict(status='sick',remaining=2)
        s.core.management['stress']['a']=5;s.set_shifts(['b','c']);s.day_off()
        self.assertEqual(s.core.management['stress']['a'],0);self.assertEqual(s.core.cats['a'].recovery_days_remaining,1)

    def test_old_saved_equipment_frozen_rules_and_save_failure(self):
        s=self.unlocked();s=self.reload(s);self.assertNotIn('soundproof',s.core.rest_space)
        s.soundproof_rest_space();funds=s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,self.path)
        original=soundproof_rules
        with patch('cat_cafe_sim.core.cafe_equipment.soundproof_rules',side_effect=lambda data=None:original(data) if data is not None else self.fail('reread settings')):
            s=self.reload(s);self.assertEqual(s.core.funds,funds)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.rejected(s,s.soundproof_rest_space)

    def test_corrupt_record_date_effect_and_cost_rejected(self):
        s=self.unlocked();s.soundproof_rest_space();source=checkpoint(s.core,set())
        for mutate in (lambda d:d['rest_space']['soundproof'].update(day=1),lambda d:d['rest_space']['soundproof']['rules'].update(cost=999),lambda d:d['rest_space']['soundproof']['rules'].update(stress_recovery_bonus=-1),lambda d:d['rest_space']['soundproof'].update(extra=True)):
            bad=copy.deepcopy(source);mutate(bad['state']);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class SoundproofWindowTests(unittest.TestCase):
    setUp=SoundproofTests.setUp
    session=SoundproofTests.session
    close=SoundproofTests.close
    rejected=SoundproofTests.rejected
    unlocked=SoundproofTests.unlocked

    def test_confirm_cancel_purchase_logs_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_equipment_gui import CafeEquipmentWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy);s=self.unlocked();app=CafeInteractionWindow(root,s)
        w=CafeEquipmentWindow(root,s,app.refresh);w.window.geometry('500x440');root.update();before=s.core.snapshot()
        self.assertFalse(w.soundproof_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.soundproof_button.invoke()
        self.assertIn('ストレス回復＋10',ask.call_args.args[1]);self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.soundproof_button.invoke()
        root.update();self.assertTrue(w.soundproof_button.instate(['disabled']));self.assertIn('防音改修',w.details.get())
        self.assertTrue(any('防音改修' in str(app.history.item(k)['values']) for k in app.history.get_children()))
        for button in (w.soundproof_button,w.purchase_button,w.upgrade_button,w.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),w.window.winfo_rootx()+w.window.winfo_width())
