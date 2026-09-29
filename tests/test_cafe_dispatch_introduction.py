import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_activities import destinations, waiting_events
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_dispatch_introduction import waiting, expenses, rules
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class DispatchIntroductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def game(self, *, legacy=False, intake=False, seats=2):
        selected = starting_conditions('free')
        for key in ('store_events', 'dispatch_unlocks'):
            selected.pop(key)
        if not intake:
            selected.pop('intake_request')
        else:
            selected['intake_request']['day'] = 3
        if legacy:
            selected.pop('dispatch_introduction')
        selected['seat_count'] = seats
        selected['management']['starting_funds'] = 3000
        return create_game(Path(self.temp.name) / 'games', selected)

    def depart(self, s, key='cat-mike'):
        s.dispatch(key, destinations()[1])
        return f'dispatch-{s.core.day}-{key}'

    def receive(self, s, event_id):
        s.day_off(); s.resolve_dispatch_choice(event_id, 'decline'); s.day_off()
        s.resolve_activity(event_id)

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def replay(self, s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def rejected(self, s, action, error=ValueError):
        before, relationships = s.core.snapshot(), s.store._read()
        with self.assertRaises(error): action()
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(s.store._read(), relationships)

    def test_departure_return_accept_join_finance_history_save_and_replay(self):
        from cat_cafe_sim.cafe_cat_details import cat_details
        from cat_cafe_sim.cafe_cat_events import cat_events
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.game(seats=seats); event_id = self.depart(s)
                offered = copy.deepcopy(s.core.activities['events'][event_id]['introduction'])
                s = self.reload(s)
                self.receive(s, event_id)
                s = self.reload(s)
                self.assertEqual(len(waiting(s.core)), 1)
                self.rejected(s, s.day_off)
                self.rejected(s, s.automatic_step)
                self.rejected(s, lambda: s.set_shifts([]))
                before = s.core.funds
                s.resolve_dispatch_introduction(event_id, 'accept')
                key = offered['cat_id']; row = offered['candidate']
                self.assertEqual(len(s.core.cats), 6)
                self.assertEqual(s.core.funds, before-200)
                self.assertNotIn(key, s.core.working_cats)
                self.assertEqual(s.core.activity(key), 'cafe')
                self.assertEqual(s.core.cat_features[key], ['white', 'long_hair'])
                self.assertEqual(s.core.traits[key]['id'], 'hospitality')
                self.assertEqual(s.core.management['stress'][key], 0)
                self.assertEqual(s.core.growth['cats'][key]['service'], 0)
                self.assertEqual(s.profiles[key]['personality'], row['personality'])
                self.assertEqual(expenses(s.core), 200)
                self.assertEqual(s.core.summary()['recruitment_expenses'], 200)
                self.assertEqual(dict(cat_details(s, key)['basic'])['加入経路'], '派遣先からの紹介')
                self.assertTrue(any(record[1]=='加入' for record in cat_events(s.core, key)))
                self.assertTrue(any(record[1]=='猫の紹介' for record in cat_events(s.core, 'cat-mike')))
                s = self.reload(s); self.replay(s)
                before = s.core.snapshot()
                with patch.object(s.store, '_write', side_effect=AssertionError('duplicate registration')):
                    s.resolve_dispatch_introduction(event_id, 'accept')
                    s.resolve_activity(event_id)
                self.assertEqual(s.core.snapshot(), before)
                self.rejected(s, lambda: s.resolve_dispatch_introduction(event_id, 'decline'))
                s.day_off()
                result = s.core.day_results[-1]['summary']
                self.assertEqual(result['recruitment_expenses'], 200)
                self.assertEqual(result['total_expenses'], 200 + result['operating_cost'])
                self.assertEqual(s.core.summary()['recruitment_expenses'], 0)
                self.reload(s); self.replay(s)

    def test_decline_preserves_funds_popularity_rewards_and_unblocks(self):
        s = self.game(); event_id = self.depart(s); self.receive(s, event_id)
        funds, popularity = s.core.funds, s.core.management['popularity']
        before = s.core.activities['events'][event_id]['resolved_day']
        with patch.object(s.store, '_write', side_effect=AssertionError('registration on decline')):
            s.resolve_dispatch_introduction(event_id, 'decline')
            s.resolve_dispatch_introduction(event_id, 'decline')
        self.assertEqual((s.core.funds, s.core.management['popularity']), (funds, popularity))
        self.assertEqual(s.core.activities['events'][event_id]['resolved_day'], before)
        self.assertEqual(expenses(s.core), 0)
        self.assertEqual(len(s.core.cats), 5)
        self.assertFalse(waiting_events(s.core))
        s.day_off(); self.reload(s); self.replay(s)

    def test_closed_return_defers_introduction_until_next_preparation(self):
        s = self.game(); event_id = self.depart(s)
        for day in range(2):
            while not s.core.closed: s.automatic_step()
            if day == 0:
                s.resolve_dispatch_choice(event_id, 'decline'); s.next_day()
        s.resolve_activity(event_id)
        self.assertEqual(s.core.activities['events'][event_id]['introduction']['status'], 'scheduled')
        self.assertFalse(waiting(s.core)); s = self.reload(s)
        self.rejected(s, lambda: s.resolve_dispatch_introduction(event_id, 'accept'))
        s.next_day(); self.assertTrue(waiting(s.core))
        s.resolve_dispatch_introduction(event_id, 'accept')
        self.assertNotIn('dispatch-rescue-1', s.core.day_results[-1]['cats'])
        self.reload(s); self.replay(s)

    def test_full_and_insufficient_funds_can_decline_instead(self):
        for full in (True, False):
            with self.subTest(full=full):
                s = self.game()
                if full:
                    s.open_recruitment(); s.recruit_cat('rescue-1')
                event_id = self.depart(s); self.receive(s, event_id)
                if not full: s.core.funds = 200
                self.rejected(s, lambda: s.resolve_dispatch_introduction(event_id, 'accept'))
                s.resolve_dispatch_introduction(event_id, 'decline')
                self.assertFalse(waiting(s.core))
                if full:
                    s.day_off(); self.reload(s); self.replay(s)

    def test_intake_and_multiple_introductions_resolve_without_deadlock(self):
        s = self.game(intake=True)
        s.open_recruitment(); s.recruit_cat('rescue-1')
        s.purchase_housing()
        first = self.depart(s); second = self.depart(s, 'rescue-1')
        s.day_off()
        s.resolve_dispatch_choice(first, 'decline'); s.resolve_dispatch_choice(second, 'decline')
        s.day_off()
        s.resolve_activity(first); s.resolve_activity(second)
        self.assertEqual(len(waiting(s.core)), 2)
        self.assertEqual(s.core.intake_request['status'], 'waiting')
        s.resolve_intake_request('accept')
        s.resolve_dispatch_introduction(first, 'accept')
        s.resolve_dispatch_introduction(second, 'decline')
        self.assertEqual(len(s.core.cats), 8)
        self.assertFalse(waiting(s.core))
        s.day_off(); self.reload(s); self.replay(s)

    def test_registration_failure_retry_and_external_id_conflict(self):
        s = self.game(); event_id = self.depart(s); self.receive(s, event_id)
        with patch.object(s.store, '_write', side_effect=OSError('disk full')):
            self.rejected(s, lambda: s.resolve_dispatch_introduction(event_id, 'accept'), OSError)
        s.resolve_dispatch_introduction(event_id, 'accept')
        before = s.core.snapshot()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): save_game(s, s.checkpoint_path)
        self.assertEqual(s.core.snapshot(), before); self.reload(s); self.replay(s)
        other = self.game(); other_id = self.depart(other); self.receive(other, other_id)
        key = other.core.activities['events'][other_id]['introduction']['cat_id']
        other.store.register_cat(key, '外部登録', other.presets['中立'])
        self.rejected(other, lambda: other.resolve_dispatch_introduction(other_id, 'accept'))

    def test_unique_ids_reserved_across_departures_and_regular_candidates(self):
        s = self.game()
        s.store.register_cat('dispatch-rescue-1', '既存登録', s.presets['中立'])
        s.checkpoint_baseline = s.store._read()  # Pre-existing external profiles are part of the initial baseline.
        event_id = self.depart(s)
        self.assertEqual(s.core.activities['events'][event_id]['introduction']['cat_id'], 'dispatch-rescue-2')
        # The lower-level candidate path must also reject IDs reserved by a travelling introduction.
        row = copy.deepcopy(s.core.activities['events'][event_id]['introduction']['candidate'])
        self.rejected(s, lambda: s.core.open_recruitment({'dispatch-rescue-2': row}))
        self.receive(s, event_id); s.resolve_dispatch_introduction(event_id, 'decline')
        next_id = self.depart(s)
        self.assertEqual(s.core.activities['events'][next_id]['introduction']['cat_id'], 'dispatch-rescue-3')
        self.reload(s); self.replay(s)

    def test_old_saves_trips_and_other_destinations_have_no_introduction(self):
        s = self.game(legacy=True); event_id = self.depart(s)
        self.assertNotIn('introduction', s.core.activities['events'][event_id])
        self.receive(s, event_id); self.assertFalse(waiting(s.core))
        s = self.reload(s); self.assertIsNone(s.core.dispatch_introduction); self.replay(s)
        s = self.game(); s.dispatch('cat-sora')
        self.assertNotIn('introduction', next(iter(s.core.activities['events'].values())))
        s.day_off(); s.resolve_activity('dispatch-1-cat-sora'); self.assertFalse(waiting(s.core))
        s = self.game()
        # An old-style operation lacks the optional candidate even with new-game rules enabled.
        s.core.dispatch('cat-mike', destinations()[1])
        event_id = 'dispatch-1-cat-mike'
        s.day_off(); s.day_off(); s.resolve_activity(event_id)
        self.assertNotIn('introduction', s.core.activities['events'][event_id])
        self.reload(s); self.replay(s)

    def test_config_is_frozen_and_corrupt_records_are_rejected(self):
        s = self.game(); event_id = self.depart(s)
        def frozen(selected=None):
            if selected is None: raise AssertionError('config reload')
            return rules(selected)
        with patch('cat_cafe_sim.core.cafe_dispatch_introduction.rules', side_effect=frozen):
            s = self.reload(s)
            s.day_off(); s.resolve_dispatch_choice(event_id, 'decline'); s.day_off(); s.resolve_activity(event_id)
            self.reload(s); self.replay(s)
        source = checkpoint(s.core, set())
        for mutate in (
                lambda row: row.update(status='accepted'),
                lambda row: row.update(presented_day=0),
                lambda row: row.update(cat_id='cat-mike'),
                lambda row: row['candidate'].update(cost=0),
                lambda row: row.update(resolved_day=3)):
            bad = copy.deepcopy(source); mutate(bad['state']['activities']['events'][event_id]['introduction'])
            bad['digest'] = digest({k: v for k, v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError): restore(bad)
        s.resolve_dispatch_introduction(event_id, 'accept')
        bad = checkpoint(s.core, set())
        bad['state']['traits']['dispatch-rescue-1']['id'] = 'relaxed'
        bad['digest'] = digest({k: v for k, v in bad.items() if k != 'digest'})
        with self.assertRaises(ValueError): restore(bad)
        for data in ({}, dict(rules(), destination='unknown')):
            with self.assertRaises(ValueError): rules(data)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class DispatchIntroductionWindowTests(unittest.TestCase):
    setUp = DispatchIntroductionTests.setUp
    game = DispatchIntroductionTests.game
    depart = DispatchIntroductionTests.depart
    receive = DispatchIntroductionTests.receive

    def test_return_screen_intro_cancel_accept_and_small_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game(); event_id = self.depart(s); self.receive(s, event_id)
        activity = CafeActivityWindow(root, s, lambda: None, show_navigation=False)
        activity.events.selection_set(event_id); activity.buttons()
        self.assertEqual(activity.receive_button['text'], '猫の紹介…')
        activity.receive_button.invoke(); window = activity.introduction_window
        window.window.geometry('560x420'); root.update()
        values = [window.details.item(key)['values'] for key in window.details.get_children()]
        self.assertIn(['特徴', '白猫・長毛'], values)
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno', return_value=False): window.accept_button.invoke()
        self.assertEqual(s.core.snapshot(), before)
        self.assertLessEqual(window.close_button.winfo_rooty()+window.close_button.winfo_height(),
                             window.window.winfo_rooty()+window.window.winfo_height())
        with patch('tkinter.messagebox.askyesno', return_value=True): window.accept_button.invoke()
        self.assertIn('迎えました', window.notice.get())
        self.assertTrue(window.accept_button.instate(['disabled']))
        window.close_button.invoke()
        self.assertEqual(activity.receive_button['text'], '猫紹介の記録…')
        activity.window.destroy()

    def test_full_window_disables_accept_and_can_decline(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_dispatch_introduction_gui import CafeDispatchIntroductionWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.game(); s.open_recruitment(); s.recruit_cat('rescue-1')
        event_id = self.depart(s); self.receive(s, event_id)
        window = CafeDispatchIntroductionWindow(root, s, event_id, lambda: None)
        self.assertIn('満員', window.notice.get())
        self.assertTrue(window.accept_button.instate(['disabled']))
        self.assertFalse(window.decline_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno', return_value=True): window.decline_button.invoke()
        self.assertIn('見送りました', window.notice.get())
        self.assertFalse(waiting(s.core))


if __name__ == '__main__': unittest.main()
