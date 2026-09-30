"""栄養おやつの疲労回復、閉店基準と旧ケア用品の互換。"""
import copy
import os
import unittest
from unittest.mock import patch, PropertyMock

import test_cafe_traits as fixtures
from cat_cafe_sim.core.cafe_items import definition, inventory, unavailable_reason
from cat_cafe_sim.core.cafe_item_shop import catalog
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game
from cat_cafe_sim.cafe_shift_forecast import shift_forecast


class NutritionSnackTests(unittest.TestCase):
    setUp = fixtures.TraitTests.setUp
    session = fixtures.TraitTests.session
    close = fixtures.TraitTests.close
    reload = fixtures.TraitTests.reload

    def snack(self):
        return next(row for row in catalog() if row['item']['id']=='nutrition_snack')

    def prepared(self, assigned=None, management=True):
        s = self.session(assigned, fatigue=32, management=management)
        self.close(s); s.next_day()
        return s

    def replay(self, s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def reject(self, s, action):
        before = s.core.snapshot()
        with self.assertRaises(ValueError): action()
        self.assertEqual(s.core.snapshot(), before)

    def test_price_fixed_recovery_traits_and_work_forecast_after_use(self):
        for trait_id, before, after, closed in (('hardy', 24, 9, 33), ('relaxed', 40, 25, 65)):
            with self.subTest(trait=trait_id):
                s = self.prepared({'a': trait_id})
                funds, stress = s.core.funds, s.core.management['stress']['a']
                s.purchase_item(self.snack())
                self.assertEqual(s.core.funds, funds - 150)
                s.use_item('item-purchase-1', 'a')
                self.assertEqual(s.core.item_uses[-1]['before'], before)
                self.assertEqual(s.core.cats['a'].fatigue, after)
                self.assertEqual(s.core.initial_fatigue['a'], after)
                self.assertEqual(s.core.management['stress']['a'], stress)
                self.assertEqual(shift_forecast(s.core, 'a')['work']['fatigue'], closed)
                s = self.reload(s); self.replay(s)
                self.close(s)
                self.assertEqual(s.core.cats['a'].fatigue, closed)
                self.assertEqual(s.core.summary()['item_expenses'], 150)
                s.next_day()
                self.assertEqual(s.core.day_results[-1]['summary']['item_expenses'], 150)
                self.reload(s); self.replay(s)

    def test_partial_recovery_zero_refusal_and_mixed_inventory(self):
        s = self.prepared({'a': 'hardy'})
        for _ in range(3): s.purchase_item(self.snack())
        s.purchase_item()  # 従来の既定購入はケア用品。
        self.assertEqual(s.core.item_purchases[-1]['item']['id'], 'care_supplies')
        s.use_item('item-purchase-1', 'a'); s.use_item('item-purchase-2', 'a')
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.reject(s, lambda: s.use_item('item-purchase-3', 'a'))
        self.assertIn('item-purchase-3', inventory(s.core))
        self.reject(s, lambda: s.use_item('item-purchase-1', 'a'))
        s.use_item('item-purchase-4', 'a')
        self.assertEqual(s.core.management['stress']['a'], 0)
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        s = self.reload(s); s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.reload(s); self.replay(s)

    def test_rest_after_use_does_not_restore_old_fatigue(self):
        s = self.prepared()
        s.purchase_item(self.snack()); s.use_item('item-purchase-1', 'a')
        self.assertEqual(s.core.cats['a'].fatigue, 17)
        self.assertEqual(shift_forecast(s.core, 'a')['rest']['fatigue'], 0)
        s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue, 0)
        self.reload(s); self.replay(s)

    def test_fatigue_item_without_stress_management(self):
        s = self.prepared(management=False)
        s.purchase_item(self.snack()); s.use_item('item-purchase-1', 'a')
        self.assertIsNone(s.core.management)
        self.assertEqual(s.core.cats['a'].fatigue, 17)
        self.reload(s); self.replay(s)

    def test_unavailable_cats_pending_business_and_sickness_not_cured(self):
        s = self.prepared(); s.purchase_item(self.snack())
        for activity in ('dispatched', 'missing', 'adopted'):
            core = copy.deepcopy(s.core)
            from cat_cafe_sim.core.cafe_activities import ensure
            ensure(core); core.activities['cats']['a'] = activity
            self.assertIn('在店', unavailable_reason(core, 'item-purchase-1', 'a'))
        core = copy.deepcopy(s.core)
        core.cats['a'].health_status = 'sick'; core.cats['a'].recovery_days_remaining = 2
        core.cats['a'].cannot_continue = True
        core.use_item('item-purchase-1', 'a')
        self.assertEqual(core.cats['a'].health_status, 'sick')
        self.assertEqual(core.cats['a'].recovery_days_remaining, 2)
        with patch.object(type(s), 'pending', new_callable=PropertyMock, return_value={'pending'}):
            self.reject(s, lambda: s.use_item('item-purchase-1', 'a'))
            self.reject(s, lambda: s.purchase_item(self.snack()))
        s.automatic_step()
        self.reject(s, lambda: s.use_item('item-purchase-1', 'a'))
        self.reject(s, lambda: s.purchase_item(self.snack()))

    def test_purchase_funds_boundary_and_end(self):
        s = self.prepared(); s.core.funds = 149
        self.reject(s, lambda: s.purchase_item(self.snack()))
        s.core.funds = 150; s.purchase_item(self.snack())
        self.assertEqual(s.core.funds, 0)
        self.assertEqual(s.core.management['game_over']['reason'], 'funds')
        self.reject(s, lambda: s.use_item('item-purchase-1', 'a'))

    def test_save_failure_retry_and_frozen_item_effect(self):
        s = self.prepared(); s.purchase_item(self.snack()); funds = s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, self.path)
        s = self.reload(s); s.use_item('item-purchase-1', 'a')
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, self.path)
        with patch('cat_cafe_sim.core.cafe_item_shop.catalog', side_effect=AssertionError('settings changed')):
            s = self.reload(s); self.replay(s)
        self.assertEqual(s.core.funds, funds)
        self.assertEqual(s.core.cats['a'].fatigue, 17)
        self.reject(s, lambda: s.use_item('item-purchase-1', 'a'))

    def test_old_care_save_and_replay_keep_record_shape(self):
        s = self.prepared(); s.purchase_item(); s.use_item('item-purchase-1', 'a')
        self.assertEqual(set(s.core.item_uses[0]), {'source','cat_id','day','before','after'})
        self.assertNotIn('stat', next(e for e in s.core.events if e['kind']=='item_used'))
        self.assertEqual(s.core.cats['a'].fatigue, 32)
        self.reload(s); self.replay(s)

    def test_invalid_item_definition_and_use_record_rejected(self):
        item = self.snack()['item']
        for change in (dict(fatigue_relief=True), dict(fatigue_relief=0), dict(fatigue_relief=float('inf')),
                       dict(stress_relief=10), dict(id='care_supplies')):
            with self.assertRaises(ValueError): definition(dict(item, **change))
        s = self.prepared(); s.purchase_item(self.snack()); s.use_item('item-purchase-1', 'a')
        source = checkpoint(s.core, set())
        for mutate in (lambda d: d['state']['item_uses'][0].update(after=20),
                       lambda d: d['state']['item_uses'].append(copy.deepcopy(d['state']['item_uses'][0])),
                       lambda d: d['state']['item_purchases'][0]['item'].update(fatigue_relief=-15)):
            bad = copy.deepcopy(source); mutate(bad)
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError): restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires desktop')
class NutritionSnackWindowTests(unittest.TestCase):
    setUp = fixtures.TraitTests.setUp
    session = fixtures.TraitTests.session
    close = fixtures.TraitTests.close
    prepared = NutritionSnackTests.prepared

    def test_purchase_preview_cancel_use_history_logs_and_small_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_cat_events import cat_events
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.prepared(); app = CafeInteractionWindow(root, s)
        window = CafeItemsWindow(root, s, app.refresh)
        window.shop_choice.current(1); window.select_shop()
        window.window.geometry('580x460'); root.update()
        self.assertIn('1個 150', window.shop_note.get())
        self.assertIn('疲労 −15', window.shop_note.get())
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False): window.buy_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        with patch('tkinter.messagebox.askyesno', return_value=True): window.buy_button.invoke()
        window.cats.selection_set('a'); window.selection_changed()
        self.assertIn('疲労 32 → 17', window.notice.get())
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False): window.use_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        with patch('tkinter.messagebox.askyesno', return_value=True): window.use_button.invoke()
        self.assertIn('疲労 32 → 17', window.result.get())
        self.assertIn('疲労 32 → 17', str([window.history.item(key)['values'] for key in window.history.get_children()]))
        self.assertTrue(any('疲労 32 → 17' in str(app.history.item(key)['values']) for key in app.history.get_children()))
        self.assertTrue(any('疲労 32 → 17' in str(row) for row in cat_events(s.core, 'a')))
        for button in (window.buy_button, window.use_button, window.close_button):
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), window.window.winfo_rootx()+window.window.winfo_width())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), window.window.winfo_rooty()+window.window.winfo_height())
        window.shop_choice.current(0); window.select_shop()
        self.assertEqual(window.buy_button['text'], 'ケア用品を1個購入')
