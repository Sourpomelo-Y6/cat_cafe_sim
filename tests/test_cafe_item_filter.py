"""用品の使用対象絞り込みと確認表示のGUI回帰。"""
import os
import unittest
from unittest.mock import patch, PropertyMock
import test_cafe_item_sales as fixtures
from cat_cafe_sim.core.cafe_item_shop import catalog
from cat_cafe_sim.core.cafe_items import unavailable_reason


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class ItemFilterTests(unittest.TestCase):
    setUp=fixtures.ItemSalesTests.setUp
    game=fixtures.ItemSalesTests.game
    session=fixtures.ItemSalesTests.session
    reload=fixtures.ItemSalesTests.reload
    received=fixtures.ItemSalesTests.received
    dispatch=fixtures.ItemSalesTests.dispatch

    def window(self,s):
        import tkinter as tk
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        return root,CafeItemsWindow(root,s,lambda:None)

    def test_three_items_switch_selection_without_state_changes(self):
        s=self.game();keys=list(s.core.cats)
        for item in catalog():s.purchase_item(item)
        for key in keys:
            s.core.management['stress'][key]=0;s.core.cats[key].fatigue=0
        s.core.management['stress'][keys[0]]=7;s.core.cats[keys[1]].fatigue=12
        root,w=self.window(s);root.update();before=s.core.snapshot();stored=s.store._read()
        w.cats.selection_set(keys[1]);w.selection_changed();w.usable_only_button.invoke();root.update()
        self.assertEqual(w.cats.get_children(),(keys[0],));self.assertEqual(w.cats.selection(),(keys[0],))
        w.items.selection_set('item-purchase-2');root.update()
        self.assertEqual(w.cats.get_children(),(keys[1],));self.assertEqual(w.cats.selection(),(keys[1],))
        w.items.selection_set('item-purchase-3');root.update()
        self.assertEqual(w.cats.get_children(),tuple(keys[:2]));self.assertEqual(w.cats.selection(),(keys[1],))
        self.assertIn('疲労 12 → 2',w.notice.get());self.assertIn('ストレス 0 → 0',w.notice.get())
        w.usable_only_button.invoke();root.update();self.assertEqual(w.cats.get_children(),tuple(keys))
        self.assertEqual(w.cats.selection(),(keys[1],));self.assertEqual(s.core.snapshot(),before);self.assertEqual(s.store._read(),stored)

    def test_confirmation_cancel_use_group_consumption_and_sale(self):
        s=self.game();keys=list(s.core.cats);s.purchase_item();s.purchase_item()
        for key in keys:s.core.management['stress'][key]=0
        s.core.management['stress'][keys[0]]=7;s.core.management['stress'][keys[1]]=20
        root,w=self.window(s);w.usable_only_button.invoke();root.update();before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.use_button.invoke()
        self.assertIn('ストレス 7 → 0',ask.call_args.args[1]);self.assertIn(s.profiles[keys[0]]['name'],ask.call_args.args[1])
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.use_button.invoke()
        root.update();self.assertEqual(len(s.core.item_uses),1)
        self.assertEqual(w.items.selection(),('item-purchase-2',));self.assertEqual(w.cats.get_children(),(keys[1],))
        self.assertEqual(w.cats.selection(),(keys[1],));self.assertFalse(w.use_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno',return_value=True):w.sell_button.invoke()
        root.update();self.assertEqual(w.items.get_children(),());self.assertEqual(w.cats.get_children(),())
        self.assertIn('所持品はありません',w.notice.get());self.assertTrue(w.use_button.instate(['disabled']))

    def test_empty_explanation_layout_and_purchase_with_filter(self):
        s=self.game();root,w=self.window(s);w.window.geometry('580x460');w.usable_only_button.invoke();root.update()
        self.assertEqual(w.cats.get_children(),());self.assertIn('所持品はありません',w.notice.get())
        with patch('tkinter.messagebox.askyesno',return_value=True):w.buy_button.invoke()
        root.update();self.assertEqual(w.cats.get_children(),());self.assertIn('使える猫はいません',w.notice.get())
        self.assertIn('0です',w.notice.get());self.assertIn('解除',w.notice.get())
        self.assertFalse(w.sell_button.instate(['disabled']));self.assertTrue(w.use_button.instate(['disabled']))
        self.assertGreater(w.items.winfo_height(),15);self.assertGreater(w.cats.winfo_height(),15)
        for widget in (w.usable_only_button,w.buy_button,w.use_button,w.sell_button,w.close_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),w.window.winfo_rootx()+w.window.winfo_width())
        w.usable_only_button.invoke();self.assertEqual(w.cats.get_children(),tuple(s.core.cats))
        self.assertIn('0です',w.notice.get())

    def test_dispatch_pending_and_operating_follow_existing_rules(self):
        s=self.session();source,key=self.received(s);s.dispatch(key)
        root,w=self.window(s);w.usable_only_button.invoke();root.update()
        self.assertNotIn(key,w.cats.get_children())
        self.assertEqual(w.cats.get_children(),tuple(k for k in s.core.cats if not unavailable_reason(s.core,source,k)))
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            w.selection_changed();root.update();self.assertEqual(w.cats.get_children(),())
            self.assertIn('保存を再試行',w.notice.get());self.assertTrue(w.use_button.instate(['disabled']))
        w.selection_changed();s.step();w.refresh();root.update()
        self.assertEqual(w.cats.get_children(),());self.assertIn('営業準備中',w.notice.get())

    def test_old_save_no_management_and_reopen_resets_filter(self):
        s=self.session(management=False);self.received(s);s=self.reload(s)
        before=s.core.snapshot();root,w=self.window(s);w.usable_only_button.invoke();root.update()
        self.assertEqual(w.cats.get_children(),());self.assertIn('経営ルール',w.notice.get())
        self.assertEqual(s.core.snapshot(),before);w.window.destroy()
        root,w=self.window(s);root.update();self.assertFalse(w.usable_only.get())
        self.assertEqual(w.cats.get_children(),tuple(s.core.cats));self.assertTrue(w.use_button.instate(['disabled']))

    def test_use_rechecks_before_confirmation(self):
        s=self.game();s.purchase_item();key=next(iter(s.core.cats));s.core.management['stress'][key]=7
        root,w=self.window(s);w.usable_only_button.invoke();root.update()
        s.core.management['stress'][key]=0;before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno') as ask:w.use_button.invoke()
        ask.assert_not_called();self.assertEqual(s.core.snapshot(),before);self.assertEqual(w.cats.get_children(),())
