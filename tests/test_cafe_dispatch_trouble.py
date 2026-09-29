import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.core.cafe_activities import destinations, reward, waiting_events
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_dispatch_trouble import DESTINATION_ID, draw, probability, waiting, expenses, rules
from cat_cafe_sim.core.cafe_dispatch_unlocks import count
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class DispatchTroubleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def game(self, chance=1, *, legacy=False, seats=2, funds=3000):
        selected = starting_conditions('free')
        for key in ('store_events', 'intake_request', 'dispatch_unlocks'):
            selected.pop(key)
        selected['seat_count'] = seats
        selected['management']['starting_funds'] = funds
        selected['dispatch_trouble'].update(base_probability=chance, stress_probability=0)
        if legacy:
            selected.pop('dispatch_trouble')
        return create_game(Path(self.temp.name) / 'games', selected)

    def depart(self, s, cat_id='cat-tama'):
        s.dispatch(cat_id, s.core.dispatch_trouble['destination'])
        return f'dispatch-{s.core.day}-{cat_id}'

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(s.core.snapshot(), loaded.core.snapshot())
        return loaded

    def replay(self, s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def rejected(self, s, action, error=ValueError):
        before, profiles = s.core.log(), s.store._read()
        with self.assertRaises(error): action()
        self.assertEqual(before, s.core.log()); self.assertEqual(profiles, s.store._read())

    def close(self, s):
        while not s.core.closed: s.automatic_step()

    def test_new_destination_exclusive_and_legacy_destinations_unchanged(self):
        s = self.game()
        self.assertEqual(len(destinations()), 3)
        self.assertEqual(destinations(s.core)[:3], destinations())
        self.assertEqual(destinations(s.core)[-1]['id'], DESTINATION_ID)
        selected = rules()['destination']
        old = self.game(legacy=True)
        self.assertEqual(destinations(old.core), destinations())
        self.assertNotIn('dispatch_trouble', old.core.snapshot())
        old = self.reload(old)
        self.rejected(old, lambda: old.dispatch('cat-tama', selected))
        self.rejected(s, lambda: s.dispatch('cat-mike', s.core.dispatch_trouble['destination']))
        self.depart(s); s.dispatch('cat-mike')
        self.assertNotIn('trouble', s.core.activities['events']['dispatch-1-cat-mike'])
        s.day_off()
        s.resolve_dispatch_trouble('dispatch-1-cat-tama', 'wait')
        s.resolve_activity('dispatch-1-cat-mike')
        self.assertEqual(count(s.core), 1)
        self.reload(s); self.replay(s)

    def test_no_trouble_normal_return_rewards_and_growth_both_seat_modes(self):
        for seats in (1, 2):
            s = self.game(0, seats=seats); event_id = self.depart(s)
            original = copy.deepcopy(s.core.activities['events'][event_id]['trouble'])
            s = self.reload(s)
            for _ in range(3): s.day_off()
            event = s.core.activities['events'][event_id]
            self.assertEqual(event['trouble']['status'], 'not_triggered')
            self.assertEqual(event['trouble']['draw'], original['draw'])
            expected = reward(s.core, event); before = s.core.funds
            s.resolve_activity(event_id)
            self.assertEqual(s.core.funds, before+expected)
            self.assertEqual(s.core.growth['cats']['cat-tama']['dispatch'], s.core.growth['rules']['dispatch_xp'])
            self.assertEqual(s.core.activity('cat-tama'), 'cafe')
            self.assertEqual(count(s.core), 1)
            self.assertEqual(expenses(s.core), 0)
            self.reload(s); self.replay(s)

    def test_wait_missing_return_and_no_rewards_experience_popularity_or_kittens(self):
        s = self.game(); event_id = self.depart(s); popularity = s.core.management['popularity']
        s.day_off()
        self.assertEqual(s.core.activity('cat-tama'), 'missing')
        self.assertTrue(waiting(s.core)); self.assertTrue(waiting_events(s.core))
        for action in (s.day_off, lambda: s.set_shifts(['cat-tama']), lambda: s.play_with_player('cat-tama'),
                       lambda: s.resolve_activity(event_id)):
            self.rejected(s, action)
        s = self.reload(s); self.replay(s)
        s.resolve_dispatch_trouble(event_id, 'wait')
        s.resolve_dispatch_trouble(event_id, 'wait')
        self.rejected(s, lambda: s.resolve_dispatch_trouble(event_id, 'search'))
        s.day_off()
        self.assertEqual(s.core.activities['events'][event_id]['remaining'], 1)
        self.rejected(s, lambda: s.play_with_player('cat-tama'))
        s = self.reload(s); s.day_off()
        event = s.core.activities['events'][event_id]
        self.assertEqual(event['status'], 'waiting'); self.assertEqual(event['occurred_day'], 3)
        before = s.core.funds
        s.resolve_activity(event_id); s.resolve_activity(event_id)
        self.assertEqual(s.core.funds, before)
        self.assertEqual(s.core.activity('cat-tama'), 'cafe')
        self.assertEqual(s.core.management['stress']['cat-tama'], 30)
        self.assertEqual(s.core.management['popularity'], popularity)
        self.assertEqual(s.core.management['events'], {})
        self.assertEqual(s.core.growth['cats']['cat-tama']['dispatch'], 0)
        self.assertEqual(count(s.core), 0)
        self.assertTrue(any(row[1] == '派遣中の家出' for row in cat_events(s.core, 'cat-tama')))
        self.reload(s); self.replay(s)

    def test_search_prep_and_closed_accounting_return_once(self):
        for closed in (False, True):
            s = self.game(); event_id = self.depart(s)
            if closed: self.close(s)
            else: s.day_off()
            before = s.core.funds
            s.resolve_dispatch_trouble(event_id, 'search')
            self.assertEqual(s.core.funds, before-100)
            self.assertEqual(s.core.summary()['dispatch_trouble_expenses'], 100)
            self.assertEqual(expenses(s.core), 100)
            self.assertEqual(s.core.activities['events'][event_id]['status'], 'waiting')
            s = self.reload(s); self.replay(s)
            s.resolve_activity(event_id)
            self.assertEqual(s.core.funds, before-100)
            self.assertNotIn('cat-tama', s.core.working_cats)
            self.assertEqual(s.core.summary()['opening_funds'], 3000 if closed else s.core.day_results[0]['summary']['closing_funds'])
            if closed: s.next_day()
            else: s.day_off()
            self.assertEqual(s.core.summary()['dispatch_trouble_expenses'], 0)
            self.assertEqual(expenses(s.core), 100)
            self.reload(s); self.replay(s)

    def test_search_funds_boundary_free_wait_and_pending_save(self):
        for remaining_funds in (100, 101):
            s = self.game(funds=remaining_funds+60)
            event_id = self.depart(s); s.day_off()
            self.assertEqual(s.core.funds, remaining_funds)
            with patch.object(type(s), 'pending', new_callable=PropertyMock, return_value={'pending': {}}):
                self.rejected(s, lambda: s.resolve_dispatch_trouble(event_id, 'wait'))
            if remaining_funds == 100:
                self.rejected(s, lambda: s.resolve_dispatch_trouble(event_id, 'search'))
                s.resolve_dispatch_trouble(event_id, 'wait')
            else:
                s.resolve_dispatch_trouble(event_id, 'search'); s.resolve_activity(event_id)
                self.assertEqual(s.core.funds, 1)
            self.reload(s)

    def test_draw_risk_freezing_rules_and_detailed_replay_do_not_reload_config(self):
        selected = starting_conditions('free')
        for key in ('store_events', 'intake_request', 'dispatch_unlocks'): selected.pop(key)
        s = create_game(Path(self.temp.name) / 'games', selected)
        s.core.management['stress']['cat-tama'] = 40
        self.assertAlmostEqual(probability(s.core, 'cat-tama'), .29)
        s.core.management['stress']['cat-tama'] = 0
        event_id = self.depart(s)
        data = copy.deepcopy(s.core.activities['events'][event_id]['trouble'])
        self.assertAlmostEqual(data['probability'], .15)
        self.assertEqual(data['draw'], draw(s.core.seed, event_id))
        self.assertEqual(probability(s.core, 'cat-tama'), data['probability'])
        original_rules = rules
        with patch('cat_cafe_sim.core.cafe_dispatch_trouble.rules', side_effect=lambda data=None: original_rules(data) if data is not None else self.fail('reload config')):
            s = self.reload(s)
            self.assertEqual(s.core.activities['events'][event_id]['trouble'], data)
            self.replay(s)

    def test_unrelated_destination_rejects_trouble_and_new_destination_requires_record(self):
        s = self.game()
        self.rejected(s, lambda: s.core.dispatch('cat-mike', destinations()[0], trouble={'bad': True}))
        self.rejected(s, lambda: s.core.dispatch('cat-tama', s.core.dispatch_trouble['destination']))
        selected = rules()
        for mutate in (lambda row: row.update(base_probability=True), lambda row: row.update(missing_days=0),
                       lambda row: row.update(stress_probability=2), lambda row: row['destination'].update(id='other')):
            bad = copy.deepcopy(selected); mutate(bad)
            with self.assertRaises(ValueError): rules(bad)

    def test_malformed_trouble_state_timing_draw_cost_and_activity_rejected(self):
        s = self.game(); event_id = self.depart(s); s.day_off(); s.resolve_dispatch_trouble(event_id, 'wait')
        source = checkpoint(s.core, set())
        for mutate in (
                lambda state: state['activities']['events'][event_id]['trouble'].update(draw=.99),
                lambda state: state['activities']['events'][event_id]['trouble'].update(probability=.5),
                lambda state: state['activities']['events'][event_id]['trouble'].update(choice_day=3),
                lambda state: state['activities']['events'][event_id]['trouble'].update(cost=100),
                lambda state: state['activities']['events'][event_id].update(remaining=0),
                lambda state: state['activities']['cats'].update({'cat-tama':'dispatched'}),
                lambda state: state['activities']['events'][event_id].pop('trouble'),
                lambda state: state.pop('dispatch_trouble')):
            bad = copy.deepcopy(source); mutate(bad['state'])
            bad['digest'] = digest({key:value for key,value in bad.items() if key!='digest'})
            with self.assertRaises(ValueError): restore(bad)

    def test_checkpoint_failure_keeps_response_and_retry_does_not_charge_again(self):
        s = self.game(); event_id = self.depart(s); s.day_off(); s.resolve_dispatch_trouble(event_id, 'search')
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            self.rejected(s, lambda: save_game(s, s.checkpoint_path), OSError)
        s = self.reload(s); s.resolve_dispatch_trouble(event_id, 'search')
        self.assertEqual(expenses(s.core), 100)
        s.resolve_activity(event_id); self.reload(s)

    def test_multiple_troubles_are_answered_independently(self):
        s = self.game(); s.purchase_cat('shop-2')
        first = self.depart(s); second = self.depart(s, 'shop-2')
        s.day_off()
        self.assertEqual(len(waiting(s.core)), 2)
        s.resolve_dispatch_trouble(first, 'search')
        s.resolve_dispatch_trouble(second, 'wait')
        s.resolve_activity(first)
        self.assertEqual(s.core.activity('cat-tama'), 'cafe')
        self.assertEqual(s.core.activity('shop-2'), 'missing')
        self.reload(s); self.replay(s)
        s.day_off(); s.day_off(); s.resolve_activity(second)
        self.assertEqual(expenses(s.core), 100)
        self.reload(s); self.replay(s)

    def test_normal_runaway_and_dispatch_missing_coexist_and_return(self):
        selected = starting_conditions('free')
        for key in ('store_events', 'intake_request', 'dispatch_unlocks'): selected.pop(key)
        selected['dispatch_trouble'].update(base_probability=1, stress_probability=0)
        selected['management'].update(starting_funds=3000, runaway_threshold=1, return_stress=0, stress_per_service_tick=100, kitten_probability=0)
        s = create_game(Path(self.temp.name) / 'games', selected)
        event_id = self.depart(s); s.set_shifts(['cat-mike']); self.close(s)
        self.assertEqual(s.core.activity('cat-mike'), 'missing')
        self.assertEqual(s.core.activity('cat-tama'), 'missing')
        s.resolve_dispatch_trouble(event_id, 'wait')
        s = self.reload(s); self.replay(s)
        s.next_day(); s.day_off(); s.day_off()
        s.resolve_missing('missing-1-cat-mike'); s.resolve_activity(event_id)
        self.assertEqual(s.core.activity('cat-mike'), 'cafe')
        self.assertEqual(s.core.activity('cat-tama'), 'cafe')
        self.reload(s); self.replay(s)

    def test_game_over_keeps_pending_trouble_readonly(self):
        s = self.game(funds=60); event_id = self.depart(s); s.day_off()
        self.assertIsNotNone(s.core.management['game_over'])
        self.rejected(s, lambda: s.resolve_dispatch_trouble(event_id, 'wait'))
        self.rejected(s, lambda: s.resolve_activity(event_id))
        self.reload(s); self.replay(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class DispatchTroubleWindowTests(unittest.TestCase):
    setUp = DispatchTroubleTests.setUp
    game = DispatchTroubleTests.game
    depart = DispatchTroubleTests.depart

    def test_new_destination_risk_confirmation_choice_and_result_history(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game()
        window = CafeActivityWindow(root, s, lambda: None, show_navigation=False)
        index = next(i for i,row in enumerate(window.destinations) if row['id']==DESTINATION_ID)
        window.destination_choice.current(index); window.select_destination()
        window.cats.selection_set('cat-tama'); window.buttons()
        self.assertIn('発生率：100%', window.selection_info.get())
        with patch('tkinter.messagebox.askyesno', return_value=False): window.send_button.invoke()
        self.assertIsNone(s.core.activities)
        with patch('tkinter.messagebox.askyesno', return_value=True): window.send_button.invoke()
        s.day_off(); window.refresh()
        event_id = 'dispatch-1-cat-tama'; window.events.selection_set(event_id); window.buttons()
        self.assertEqual(window.receive_button['text'], '家出トラブルに対応…')
        window.receive_button.invoke(); trouble = window.trouble_window
        trouble.window.geometry('500x340'); root.update()
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False): trouble.search_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        self.assertLessEqual(trouble.close_button.winfo_rooty()+trouble.close_button.winfo_height(), trouble.window.winfo_rooty()+trouble.window.winfo_height())
        with patch('tkinter.messagebox.askyesno', return_value=True): trouble.search_button.invoke()
        self.assertTrue(trouble.search_button.instate(['disabled']))
        trouble.close_button.invoke()
        self.assertIn('帰還を確認する', window.receive_button['text'])
        window.receive_button.invoke(); window.show_result()
        self.assertIn('資金報酬合計：0', window.result_text.get('1.0', 'end'))
        self.assertIn('捜索費：100', window.result_text.get('1.0', 'end'))

    def test_insufficient_funds_free_wait_dashboard_and_old_destination_list(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_dispatch_trouble_gui import CafeDispatchTroubleWindow
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game(funds=160); event_id = self.depart(s); s.day_off()
        app = CafeInteractionWindow(root, s)
        self.assertIn('家出トラブル', app.notice.get())
        window = CafeDispatchTroubleWindow(root, s, event_id, app.refresh)
        self.assertTrue(window.search_button.instate(['disabled']))
        self.assertFalse(window.wait_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno', return_value=True): window.wait_button.invoke()
        self.assertFalse(waiting(s.core)); window.close_button.invoke()
        old = self.game(legacy=True)
        activity = CafeActivityWindow(root, old, lambda: None)
        self.assertEqual(len(activity.destinations), 3)


if __name__ == '__main__': unittest.main()
