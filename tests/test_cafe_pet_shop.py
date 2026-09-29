import copy
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.cafe_health import HealthRules
from cat_cafe_sim.core.cafe_growth import total
from cat_cafe_sim.core.cafe_checkpoint import outcome_result
from cat_cafe_sim.core.cafe_pet_shop import candidates, expenses
from cat_cafe_sim.core.cafe_recruitment import catalog
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class PetShopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def game(self, *, legacy=False, funds=3000, seats=2, intake=False):
        selected = starting_conditions('free')
        selected.pop('store_events')
        if not intake:
            selected.pop('intake_request')
        if legacy:
            selected.pop('pet_shop')
        selected['management']['starting_funds'] = funds
        selected['seat_count'] = seats
        return create_game(Path(self.temp.name) / 'games', selected)

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def rejected(self, s, action, error=ValueError):
        before, profiles = s.core.log(), s.store._read()
        with self.assertRaises(error):
            action()
        self.assertEqual(s.core.log(), before)
        self.assertEqual(s.store._read(), profiles)

    def close(self, s):
        while not s.core.closed:
            s.automatic_step()

    def test_catalog_distinct_fixed_candidates_and_reserved_ids(self):
        rows = candidates({'shop-1', 'shop-3'})
        self.assertEqual(list(rows), ['shop-2', 'shop-4', 'shop-5'])
        self.assertEqual([row['name'] for row in rows.values()], ['チロ', 'レオ', 'ナナ'])
        self.assertEqual([row['cost'] for row in rows.values()], [400, 450, 500])
        combinations = lambda rows: {(digest(row['personality']), tuple(row['features']), row['trait']['id']) for row in rows}
        self.assertFalse(combinations(rows.values()) & combinations(catalog()))
        self.assertEqual(rows, candidates({'shop-3', 'shop-1'}))
        with self.assertRaises(ValueError):
            candidates(set(), [dict(next(iter(rows.values())), cost=-1)])

    def test_purchase_accounting_history_roster_save_and_replay_both_seat_modes(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.game(seats=seats)
                source = copy.deepcopy(s.core.pet_shop['candidates'])
                self.assertEqual(len(s.core.cats), 5)
                s.play_with_player('cat-mike')
                s.player_command(finish=True)
                s.purchase_cat('shop-1')
                self.assertEqual(s.core.funds, 2600)
                self.assertEqual(s.core.summary()['pet_shop_expenses'], 400)
                self.assertEqual(s.core.summary()['recruitment_expenses'], 0)
                self.assertEqual(s.core.summary()['total_expenses'], 400)
                self.assertEqual(s.core.summary()['opening_funds'], 3000)
                self.assertEqual(s.core.cat_features['shop-1'], source['shop-1']['features'])
                self.assertEqual(s.core.traits['shop-1'], source['shop-1']['trait'])
                self.assertNotIn('shop-1', s.core.working_cats)
                self.assertEqual(s.core.cats['shop-1'].stamina, s.core.config.max_stamina)
                self.assertEqual(s.core.management['stress']['shop-1'], 0)
                self.assertEqual(total(s.core.growth['cats']['shop-1']), 0)
                for field in ('affinity', 'today', 'total'):
                    self.assertEqual(s.core.player_bond[field]['shop-1'], 0)
                self.assertEqual(dict(cat_details(s, 'shop-1')['basic'])['加入経路'], 'ペットショップ')
                self.assertIn((1, '加入', 'ペットショップ', '購入費 400'), cat_events(s.core, 'shop-1'))
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                s = self.reload(s)
                self.rejected(s, lambda: s.purchase_cat('shop-1'))
                s.day_off()
                self.assertEqual(s.core.summary()['pet_shop_expenses'], 0)
                self.assertEqual(s.core.day_results[0]['summary']['pet_shop_expenses'], 400)
                self.assertEqual(s.core.pet_shop['candidates'], source)
                self.reload(s)

    def test_candidates_persist_without_refresh_and_do_not_read_changed_config(self):
        s = self.game()
        original = copy.deepcopy(s.core.pet_shop)
        with patch('cat_cafe_sim.core.cafe_pet_shop.candidates', side_effect=AssertionError('reroll')):
            for _ in range(3):
                s.day_off()
            s = self.reload(s)
            self.assertEqual(s.core.pet_shop, original)
            s.purchase_cat('shop-2')
            self.assertEqual(expenses(s.core), 450)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
            self.reload(s)

    def test_housing_shared_with_rescue_and_expansion_allows_other_purchases(self):
        s = self.game()
        s.purchase_cat('shop-1')
        self.rejected(s, lambda: s.purchase_cat('shop-2'))
        s.open_recruitment()
        self.rejected(s, lambda: s.recruit_cat('rescue-1'))
        s.purchase_housing()
        s.purchase_cat('shop-2')
        s.purchase_cat('shop-3')
        s.recruit_cat('rescue-1')
        self.assertEqual(len(s.core.cats), 9)
        self.assertEqual(expenses(s.core), 1350)
        self.assertEqual(s.core.summary()['pet_shop_expenses'], 1350)
        self.assertEqual(s.core.summary()['recruitment_expenses'], 200)
        self.assertEqual(s.core.summary()['total_expenses'], 2050)
        self.rejected(s, lambda: s.recruit_cat('rescue-2'))
        s.day_off()
        self.reload(s)

    def test_funds_must_remain_positive(self):
        for funds in (399, 400, 401):
            s = self.game(funds=funds)
            if funds <= 400:
                self.rejected(s, lambda: s.purchase_cat('shop-1'))
            else:
                s.purchase_cat('shop-1')
                self.assertEqual(s.core.funds, 1)
                self.reload(s)

    def test_relationship_failure_then_retry_and_checkpoint_failure(self):
        s = self.game()
        with patch.object(s.store, '_write', side_effect=OSError('full')):
            self.rejected(s, lambda: s.purchase_cat('shop-1'), OSError)
        s.purchase_cat('shop-1')
        self.assertEqual(expenses(s.core), 400)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            self.rejected(s, lambda: save_game(s, s.checkpoint_path), OSError)
        s = self.reload(s)
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.store.register_cat('shop-2', 'external', Personality())
        self.rejected(s, lambda: s.purchase_cat('shop-2'))

    def test_profile_conflicts_and_older_checkpoint_cannot_overwrite_purchase(self):
        s = self.game()
        s.purchase_cat('shop-1')
        with self.assertRaises(ValueError):
            load_game(s.checkpoint_path)
        s = self.reload(s)
        data = s.store._read()
        data['cats']['shop-1']['name'] = 'changed'
        s.store._write(data)
        with self.assertRaises(ValueError):
            load_game(s.checkpoint_path)
        with self.assertRaises(ValueError):
            save_game(s, s.checkpoint_path)

    def test_joined_cat_profile_used_for_player_service_and_dispatch(self):
        from cat_cafe_sim.core.cafe_preferences import match
        selected = starting_conditions('free')
        for key in ('store_events', 'intake_request'):
            selected.pop(key)
        selected['management']['starting_funds'] = 3000
        selected['preferences']['pool'] = ['long_hair']
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.purchase_cat('shop-1')
        s.play_with_player('shop-1')
        self.assertEqual(s.core.player_bond['active']['config']['personality'], s.core.pet_shop['candidates']['shop-1']['personality'])
        s.player_command(finish=True)
        s.set_shifts(['shop-1'])
        while not s.core.visits:
            s.automatic_step()
        self.assertTrue(match(s.core, 'shop-1', next(iter(s.core.visits)))['matched'])
        self.close(s)
        self.assertTrue(any(outcome_result(log)['cat_id'] == 'shop-1' for log in s.core.outcomes.values()))
        s.next_day()
        s.dispatch('shop-1')
        s.day_off()
        s.resolve_activity('dispatch-2-shop-1')
        self.assertEqual(s.core.activity('shop-1'), 'cafe')
        self.assertGreater(total(s.core.growth['cats']['shop-1']), 0)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_business_interaction_pending_return_request_and_game_over_block_purchase(self):
        s = self.game(intake=True)
        s.play_with_player('cat-mike')
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.player_command(finish=True)
        s.dispatch('cat-tama')
        s.day_off()
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.resolve_activity('dispatch-1-cat-tama')
        s.automatic_step()
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        self.close(s)
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.next_day(); s.day_off()
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.resolve_intake_request('decline')
        s.purchase_cat('shop-1')
        s = self.game(funds=1)
        s.day_off()
        self.assertIsNotNone(s.core.management['game_over'])
        self.rejected(s, lambda: s.purchase_cat('shop-1'))

    def test_legacy_save_omits_shop_and_keeps_original_replay(self):
        s = self.game(legacy=True)
        self.assertNotIn('pet_shop', s.core.snapshot())
        s = self.reload(s)
        self.assertIsNone(s.core.pet_shop)
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.open_recruitment(); s.recruit_cat('rescue-1'); s.day_off()
        self.assertNotIn('pet_shop_expenses', s.core.day_results[0]['summary'])
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_pending_results_and_introduction_block_purchase_until_resolved(self):
        from unittest.mock import PropertyMock
        from cat_cafe_sim.core.cafe_activities import destinations
        s = self.game()
        with patch.object(type(s), 'pending', new_callable=PropertyMock, return_value={'pending': {}}):
            self.rejected(s, lambda: s.purchase_cat('shop-1'))
        # The introduction must be answered before another optional joining path.
        selected = starting_conditions('free')
        for field in ('store_events', 'intake_request', 'dispatch_unlocks'):
            selected.pop(field)
        selected['management']['starting_funds'] = 3000
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.dispatch('cat-mike', destinations()[1])
        s.day_off(); s.resolve_dispatch_choice('dispatch-1-cat-mike', 'decline'); s.day_off()
        s.resolve_activity('dispatch-1-cat-mike')
        self.rejected(s, lambda: s.purchase_cat('shop-1'))
        s.resolve_dispatch_introduction('dispatch-1-cat-mike', 'decline')
        s.purchase_cat('shop-1')
        self.reload(s)

    def test_all_start_modes_keep_shop_candidates(self):
        for mode in ('popularity', 'patron', 'bond', 'free'):
            selected = starting_conditions(mode)
            selected.pop('store_events')
            s = create_game(Path(self.temp.name) / 'games', selected)
            self.assertEqual(len(s.core.pet_shop['candidates']), 3)
            s.purchase_cat('shop-1')
            self.reload(s)

    def test_single_cat_core_replay_without_base_and_cross_path_id_collisions(self):
        core = CafeInteractionCore(replace(Config.load(), initial_funds=1000), compact=True)
        core.set_shifts(['cat-1'])
        core.enable_health(asdict(HealthRules.load()))
        core.initialize_pet_shop(candidates(core.cats))
        with self.assertRaises(ValueError):
            core.open_recruitment({'shop-2': core.pet_shop['candidates']['shop-2']})
        core.purchase_cat('shop-1')
        self.assertEqual(verify_cafe_interaction(core.log()).snapshot(), core.snapshot())
        self.assertEqual(restore(checkpoint(core, set())).snapshot(), core.snapshot())
        with self.assertRaises(ValueError):
            core.initialize_pet_shop(candidates(core.cats))

    def test_corrupt_purchase_records_costs_features_and_rules_are_rejected(self):
        s = self.game(); s.purchase_cat('shop-1')
        source = checkpoint(s.core, set())
        for mutate in (
                lambda state: state['pet_shop']['accepted'].update({'shop-1': 2}),
                lambda state: state['pet_shop']['accepted'].clear(),
                lambda state: state['pet_shop'].update(opened_day=0),
                lambda state: state['pet_shop']['candidates']['shop-1'].update(cost=399),
                lambda state: state['pet_shop']['candidates']['shop-1'].update(cost=True),
                lambda state: state['pet_shop']['candidates']['shop-1'].update(features=['black', 'long_hair']),
                lambda state: state['pet_shop']['candidates'].update({'cat-mike': state['pet_shop']['candidates']['shop-2']}),
                lambda state: state['pet_shop'].update(last_added_day=1),
                lambda state: state.pop('health')):
            bad = copy.deepcopy(source); mutate(bad['state'])
            bad['digest'] = digest({key: value for key, value in bad.items() if key != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class PetShopWindowTests(unittest.TestCase):
    setUp = PetShopTests.setUp
    game = PetShopTests.game

    def test_dashboard_purchase_cancel_history_details_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_history import CafeHistoryWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game()
        app = CafeInteractionWindow(root, s)
        self.assertFalse(app.pet_shop_button.instate(['disabled']))
        app.pet_shop_button.invoke()
        window = app.pet_shop_window
        window.window.geometry('500x440'); root.update()
        self.assertEqual(window.cats.item('shop-1')['values'][:2], ['チロ', '白猫・長毛'])
        self.assertIn('購入費 400 / 購入後の所持金 2600', window.notice.get())
        self.assertIn(['体調 / 出勤予定', '健康 / 休養'], [window.details.item(key)['values'] for key in window.details.get_children()])
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.receive_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        self.assertLessEqual(window.close_button.winfo_rooty()+window.close_button.winfo_height(), window.window.winfo_rooty()+window.window.winfo_height())
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.receive_button.invoke()
        self.assertTrue(window.receive_button.instate(['disabled']))
        self.assertIn('購入済み', window.notice.get())
        window.close_button.invoke()
        s.day_off()
        history = CafeHistoryWindow(root, s)
        self.assertEqual(history.days.set(history.days.get_children()[0], '猫購入費'), '400')
        history.window.destroy()
        app.refresh(); app.pet_shop_button.invoke()
        self.assertEqual(app.pet_shop_window.cats.item('shop-1')['values'][-1], '1日目に購入済み')

    def test_funds_full_and_business_readonly_and_legacy_disabled(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_pet_shop_gui import CafePetShopWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game(funds=400)
        window = CafePetShopWindow(root, s, lambda: None)
        self.assertTrue(window.receive_button.instate(['disabled']))
        self.assertIn('資金', window.notice.get()); window.window.destroy()
        s = self.game(); s.open_recruitment(); s.recruit_cat('rescue-1')
        window = CafePetShopWindow(root, s, lambda: None)
        self.assertTrue(window.receive_button.instate(['disabled']))
        self.assertIn('満員', window.notice.get()); window.window.destroy()
        s = self.game(); s.automatic_step()
        window = CafePetShopWindow(root, s, lambda: None)
        self.assertTrue(window.receive_button.instate(['disabled']))
        self.assertIn('準備中', window.notice.get()); window.window.destroy()
        s = self.game(legacy=True)
        app = CafeInteractionWindow(root, s)
        self.assertTrue(app.pet_shop_button.instate(['disabled']))


if __name__ == '__main__':
    unittest.main()
