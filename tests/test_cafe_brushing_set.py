"""美術館の固定ブラッシングセット報酬・ストレス回復・売却互換。"""
import copy
import os
import unittest
from unittest.mock import patch
import test_cafe_museum_dispatch as fixtures
from cat_cafe_sim.core.cafe_items import inventory, for_destination, definition, unavailable_reason
from cat_cafe_sim.core.cafe_item_sales import prices
from cat_cafe_sim.core.cafe_dispatch_unlocks import museum_destination
from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
from cat_cafe_sim.cafe_dispatch_results import result_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class BrushingSetTests(unittest.TestCase):
    setUp=fixtures.MuseumDispatchTests.setUp
    game=fixtures.MuseumDispatchTests.game
    close=fixtures.MuseumDispatchTests.close
    unlock=fixtures.MuseumDispatchTests.unlock
    depart=fixtures.MuseumDispatchTests.depart
    reload_replay=fixtures.MuseumDispatchTests.reload_replay
    rejected=fixtures.MuseumDispatchTests.rejected

    def receive(self,choice='accept'):
        s,key=self.depart();s.day_off();s.resolve_dispatch_choice(key,choice);s.day_off();s.resolve_activity(key)
        return s,key

    def test_both_choices_one_reward_use_stress_only_and_no_duplicate(self):
        for choice in ('accept','decline'):
            s,key=self.depart();item=copy.deepcopy(s.core.activities['events'][key]['item_reward'])
            self.assertEqual(item,dict(id='brushing_set',name='ブラッシングセット',stress_relief=20))
            self.assertNotIn(key,inventory(s.core));self.rejected(s,lambda:s.use_item(key,'cat-mugi'))
            s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice(key,choice)
            self.assertNotIn(key,inventory(s.core));s=self.reload_replay(s);s.day_off()
            self.assertNotIn(key,inventory(s.core));funds=s.core.funds;s.resolve_activity(key)
            self.assertEqual(s.core.funds,funds+(450 if choice=='accept' else 350))
            self.assertEqual(inventory(s.core)[key],item)
            self.assertEqual(dict(result_rows(s.core,s.core.activities['events'][key]))['アイテム報酬'],'ブラッシングセット ×1')
            before=s.core.snapshot();s.resolve_activity(key);self.assertEqual(s.core.snapshot(),before)
            s=self.reload_replay(s)
            if choice=='accept':
                fatigue=s.core.cats['cat-mugi'].fatigue;health=s.core.cats['cat-mugi'].health_status
                stamina=s.core.cats['cat-mugi'].stamina
                self.assertEqual(s.core.management['stress']['cat-mugi'],10)
                s.use_item(key,'cat-mugi');self.assertEqual(s.core.management['stress']['cat-mugi'],0)
                self.assertEqual(s.core.cats['cat-mugi'].fatigue,fatigue);self.assertEqual(s.core.cats['cat-mugi'].health_status,health)
                self.assertEqual(s.core.cats['cat-mugi'].stamina,stamina)
                self.rejected(s,lambda:s.use_item(key,'cat-mugi'));self.rejected(s,lambda:s.sell_item(key))
            else:
                self.rejected(s,lambda:s.use_item(key,'cat-mugi'),'0')
                self.assertIn(key,inventory(s.core));funds=s.core.funds;s.sell_item(key)
                self.assertEqual(s.core.funds,funds+100);self.assertEqual(s.core.summary()['item_sales_income'],100)
                self.rejected(s,lambda:s.sell_item(key));self.rejected(s,lambda:s.use_item(key,'cat-mugi'))
            self.assertNotIn(key,inventory(s.core));self.reload_replay(s)

    def test_fixed_twenty_relief_absent_management_and_invalid_definition(self):
        s,key=self.receive();core=copy.deepcopy(s.core);core.management['stress']['cat-mugi']=35
        fatigue=core.cats['cat-mugi'].fatigue;core.use_item(key,'cat-mugi')
        self.assertEqual(core.management['stress']['cat-mugi'],15);self.assertEqual(core.cats['cat-mugi'].fatigue,fatigue)
        core=copy.deepcopy(s.core);core.activities['cats']['cat-mugi']='missing'
        self.assertIn('在店',unavailable_reason(core,key,'cat-mugi'))
        core=copy.deepcopy(s.core);core.management=None
        self.assertIn('経営ルール',unavailable_reason(core,key,'cat-mugi'))
        self.assertEqual(prices()['brushing_set'],100)
        for effect in (True,0,-1,101,float('nan')):
            with self.assertRaises(ValueError):definition(dict(id='brushing_set',name='セット',stress_relief=effect))
        with self.assertRaises(ValueError):definition(dict(id='brushing_set',name='セット',stress_relief=20,fatigue_relief=10))

    def test_fixed_reward_save_failure_and_repeat_use_or_sale(self):
        for selling in (True,False):
            s,key=self.depart();item=copy.deepcopy(s.core.activities['events'][key]['item_reward'])
            with patch('cat_cafe_sim.core.cafe_items.for_destination',side_effect=AssertionError('changed')):
                s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice(key,'accept');s.day_off();s.resolve_activity(key)
                with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                    with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
                s=self.reload_replay(s);before=s.core.snapshot();s.resolve_activity(key);self.assertEqual(s.core.snapshot(),before)
                self.assertEqual(inventory(s.core)[key],item)
                if selling:s.sell_item(key)
                else:s.use_item(key,'cat-mugi')
                with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                    with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
                s=self.reload_replay(s);self.assertNotIn(key,inventory(s.core))
                self.rejected(s,lambda:s.sell_item(key));self.rejected(s,lambda:s.use_item(key,'cat-mugi'))
                self.reload_replay(s)

    def test_old_departed_without_reward_kept_other_rewards_and_preview(self):
        s=self.unlock(self.game());original=for_destination
        with patch('cat_cafe_sim.core.cafe_items.for_destination',side_effect=lambda d:None if d['id']=='small_art_museum' else original(d)):
            s.dispatch('cat-mugi',museum_destination(s.core))
        key='dispatch-3-cat-mugi';s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice(key,'accept');s.day_off();s.resolve_activity(key)
        self.assertNotIn('item_reward',s.core.activities['events'][key]);self.assertNotIn(key,inventory(s.core));self.reload_replay(s)
        s=self.unlock(self.game());before=s.core.snapshot()
        row=next(r for r in comparison_rows(s,'cat-mugi') if r['destination']['id']=='small_art_museum')
        self.assertIn('ブラッシングセット ×1',row['detail']);self.assertIn('ストレス −20',row['detail'])
        self.assertEqual(s.core.snapshot(),before)
        from cat_cafe_sim.core.cafe_activities import destinations
        self.assertEqual({r['id']:for_destination(r)['id'] for r in destinations(s.core) if for_destination(r)},
                         dict(neighborhood_visit='care_supplies',cat_product_trial='special_care_set',small_art_museum='brushing_set'))


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires display')
class BrushingSetGuiTests(unittest.TestCase):
    setUp=BrushingSetTests.setUp
    game=BrushingSetTests.game
    close=BrushingSetTests.close
    unlock=BrushingSetTests.unlock

    def test_confirmation_return_inventory_effect_and_sale_buttons(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.unlock(self.game());app=CafeInteractionWindow(root,s);app.activity_button.invoke();w=app.activity_window
        w.destination_choice.current(next(i for i,r in enumerate(w.destinations) if r['id']=='small_art_museum'));w.select_destination()
        w.cats.selection_set('cat-mugi');w.buttons()
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.send_button.invoke()
        self.assertIn('ブラッシングセット',ask.call_args.args[1]);self.assertIn('ストレス −20',ask.call_args.args[1])
        with patch('tkinter.messagebox.askyesno',return_value=True):w.send_button.invoke()
        key='dispatch-3-cat-mugi';s.day_off();s.resolve_dispatch_choice(key,'accept');s.day_off()
        w.refresh();w.events.selection_set(key);w.buttons();w.receive_button.invoke();w.result_button.invoke()
        self.assertIn('アイテム報酬：ブラッシングセット ×1',w.result_text.get('1.0','end'))
        w.window.destroy();items=CafeItemsWindow(root,s,lambda:None);items.window.geometry('560x400')
        items.items.selection_set(key);items.cats.selection_set('cat-mugi');items.selection_changed();root.update()
        self.assertIn('ブラッシングセット',items.items.item(key)['values'])
        self.assertFalse(items.use_button.instate(['disabled']));self.assertFalse(items.sell_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno',return_value=True):items.use_button.invoke()
        self.assertEqual(s.core.management['stress']['cat-mugi'],0)
        self.assertNotIn(key,inventory(s.core))
