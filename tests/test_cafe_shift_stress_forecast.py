"""閉店時ストレス予測、特性・旧保存・GUIの回帰。"""
import copy
import os
import unittest
from unittest.mock import patch
import test_cafe_traits as fixtures
from cat_cafe_sim.cafe_shift_forecast import shift_forecast


class ShiftStressForecastTests(unittest.TestCase):
    setUp=fixtures.TraitTests.setUp
    session=fixtures.TraitTests.session
    close=fixtures.TraitTests.close
    reload=fixtures.TraitTests.reload

    def test_trait_work_estimate_matches_actual_close_and_saved_rules(self):
        for trait_id,multiplier in (('hardworking',1.25),('hospitality',.5)):
            s=self.session({'a':trait_id});self.close(s);s=self.reload(s);s.next_day()
            before=s.core.snapshot();value=shift_forecast(s.core,'a')
            self.assertEqual(value['current_stress'],multiplier)
            self.assertEqual(value['work_stress'],multiplier*2)
            self.assertEqual(value['rest_stress'],0);self.assertEqual(s.core.snapshot(),before)
            with patch('cat_cafe_sim.core.cafe_traits.definitions',side_effect=AssertionError('settings changed')):
                self.close(s);self.assertEqual(s.core.management['stress']['a'],value['work_stress'])
                self.reload(s)

    def test_initial_day_zero_history_and_caps(self):
        s=self.session({'a':'hardworking'});value=shift_forecast(s.core,'a')
        self.assertIsNone(value['work_stress']);self.assertEqual(value['rest_stress'],0)
        self.close(s);s.next_day();s.core.management['stress']['a']=99.5
        self.assertEqual(shift_forecast(s.core,'a')['work_stress'],100)
        s.core.day_results[-1]['cats']['a']['service_ticks']=0
        self.assertEqual(shift_forecast(s.core,'a')['work_stress'],99.5)
        s.core.management['stress']['a']=5
        self.assertEqual(shift_forecast(s.core,'a')['rest_stress'],0)

    def test_rest_uses_management_recovery_and_matches_actual_close(self):
        s=self.session({'a':'hardworking'});self.close(s);s.next_day()
        s.core.management['stress']['a']=50;s.core.management['rules']['rest_recovery']=7
        value=shift_forecast(s.core,'a');self.assertEqual(value['rest_stress'],43)
        s.set_shifts(['b','c']);self.close(s);self.assertEqual(s.core.management['stress']['a'],43)

    def test_sick_absent_legacy_and_no_fatigue_rules(self):
        s=self.session({'a':'hardworking'});self.close(s);s.next_day()
        s.core.cats['a'].health_status='sick';value=shift_forecast(s.core,'a')
        self.assertIsNone(value['work_stress']);self.assertEqual(value['rest_stress'],0)
        s.core.cats['a'].health_status='healthy';s.dispatch('a')
        value=shift_forecast(s.core,'a');self.assertIsNone(value['work_stress']);self.assertIsNone(value['rest_stress'])
        s=self.session(management=False);s=self.reload(s);before=s.core.snapshot()
        value=shift_forecast(s.core,'a')
        for field in ('current_stress','work_stress','rest_stress'):self.assertIsNone(value[field])
        self.assertEqual(s.core.snapshot(),before)
        s=self.session();s.core.shift_rules=None
        self.assertIsNone(shift_forecast(s.core,'a')['rest']);self.assertEqual(shift_forecast(s.core,'a')['rest_stress'],0)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class ShiftStressForecastWindowTests(unittest.TestCase):
    setUp=ShiftStressForecastTests.setUp
    session=ShiftStressForecastTests.session
    close=ShiftStressForecastTests.close

    def window(self,s):
        import tkinter as tk
        from cat_cafe_sim.cafe_shift_gui import CafeShiftWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        return root,CafeShiftWindow(root,s,lambda:None)

    def test_values_selection_schedule_and_small_layout_do_not_mutate(self):
        s=self.session({'a':'hardworking','b':'hospitality'});self.close(s);s.next_day()
        before=s.core.snapshot();root,w=self.window(s);w.window.geometry('500x400');root.update()
        self.assertEqual(w.tree.set('a','stress'),'1.25');self.assertEqual(w.tree.set('a','work_stress'),'2.5')
        self.assertEqual(w.tree.set('b','work_stress'),'1');self.assertEqual(w.tree.set('a','rest_stress'),'0')
        self.assertIn('ストレス',w.forecast_note.get());w.tree.selection_set('b');root.update();w.set_selected(False)
        self.assertEqual(s.core.snapshot(),before)
        w.tree.xview_moveto(1);root.update();self.assertGreater(w.tree.winfo_height(),15)
        self.assertLessEqual(w.save_button.winfo_rooty()+w.save_button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())

    def test_first_day_sick_absent_and_legacy_text(self):
        s=self.session();root,w=self.window(s);root.update()
        self.assertEqual(w.tree.set('a','work_stress'),'—');self.assertIn('記録がない',w.forecast_note.get());w.window.destroy()
        s.dispatch('a');s.core.cats['b'].health_status='sick';root,w=self.window(s);root.update()
        self.assertEqual(w.tree.set('a','rest_stress'),'在店していません')
        self.assertEqual(w.tree.set('b','work_stress'),'出勤不可');w.window.destroy()
        s=self.session(management=False);root,w=self.window(s);root.update()
        self.assertEqual(w.tree.set('a','stress'),'未導入');self.assertEqual(w.tree.set('a','rest_stress'),'—')
        self.assertIn('ストレス管理が未導入',w.forecast_note.get())
