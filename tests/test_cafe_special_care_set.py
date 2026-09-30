"""疲労・ストレスの同時回復と単独用品の保存互換。"""
import copy
import os
import unittest
from unittest.mock import patch, PropertyMock

import test_cafe_traits as fixtures
from cat_cafe_sim.core.cafe_items import definition, inventory, unavailable_reason
from cat_cafe_sim.core.cafe_item_shop import catalog
from cat_cafe_sim.core.cafe_item_sales import prices
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game
from cat_cafe_sim.cafe_shift_forecast import shift_forecast


class SpecialCareSetTests(unittest.TestCase):
    setUp=fixtures.TraitTests.setUp
    session=fixtures.TraitTests.session
    close=fixtures.TraitTests.close
    reload=fixtures.TraitTests.reload

    def selected(self):
        return next(row for row in catalog() if row['item']['id']=='special_care_set')

    def prepared(self, assigned=None, management=True, fatigue=32):
        s=self.session(assigned,fatigue=fatigue,management=management)
        self.close(s);s.next_day()
        return s

    def replay(self,s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def reject(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(s.core.log(),before)

    def test_fixed_dual_recovery_traits_forecast_and_actual_work(self):
        for trait_id,before in (('hardy',24),('relaxed',40),('hospitality',40)):
            s=self.prepared({'a':trait_id})
            stamina=s.core.cats['a'].stamina;funds=s.core.funds;stress=s.core.management['stress']['a']
            s.purchase_item(self.selected());s.use_item('item-purchase-1','a')
            row=s.core.item_uses[-1]
            self.assertEqual(row['before'],dict(fatigue=before,stress=stress))
            self.assertEqual(row['after'],dict(fatigue=before-10,stress=0))
            self.assertEqual(s.core.funds,funds-200)
            self.assertEqual(s.core.cats['a'].stamina,stamina)
            self.assertEqual(s.core.initial_fatigue['a'],before-10)
            forecast=shift_forecast(s.core,'a')['work']['fatigue']
            s=self.reload(s);self.replay(s);self.close(s)
            self.assertEqual(s.core.cats['a'].fatigue,forecast)
            self.assertEqual(s.core.summary()['item_expenses'],200)
            s.next_day();self.assertEqual(s.core.day_results[-1]['summary']['item_expenses'],200)
            self.reload(s);self.replay(s)

    def test_partial_one_zero_and_both_zero_preserve_inventory(self):
        s=self.prepared(fatigue=3)
        for _ in range(2):s.purchase_item(self.selected())
        s.use_item('item-purchase-1','a')
        self.assertEqual(s.core.item_uses[-1]['after'],dict(fatigue=0,stress=0))
        self.reject(s,lambda:s.use_item('item-purchase-2','a'))
        self.assertIn('item-purchase-2',inventory(s.core))
        self.reload(s);self.replay(s)
        s=self.prepared()
        for _ in range(2):s.purchase_item(self.selected())
        s.use_item('item-purchase-1','a');s.use_item('item-purchase-2','a')
        self.assertEqual(s.core.item_uses[-1]['before'],dict(fatigue=22,stress=0))
        self.assertEqual(s.core.cats['a'].fatigue,12)
        self.reload(s);self.replay(s)
        s=self.prepared(fatigue=0);s.purchase_item(self.selected());s.use_item('item-purchase-1','a')
        self.assertEqual(s.core.item_uses[-1]['before'],dict(fatigue=0,stress=1))
        self.reload(s);self.replay(s)

    def test_rest_day_uses_recovered_fatigue_and_records_expense(self):
        s=self.prepared();s.purchase_item(self.selected());s.use_item('item-purchase-1','a')
        self.assertEqual(shift_forecast(s.core,'a')['rest']['fatigue'],2)
        s.day_off();self.assertEqual(s.core.cats['a'].fatigue,2)
        self.assertEqual(s.core.day_results[-1]['summary']['item_expenses'],200)
        self.reload(s);self.replay(s)

    def test_rule_requirements_absent_cats_pending_and_sickness(self):
        s=self.prepared(management=False);s.purchase_item(self.selected())
        self.reject(s,lambda:s.use_item('item-purchase-1','a'))
        s.sell_item('item-purchase-1');self.assertEqual(s.core.summary()['item_sales_income'],100)
        self.reload(s);self.replay(s)
        s=self.prepared();s.purchase_item(self.selected())
        for activity in ('dispatched','missing','adopted'):
            core=copy.deepcopy(s.core)
            from cat_cafe_sim.core.cafe_activities import ensure
            ensure(core);core.activities['cats']['a']=activity
            self.assertIn('在店',unavailable_reason(core,'item-purchase-1','a'))
        core=copy.deepcopy(s.core);core.shift_rules=None
        self.assertIn('出勤ルール',unavailable_reason(core,'item-purchase-1','a'))
        core=copy.deepcopy(s.core);core.cats['a'].health_status='sick';core.cats['a'].recovery_days_remaining=2
        core.use_item('item-purchase-1','a')
        self.assertEqual(core.cats['a'].health_status,'sick')
        self.assertEqual(core.cats['a'].recovery_days_remaining,2)
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            self.reject(s,lambda:s.use_item('item-purchase-1','a'))
            self.reject(s,lambda:s.purchase_item(self.selected()))
        s.play_with_player('a');self.reject(s,lambda:s.use_item('item-purchase-1','a'))
        s.player_command(finish=True);s.automatic_step()
        self.reject(s,lambda:s.use_item('item-purchase-1','a'))

    def test_purchase_funds_boundary_and_game_over(self):
        s=self.prepared();s.core.funds=199
        self.reject(s,lambda:s.purchase_item(self.selected()))
        s.core.funds=200;s.purchase_item(self.selected())
        self.assertEqual(s.core.funds,0)
        self.assertEqual(s.core.management['game_over']['reason'],'funds')
        self.reject(s,lambda:s.use_item('item-purchase-1','a'))
        self.reject(s,lambda:s.sell_item('item-purchase-1'))

    def test_sell_unconsumed_set_and_mixed_old_items_keep_shapes(self):
        s=self.prepared();s.purchase_item();s.purchase_item(catalog()[1])
        for _ in range(2):s.purchase_item(self.selected())
        s.use_item('item-purchase-1','a');s.use_item('item-purchase-2','a')
        self.assertIsInstance(s.core.item_uses[0]['before'],(int,float))
        self.assertIsInstance(s.core.item_uses[1]['before'],(int,float))
        s.use_item('item-purchase-3','a')
        self.reject(s,lambda:s.sell_item('item-purchase-3'))
        funds=s.core.funds;s.sell_item('item-purchase-4')
        self.assertEqual(s.core.funds,funds+100)
        self.assertEqual(s.core.summary()['item_sales_income'],100)
        self.reject(s,lambda:s.use_item('item-purchase-4','a'))
        self.reject(s,lambda:s.sell_item('item-purchase-4'))
        self.assertEqual(prices()['special_care_set'],100)
        s=self.reload(s);s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['item_sales_income'],100)
        self.reload(s);self.replay(s)

    def test_save_failure_retry_and_purchase_effects_remain_frozen(self):
        s=self.prepared();selected=self.selected();selected['item'].update(fatigue_relief=7,stress_relief=3)
        s.purchase_item(selected);s.use_item('item-purchase-1','a')
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,self.path)
        with patch('cat_cafe_sim.core.cafe_item_shop.catalog',side_effect=AssertionError('changed')):
            s=self.reload(s);self.replay(s)
        self.assertEqual(s.core.cats['a'].fatigue,25)
        self.assertEqual(s.core.management['stress']['a'],0)
        self.reject(s,lambda:s.use_item('item-purchase-1','a'))
        self.assertEqual(len(s.core.item_uses),1)

    def test_invalid_definition_and_dual_use_records_rejected(self):
        item=self.selected()['item']
        for change in (dict(fatigue_relief=True),dict(stress_relief=0),dict(stress_relief=float('nan')),dict(extra=1)):
            with self.assertRaises(ValueError):definition(dict(item,**change))
        s=self.prepared();s.purchase_item(self.selected());s.use_item('item-purchase-1','a')
        source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['item_uses'][0].update(after=0),
                       lambda d:d['state']['item_uses'][0]['after'].pop('stress'),
                       lambda d:d['state']['item_uses'][0]['after'].update(fatigue=23),
                       lambda d:d['state']['item_uses'][0]['before'].update(stress=True),
                       lambda d:d['state']['item_uses'][0].update(before=dict(fatigue=0,stress=0)),
                       lambda d:d['state']['item_uses'].append(copy.deepcopy(d['state']['item_uses'][0]))):
            bad=copy.deepcopy(source);mutate(bad)
            bad['digest']=digest({key:value for key,value in bad.items() if key!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires desktop')
class SpecialCareSetGuiTests(unittest.TestCase):
    setUp=fixtures.TraitTests.setUp
    session=fixtures.TraitTests.session
    close=fixtures.TraitTests.close
    prepared=SpecialCareSetTests.prepared
    selected=SpecialCareSetTests.selected

    def test_purchase_use_sell_cancel_history_and_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_cat_events import cat_events
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.prepared();app=CafeInteractionWindow(root,s)
        window=CafeItemsWindow(root,s,app.refresh)
        index=next(i for i,row in enumerate(window.shop_catalog) if row['item']['id']=='special_care_set')
        window.shop_choice.current(index);window.select_shop();window.window.geometry('580x460');root.update()
        self.assertIn('1個 200',window.shop_note.get())
        self.assertIn('疲労 −10 / ストレス −10',window.shop_note.get())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.buy_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):window.buy_button.invoke();window.buy_button.invoke()
        window.cats.selection_set('a');window.selection_changed()
        self.assertIn('疲労 32 → 22 / ストレス 1 → 0',window.notice.get())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.use_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):window.use_button.invoke()
        self.assertIn('疲労 32 → 22 / ストレス 1 → 0',window.result.get())
        self.assertIn('ストレス 1 → 0',str([window.history.item(key)['values'] for key in window.history.get_children()]))
        self.assertTrue(any('疲労 32 → 22 / ストレス 1 → 0' in str(app.history.item(key)['values']) for key in app.history.get_children()))
        self.assertIn('特製ケアセットの使用',str(cat_events(s.core,'a')))
        self.assertIn('100',window.sale_notice.get())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.sell_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):window.sell_button.invoke()
        self.assertEqual(len(window.sale_history.get_children()),1)
        for button in (window.buy_button,window.use_button,window.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),window.window.winfo_rootx()+window.window.winfo_width())
        # Equal names with different effects remain separate inventory rows.
        s.purchase_item(self.selected());custom=self.selected();custom['item']['stress_relief']=15;s.purchase_item(custom)
        window.refresh();self.assertEqual(len(window.items.get_children()),2)
