"""未使用品の売却、独立した収入と二重消費防止。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

import test_cafe_items as fixtures
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_items import inventory
from cat_cafe_sim.core.cafe_item_shop import catalog
from cat_cafe_sim.core.cafe_item_sales import prices
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game


class ItemSalesTests(unittest.TestCase):
    setUp = fixtures.ItemTests.setUp
    session = fixtures.ItemTests.session
    received = fixtures.ItemTests.received
    dispatch = fixtures.ItemTests.dispatch
    reload = fixtures.ItemTests.reload
    rejected = fixtures.ItemTests.rejected

    def replay(self, s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def game(self):
        selected = starting_conditions('free')
        for key in ('intake_request','regular_introduction','store_events','growth'):
            selected.pop(key)
        return create_game(Path(self.temp.name) / 'games', selected)

    def test_both_purchase_types_sell_once_without_cat_changes(self):
        for seats in (1, 2):
            s = self.session(seats)
            s.purchase_item(); s.purchase_item(catalog()[1])
            cats = copy.deepcopy(s.core.snapshot()['cats'])
            funds = s.core.funds
            s.sell_item('item-purchase-1'); s.sell_item('item-purchase-2')
            self.assertEqual(s.core.funds, funds + 125)
            self.assertEqual(s.core.summary()['item_sales_income'], 125)
            self.assertEqual(inventory(s.core), {})
            self.assertEqual(s.core.snapshot()['cats'], cats)
            self.assertEqual([row['price'] for row in s.core.item_sales], [50, 75])
            self.rejected(s, lambda: s.sell_item('item-purchase-1'))
            self.rejected(s, lambda: s.use_item('item-purchase-1', next(iter(s.core.cats))))
            self.reload(s); self.replay(s)

    def test_dispatch_reward_unreceived_and_received_sale(self):
        s = self.session(); source, key = self.dispatch(s)
        self.rejected(s, lambda: s.sell_item(source))
        s.day_off()
        self.rejected(s, lambda: s.sell_item(source))
        s.resolve_activity(source)
        funds = s.core.funds; s.sell_item(source)
        self.assertEqual(s.core.funds, funds + 50)
        before = s.core.snapshot(); s.resolve_activity(source)
        self.assertEqual(s.core.snapshot(), before)
        self.assertNotIn(source, inventory(s.core))
        self.reload(s); self.replay(s)

    def test_store_event_reward_sale_and_pending_event_restriction(self):
        selected = starting_conditions('free')
        for key in ('intake_request', 'regular_introduction', 'growth'):
            selected.pop(key)
        selected['store_events']['probability'] = 1
        s = create_game(Path(self.temp.name) / 'store-games', selected)
        s.purchase_item(); s.day_off()
        self.rejected(s, lambda: s.sell_item('item-purchase-1'))
        s.resolve_store_event('decline'); s.day_off()
        self.assertIn('store-event-3', inventory(s.core))
        funds = s.core.funds; s.sell_item('store-event-3')
        self.assertEqual(s.core.funds, funds + 50)
        self.assertIn('item-purchase-1', inventory(s.core))
        self.reload(s); self.replay(s)

    def test_used_items_cannot_be_sold_and_sale_requires_no_cat_target(self):
        s = self.session(); source, key = self.received(s)
        s.use_item(source, key)
        self.rejected(s, lambda: s.sell_item(source))
        s.purchase_item()
        # ストレス0でも、売却には猫の状態や対象選択が不要。
        self.assertEqual(s.core.management['stress'][key], 0)
        s.sell_item('item-purchase-1')
        self.reload(s); self.replay(s)

    def test_operating_day_rest_day_income_and_funds_continuity(self):
        for rest_day in (False, True):
            s = self.game(); funds = s.core.funds
            s.purchase_item(); s.purchase_item(catalog()[1])
            s.sell_item('item-purchase-1'); s.sell_item('item-purchase-2')
            if rest_day:
                s.day_off()
            else:
                while not s.core.closed: s.automatic_step()
                s.next_day()
            summary = s.core.day_results[-1]['summary']
            self.assertEqual(summary['item_sales_income'], 125)
            self.assertEqual(summary['item_expenses'], 250)
            self.assertEqual(summary['total_income'], summary['revenue'] + summary.get('dispatch_income', 0) + 125)
            self.assertEqual(summary['opening_funds'], funds)
            self.assertEqual(summary['closing_funds'], funds + summary['net_cash_flow'])
            s = self.reload(s); self.replay(s)
            s.day_off()
            self.assertEqual(s.core.day_results[-1]['summary']['item_sales_income'], 0)
            self.reload(s); self.replay(s)

    def test_pending_and_business_game_over_restrictions(self):
        s = self.session(); s.purchase_item()
        with patch.object(type(s), 'pending', new_callable=PropertyMock, return_value={'pending'}):
            self.rejected(s, lambda: s.sell_item('item-purchase-1'))
        s.step(); self.rejected(s, lambda: s.sell_item('item-purchase-1'))
        while not s.core.closed: s.automatic_step()
        self.rejected(s, lambda: s.sell_item('item-purchase-1'))
        s.next_day(); s.core.funds = 100; s.purchase_item()
        self.rejected(s, lambda: s.sell_item('item-purchase-1'))
        self.assertEqual(s.core.management['game_over']['reason'], 'funds')

    def test_old_save_has_no_sale_records_until_explicit_sale(self):
        s = self.session(management=False); source, _ = self.received(s)
        s = self.reload(s)
        self.assertNotIn('item_sales', s.core.snapshot())
        self.assertNotIn('item_sales_income', s.core.summary())
        self.assertEqual(len(inventory(s.core)), 1)
        s.sell_item(source)
        self.assertEqual(s.core.item_sales[0]['price'], 50)
        self.reload(s); self.replay(s)

    def test_save_failure_and_fixed_price_replay(self):
        s = self.session(); s.purchase_item(catalog()[1]); funds = s.core.funds
        s.sell_item('item-purchase-1')
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, self.path)
        with patch('cat_cafe_sim.core.cafe_item_sales.prices', side_effect=AssertionError('settings changed')):
            s = self.reload(s); self.replay(s)
        self.assertEqual(s.core.funds, funds + 75)
        self.rejected(s, lambda: s.sell_item('item-purchase-1'))
        self.assertEqual(s.core.funds, funds + 75)

    def test_invalid_price_records_double_consumption_and_daily_income_rejected(self):
        s = self.game(); s.purchase_item(); s.sell_item('item-purchase-1'); s.day_off()
        source = checkpoint(s.core, set())
        for mutate in (lambda d: d['state']['item_sales'][0].update(price=-1),
                       lambda d: d['state']['item_sales'][0].update(day=0),
                       lambda d: d['state']['item_sales'][0].update(source='unknown'),
                       lambda d: d['state']['item_sales'].append(copy.deepcopy(d['state']['item_sales'][0])),
                       lambda d: d['state']['day_results'][0]['summary'].update(item_sales_income=0)):
            bad = copy.deepcopy(source); mutate(bad)
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError): restore(bad)
        s = self.session(); source, key = self.received(s)
        s.use_item(source, key); s.purchase_item(); s.sell_item('item-purchase-1')
        bad = checkpoint(s.core, set()); bad['state']['item_sales'][0]['source'] = source
        bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
        with self.assertRaises(ValueError): restore(bad)
        with patch('cat_cafe_sim.core.cafe_item_sales.json.loads', return_value={'care_supplies':True,'nutrition_snack':75}):
            with self.assertRaises(ValueError): prices()


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
class ItemSalesWindowTests(unittest.TestCase):
    setUp = fixtures.ItemTests.setUp
    game = ItemSalesTests.game

    def test_grouped_sale_cancel_price_history_finance_and_small_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_history import CafeHistoryWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game(); s.purchase_item(); s.purchase_item(); s.purchase_item(catalog()[1])
        app = CafeInteractionWindow(root, s)
        window = CafeItemsWindow(root, s, app.refresh)
        window.window.geometry('580x460'); root.update()
        window.items.selection_set('item-purchase-1'); window.selection_changed()
        self.assertTrue(window.use_button.instate(['disabled']))
        self.assertFalse(window.sell_button.instate(['disabled']))
        self.assertIn('50', window.sale_notice.get())
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False): window.sell_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        with patch('tkinter.messagebox.askyesno', return_value=True): window.sell_button.invoke()
        self.assertEqual(window.items.set('item-purchase-2', '所持数'), '1')
        window.items.selection_set('item-purchase-3'); window.selection_changed()
        self.assertIn('75', window.sale_notice.get())
        with patch('tkinter.messagebox.askyesno', return_value=True): window.sell_button.invoke()
        self.assertEqual(len(window.sale_history.get_children()), 2)
        self.assertTrue(any('栄養おやつを1個売却' in str(app.history.item(key)['values']) for key in app.history.get_children()))
        for button in (window.sell_button, window.buy_button, window.use_button, window.close_button):
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), window.window.winfo_rootx()+window.window.winfo_width())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), window.window.winfo_rooty()+window.window.winfo_height())
        window.window.destroy(); s.day_off()
        history = CafeHistoryWindow(root, s)
        self.assertEqual(history.days.set(history.days.get_children()[0], '用品売却収入'), '125')
