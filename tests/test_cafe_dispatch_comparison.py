"""派遣比較の見込み・副作用なし・旧ゲーム・GUIからの出発。"""
import copy
import os
import unittest
from unittest.mock import patch, PropertyMock

import test_cafe_photo_dispatch_match as fixtures
from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
from cat_cafe_sim.core.cafe_dispatch_unlocks import photo_destination
from cat_cafe_sim.core.cafe_activities import reward


class DispatchComparisonTests(unittest.TestCase):
    setUp=fixtures.PhotoDispatchMatchTests.setUp
    game=fixtures.PhotoDispatchMatchTests.game
    unlock=fixtures.PhotoDispatchMatchTests.unlock
    depart=fixtures.PhotoDispatchMatchTests.depart
    receive=fixtures.PhotoDispatchMatchTests.receive
    reload_replay=fixtures.PhotoDispatchMatchTests.reload_replay

    def test_preview_matches_departure_and_both_choices_without_mutating(self):
        for choice in ('accept','decline'):
            s=self.game(white=True,service=True);before=s.core.snapshot();stored=s.store._read()
            rows=comparison_rows(s,'cat-mike');row=next(r for r in rows if r['destination']['id']=='cat_photo_studio')
            self.assertEqual(row['reason'],'');self.assertEqual(row['reward'],390)
            self.assertIn('報酬 490',row['options'][0]);self.assertIn('報酬 390',row['options'][1])
            self.assertIn('疲労 +15',row['options'][0]);self.assertIn('ストレス +5',row['options'][1])
            self.assertIn('ルカ',row['detail']);self.assertIn('追加報酬 40',row['detail'])
            self.assertEqual(s.core.snapshot(),before);self.assertEqual(s.store._read(),stored)
            event_id=self.depart(s);self.receive(s,event_id,choice)
            self.assertEqual(reward(s.core,s.core.activities['events'][event_id]),490 if choice=='accept' else 390)
            s.resolve_dispatch_introduction(event_id,'decline');self.reload_replay(s)

    def test_eligibility_pending_and_cat_state_reasons(self):
        s=self.game();core=s.core
        row=lambda:next(r for r in comparison_rows(s,'cat-mike') if r['destination']['id']=='cat_photo_studio')
        self.assertEqual(row()['reason'],'')
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            self.assertTrue(all('保存' in r['reason'] for r in comparison_rows(s,'cat-mike')))
        core.cats['cat-mike'].fatigue=41;self.assertIn('疲労',row()['reason'])
        core.cats['cat-mike'].fatigue=0;core.cats['cat-mike'].health_status='sick';self.assertIn('健康',row()['reason'])
        core.cats['cat-mike'].health_status='healthy'
        del core.dispatch_unlocks['unlocked']['cat_photo_studio'];self.assertIn('未解放',row()['reason'])
        with self.assertRaises(ValueError):comparison_rows(s,'missing')

    def test_saved_conditions_old_games_and_no_growth_health_or_management(self):
        s=self.game(white=True,service=True,legacy=True);s=self.reload_replay(s)
        row=next(r for r in comparison_rows(s,'cat-mike') if r['destination']['id']=='cat_photo_studio')
        self.assertEqual(row['reward'],350);self.assertIn('歓迎条件：なし',row['detail'])
        old=copy.deepcopy(s);old.core.dispatch_unlocks=None;old.core.dispatch_trouble=None;old.core.dispatch_introduction=None
        old.core.management=None;old.core.growth=None;old.core.shift_rules=None;old.core.health_rules=None
        rows=comparison_rows(old,'cat-mike')
        self.assertEqual(len(rows),3);self.assertNotIn('cat_photo_studio',[r['destination']['id'] for r in rows])
        self.assertTrue(all(r['reason'] for r in rows));self.assertIn('ストレス変化は適用なし',rows[1]['detail'])

    def test_caps_items_patron_and_saved_trouble_details(self):
        s=self.game(mode='patron');s.core.cats['cat-mike'].fatigue=95;s.core.management['stress']['cat-mike']=95
        rows={r['destination']['id']:r for r in comparison_rows(s,'cat-mike')}
        self.assertIn('疲労 95 → 100',rows['cat_photo_studio']['options'][0])
        self.assertIn('ストレス 95 → 100',rows['cat_photo_studio']['options'][0])
        self.assertIn('ケア用品',rows['neighborhood_visit']['detail'])
        self.assertIn('有力者満足度',rows['patron_visit']['detail'])
        lodge=rows['mountain_lodge_visit'];self.assertIn('家出トラブル',lodge['detail']);self.assertIn('中断報酬0',lodge['detail'])
        self.assertIn('中断帰還時ストレスは30に設定',lodge['detail']);self.assertIn('通常帰還の加算なし',lodge['detail'])
        self.assertIn('捜索費 100',lodge['detail']);self.assertIn('48.25%',lodge['detail'])
        self.assertIn('疲労20以下',lodge['reason']);self.assertIn('外出好き',lodge['detail'])


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class DispatchComparisonGuiTests(unittest.TestCase):
    setUp=DispatchComparisonTests.setUp
    game=DispatchComparisonTests.game
    unlock=DispatchComparisonTests.unlock

    def open(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game(white=True,service=True);owner=CafeActivityWindow(root,s,lambda:None,show_navigation=False)
        owner.cats.selection_set('cat-mike');owner.buttons();owner.compare_button.invoke()
        return root,s,owner,owner.comparison_window

    def test_minimum_size_detail_cancel_choose_confirmation_and_depart(self):
        root,s,owner,dialog=self.open();before=s.core.snapshot()
        dialog.window.geometry('560x400');root.update()
        dialog.table.selection_set('cat_photo_studio');dialog.show_detail()
        self.assertIn('報酬 490',dialog.details.get('1.0','end'))
        self.assertTrue(dialog.select_button.winfo_ismapped())
        self.assertLessEqual(dialog.select_button.winfo_rooty()+dialog.select_button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.close();self.assertEqual(s.core.snapshot(),before)
        owner.compare_button.invoke();dialog=owner.comparison_window;dialog.table.selection_set('cat_photo_studio');dialog.show_detail()
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:dialog.select_button.invoke()
        self.assertIn('猫の撮影スタジオ',confirm.call_args.args[1]);self.assertIn('報酬見込み 390',confirm.call_args.args[1])
        self.assertEqual(owner.rules['id'],'cat_photo_studio');self.assertEqual(owner.cats.selection(),('cat-mike',))
        self.assertEqual(s.core.snapshot(),before)
        owner.compare_button.invoke();dialog=owner.comparison_window;dialog.table.selection_set('cat_photo_studio');dialog.show_detail()
        with patch('tkinter.messagebox.askyesno',return_value=True):dialog.select_button.invoke()
        self.assertEqual(s.core.activity('cat-mike'),'dispatched')

    def test_disabled_destination_and_recheck_changed_state(self):
        root,s,owner,dialog=self.open()
        dialog.table.selection_set('quiet_reading_salon');dialog.show_detail()
        self.assertTrue(dialog.select_button.instate(['disabled']));self.assertIn('のんびり屋',dialog.details.get('1.0','end'))
        dialog.table.selection_set('cat_photo_studio');dialog.show_detail();self.assertTrue(dialog.select_button.instate(['!disabled']))
        s.core.cats['cat-mike'].fatigue=41
        with patch('tkinter.messagebox.askyesno',side_effect=AssertionError('should not confirm')):dialog.select()
        self.assertTrue(dialog.select_button.instate(['disabled']));self.assertIn('疲労',dialog.details.get('1.0','end'))
        dialog.close();owner.cats.selection_remove(*owner.cats.selection());owner.buttons()
        self.assertTrue(owner.compare_button.instate(['disabled']))


    def test_filter_sort_selection_stability_and_no_mutation(self):
        root,s,owner,dialog=self.open();before=s.core.snapshot();stored=s.store._read()
        original=dialog.table.get_children()
        dialog.table.selection_set('cat_photo_studio');dialog.show_detail()
        dialog.available_button.invoke();root.update()
        self.assertIn('cat_photo_studio',dialog.table.get_children());self.assertNotIn('quiet_reading_salon',dialog.table.get_children())
        self.assertEqual(dialog.table.selection(),('cat_photo_studio',))
        dialog.available_button.invoke();dialog.sort_choice.current(1);dialog.sort_choice.event_generate('<<ComboboxSelected>>');root.update()
        self.assertEqual(dialog.table.get_children()[0],'mountain_lodge_visit')
        self.assertEqual(dialog.table.selection(),('cat_photo_studio',))
        dialog.sort_choice.current(2);dialog.sort_choice.event_generate('<<ComboboxSelected>>');root.update()
        self.assertEqual(dialog.table.get_children()[0],'neighborhood_visit')
        twoday=[key for key in original if dialog.rows[key]['destination']['days']==2]
        self.assertEqual([key for key in dialog.table.get_children() if key in twoday],twoday)
        dialog.sort_choice.current(0);dialog.sort_choice.event_generate('<<ComboboxSelected>>');root.update()
        self.assertEqual(dialog.table.get_children(),original)
        self.assertEqual(s.core.snapshot(),before);self.assertEqual(s.store._read(),stored)
        dialog.close();owner.compare_button.invoke();dialog=owner.comparison_window
        self.assertFalse(dialog.available_only.get());self.assertEqual(dialog.sort_order.get(),'標準順')

    def test_filtered_empty_list_reason_restore_and_live_recheck(self):
        root,s,owner,dialog=self.open();dialog.window.geometry('560x400');root.update()
        dialog.available_button.invoke()
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            dialog.refresh();root.update()
            self.assertEqual(dialog.table.get_children(),());self.assertTrue(dialog.select_button.instate(['disabled']))
            self.assertEqual(dialog.details.get('1.0','end').strip(),'');self.assertIn('絞り込みを解除',dialog.notice.get())
            dialog.available_button.invoke();root.update()
            self.assertIn('保存',dialog.details.get('1.0','end'));self.assertTrue(dialog.select_button.instate(['disabled']))
        dialog.refresh();dialog.table.selection_set('cat_photo_studio');dialog.show_detail();dialog.available_button.invoke()
        s.core.cats['cat-mike'].fatigue=100
        with patch('tkinter.messagebox.askyesno',side_effect=AssertionError('must not confirm')):dialog.select()
        self.assertEqual(dialog.table.get_children(),());self.assertTrue(dialog.select_button.instate(['disabled']))
        self.assertTrue(dialog.available_button.winfo_ismapped());self.assertTrue(dialog.sort_choice.winfo_ismapped())
        self.assertLessEqual(dialog.close_button.winfo_rooty()+dialog.close_button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())

    def test_filtered_sorted_destination_uses_existing_confirmation(self):
        root,s,owner,dialog=self.open();before=s.core.snapshot()
        dialog.available_button.invoke();dialog.sort_order.set('報酬見込みが高い順');dialog.refresh()
        self.assertEqual(dialog.table.get_children()[0],'cat_photo_studio')
        dialog.table.selection_set('cat_photo_studio');dialog.show_detail()
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:dialog.select_button.invoke()
        self.assertIn('猫の撮影スタジオ',confirm.call_args.args[1]);self.assertEqual(owner.rules['id'],'cat_photo_studio')
        self.assertEqual(s.core.snapshot(),before)
