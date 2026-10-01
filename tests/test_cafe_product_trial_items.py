"""用品体験会の固定ケアセット報酬・使用売却・旧派遣の回帰。"""
import copy
import os
import unittest
from unittest.mock import patch
import test_cafe_product_trial_dispatch as fixtures
from cat_cafe_sim.core.cafe_items import inventory, for_destination
from cat_cafe_sim.core.cafe_dispatch_unlocks import trial_destination
from cat_cafe_sim.cafe_dispatch_results import result_rows
from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class ProductTrialItemTests(unittest.TestCase):
    setUp=fixtures.ProductTrialDispatchTests.setUp
    game=fixtures.ProductTrialDispatchTests.game
    unlock=fixtures.ProductTrialDispatchTests.unlock
    depart=fixtures.ProductTrialDispatchTests.depart
    reload_replay=fixtures.ProductTrialDispatchTests.reload_replay
    rejected=fixtures.ProductTrialDispatchTests.rejected

    def test_both_choices_receive_one_fixed_set_then_use_or_sell(self):
        for choice in ('accept','decline'):
            s,event_id=self.depart();event=s.core.activities['events'][event_id]
            item=copy.deepcopy(event['item_reward']);self.assertEqual(item['id'],'special_care_set')
            self.assertNotIn(event_id,inventory(s.core));self.rejected(s,lambda:s.use_item(event_id,'cat-mugi'))
            s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice(event_id,choice)
            self.assertNotIn(event_id,inventory(s.core));s=self.reload_replay(s);s.day_off()
            self.assertNotIn(event_id,inventory(s.core));funds=s.core.funds;s.resolve_activity(event_id)
            self.assertEqual(s.core.funds,funds+(400 if choice=='accept' else 300))
            self.assertEqual(inventory(s.core)[event_id],item)
            self.assertEqual(dict(result_rows(s.core,s.core.activities['events'][event_id]))['アイテム報酬'],'特製ケアセット ×1')
            before=s.core.snapshot();s.resolve_activity(event_id);self.assertEqual(s.core.snapshot(),before)
            s=self.reload_replay(s)
            if choice=='accept':
                s.use_item(event_id,'cat-mugi')
                self.assertEqual(s.core.cats['cat-mugi'].fatigue,0);self.assertEqual(s.core.management['stress']['cat-mugi'],0)
                self.rejected(s,lambda:s.sell_item(event_id));self.rejected(s,lambda:s.use_item(event_id,'cat-mugi'))
            else:
                funds=s.core.funds;s.sell_item(event_id);self.assertEqual(s.core.funds,funds+100)
                self.rejected(s,lambda:s.sell_item(event_id));self.rejected(s,lambda:s.use_item(event_id,'cat-mugi'))
            self.assertNotIn(event_id,inventory(s.core));self.reload_replay(s)

    def test_saved_reward_and_return_save_retry_do_not_duplicate(self):
        s,event_id=self.depart();item=copy.deepcopy(s.core.activities['events'][event_id]['item_reward'])
        with patch('cat_cafe_sim.core.cafe_items.for_destination',side_effect=AssertionError('settings changed')):
            s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice(event_id,'accept');s.day_off()
            s.resolve_activity(event_id);funds=s.core.funds
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
            s=self.reload_replay(s);s.resolve_activity(event_id)
            self.assertEqual(s.core.funds,funds);self.assertEqual(inventory(s.core)[event_id],item)
            self.assertEqual(sum(v['id']=='special_care_set' for v in inventory(s.core).values()),1)
            self.reload_replay(s)

    def test_departed_trip_without_item_kept_and_only_trial_added(self):
        s=self.unlock(self.game())
        original=for_destination
        with patch('cat_cafe_sim.core.cafe_items.for_destination',side_effect=lambda d:None if d['id']=='cat_product_trial' else original(d)):
            s.dispatch('cat-mugi',trial_destination(s.core))
        event_id='dispatch-2-cat-mugi';s=self.reload_replay(s)
        self.assertNotIn('item_reward',s.core.activities['events'][event_id])
        s.day_off();s.resolve_dispatch_choice(event_id,'accept');s.day_off();s.resolve_activity(event_id)
        self.assertNotIn(event_id,inventory(s.core));self.reload_replay(s)
        from cat_cafe_sim.core.cafe_activities import destinations
        s=self.game()
        self.assertEqual([r['id'] for r in destinations(s.core) if for_destination(r)],['neighborhood_visit','cat_product_trial'])
        old=self.game(legacy=True);self.assertNotIn('cat_product_trial',[r['id'] for r in destinations(old.core)])
        self.reload_replay(old)

    def test_comparison_has_reward_and_reading_does_not_mutate(self):
        s=self.unlock(self.game());before=s.core.snapshot()
        row=next(r for r in comparison_rows(s,'cat-mugi') if r['destination']['id']=='cat_product_trial')
        self.assertIn('アイテム報酬：特製ケアセット ×1',row['detail'])
        self.assertIn('疲労 −10 / ストレス −10',row['detail']);self.assertEqual(s.core.snapshot(),before)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class ProductTrialItemWindowTests(unittest.TestCase):
    setUp=ProductTrialItemTests.setUp
    game=ProductTrialItemTests.game
    unlock=ProductTrialItemTests.unlock

    def test_confirmation_return_and_inventory_show_set(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.unlock(self.game());app=CafeInteractionWindow(root,s);app.activity_button.invoke();w=app.activity_window
        w.destination_choice.current(next(i for i,r in enumerate(w.destinations) if r['id']=='cat_product_trial'));w.select_destination()
        w.cats.selection_set('cat-mugi');w.buttons()
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.send_button.invoke()
        self.assertIn('特製ケアセット',ask.call_args.args[1])
        with patch('tkinter.messagebox.askyesno',return_value=True):w.send_button.invoke()
        event_id='dispatch-2-cat-mugi';s.day_off();s.resolve_dispatch_choice(event_id,'accept');s.day_off()
        w.refresh();w.events.selection_set(event_id);w.buttons();w.receive_button.invoke();w.result_button.invoke();root.update()
        self.assertIn('アイテム報酬：特製ケアセット ×1',w.result_text.get('1.0','end'))
        w.window.destroy();items=CafeItemsWindow(root,s,lambda:None);items.items.selection_set(event_id);items.cats.selection_set('cat-mugi');items.selection_changed()
        self.assertIn('特製ケアセット',items.items.item(event_id)['values']);self.assertFalse(items.use_button.instate(['disabled']))
        self.assertFalse(items.sell_button.instate(['disabled']))
