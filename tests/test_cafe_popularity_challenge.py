import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_objective import progress
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_goal import current_start, pending
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_popularity_challenge import CUSTOMERS, reason, rules
from cat_cafe_sim.core.cafe_reservation import waiting
from cat_cafe_sim.core.cafe_seat_equipment import catalog
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class PopularityChallengeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sequence=0

    def game(self,mode='free'):
        self.sequence+=1
        selected=starting_conditions(mode); selected.pop('intake_request')
        selected['management']['starting_funds']=10000
        selected['store_events']['probability']=0
        selected['growth']['threshold']=1000
        return create_game(Path(self.temp.name)/str(self.sequence),selected)

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def reload(self,s):
        save_game(s,s.checkpoint_path); loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot()); return loaded

    def easy(self,s):
        selected=rules(s.core); selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=10,target=115)])
        return selected

    def rejected(self,s,action):
        before=s.core.snapshot()
        with self.assertRaises(ValueError):action()
        self.assertEqual(before,s.core.snapshot())

    def test_start_after_free_service_preserves_everything_except_goal_and_new_customers(self):
        s=self.game(); s.expand_seats()
        s.purchase_seat_equipment('seat-3',next(row for row in catalog() if row['id']=='grooming_brush'))
        self.close(s); s.next_day(); before=s.core.snapshot()
        s.start_popularity_challenge(self.easy(s))
        self.assertEqual(s.core.objective,'free'); self.assertNotIn('tracking_only',s.core.goal)
        self.assertEqual(current_start(s.core.goal),2); self.assertEqual(s.core.goal['challenge_started_day'],2)
        self.assertEqual(s.core.goal['days'],before['goal']['days'])
        self.assertEqual(s.core.goal['status'],'active')
        self.assertNotIn('goal_status',s.core.day_results[0]['summary'])
        for key in before:
            if key not in ('goal',):self.assertEqual(s.core.snapshot()[key],before[key])
        self.assertTrue(all(getattr(s.core,key) is not None for key in CUSTOMERS))
        self.assertIn('自由営業から挑戦',progress(s.core))
        self.assertIn('11日目まで',progress(s.core))
        self.rejected(s,s.start_popularity_challenge)
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_deadline_begins_at_challenge_day_and_day_off_counts(self):
        s=self.game()
        for _ in range(11):s.day_off()
        self.assertEqual(s.core.day,12); s.start_popularity_challenge()
        self.assertIn('21日目まで',progress(s.core))
        for _ in range(9):s.day_off(); self.assertEqual(s.core.goal['status'],'active')
        s.day_off(); self.assertEqual(s.core.goal['status'],'expired')
        self.assertEqual(s.core.goal['resolved_day'],21); self.assertTrue(pending(s.core))
        self.assertEqual(len(s.core.goal['days']),21)
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.continue_goal(); self.rejected(s,s.start_popularity_challenge)

    def test_all_three_stages_unlock_customers_and_four_through_six_seats(self):
        from cat_cafe_sim.core.cafe_quiet_customer import schedule as quiet_schedule
        from cat_cafe_sim.core.cafe_play_customer import schedule as play_schedule
        from cat_cafe_sim.core.cafe_contact_customer import schedule as contact_schedule
        from cat_cafe_sim.core.cafe_vip_customer import schedule as vip_schedule
        s=self.game(); self.close(s); s.next_day(); s.expand_seats()
        s.start_popularity_challenge(self.easy(s))
        self.assertFalse(any(row['arrival_tick'] is not None for row in directory(s) if row['customer_id'].startswith('advanced-')))
        for seat_count in (4,5,6):
            self.close(s); self.assertEqual(s.core.goal['status'],'cleared')
            (s.advance_goal if seat_count<6 else s.continue_goal)(); s.next_day()
            if waiting(s.core):s.resolve_reservation('decline')
            s.expand_seats(); self.assertEqual(len(s.core.seats),seat_count)
            self.reload(s)
        self.assertTrue(play_schedule(s.core,6)); self.assertTrue(quiet_schedule(s.core,5)); self.assertTrue(contact_schedule(s.core,7))
        self.assertTrue(vip_schedule(s.core,s.core.day))
        self.assertIn('popularity',s.core.clear_results)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_inherited_popularity_does_not_clear_until_day_ends(self):
        s=self.game(); self.close(s); s.next_day()
        self.assertGreaterEqual(s.core.management['popularity'],105)
        s.start_popularity_challenge(self.easy(s)); self.assertEqual(s.core.goal['status'],'active')
        s.day_off(); self.assertEqual(s.core.goal['resolved_day'],2)
        self.assertEqual(s.core.goal['status'],'cleared'); self.reload(s)

    def test_wrong_modes_closed_service_player_exchange_and_event_waits_are_blocked(self):
        s=self.game('popularity'); self.rejected(s,s.start_popularity_challenge)
        s=self.game(); s.step(); self.rejected(s,s.start_popularity_challenge)
        self.close(s); self.rejected(s,s.start_popularity_challenge)
        s=self.game(); s.play_with_player('cat-mugi'); self.rejected(s,s.start_popularity_challenge)
        s=self.game(); s.dispatch(next(iter(s.core.cats))); s.day_off()
        self.rejected(s,s.start_popularity_challenge)

    def test_popularity_rates_and_invalid_settings_are_checked_atomically(self):
        s=self.game(); selected=self.easy(s)
        for change in (dict(cap=400),dict(gain_per_success=9),dict(stages=[])):
            bad=copy.deepcopy(selected); bad['goal'].update(change)
            self.rejected(s,lambda:s.start_popularity_challenge(bad))
        bad=copy.deepcopy(selected); bad['contact_customer']['contact_count']=0
        self.rejected(s,lambda:s.start_popularity_challenge(bad))
        self.assertTrue(s.core.goal['tracking_only'])
        self.assertTrue(all(getattr(s.core,key) is None for key in CUSTOMERS))

    def test_saved_rules_survive_config_change_active_service_and_failure_retry(self):
        s=self.game(); s.start_popularity_challenge(self.easy(s))
        with patch('cat_cafe_sim.core.cafe_popularity_challenge.rules',side_effect=lambda core,data:rules(core,data)):
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.step(); s.start(s.core.queue[0],s.available_cats()[0].id,'seat-1'); s=self.reload(s)
        s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.finish()
        self.assertTrue(s.pending); self.rejected(s,s.start_popularity_challenge)
        s=self.reload(s); s.persist(); self.reload(s)
        self.assertEqual(sum(e['kind']=='popularity_challenge_started' for e in s.core.events),1)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_legacy_without_marker_keeps_tracking_and_rejects_corruption(self):
        s=self.game(); s.day_off(); self.reload(s)
        self.assertNotIn('challenge_started_day',s.core.goal)
        self.assertTrue(s.core.goal['tracking_only'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.start_popularity_challenge(self.easy(s)); source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['goal'].update(challenge_started_day=None),
            lambda d:d['state']['goal'].update(challenge_started_day=0),
            lambda d:d['state']['goal'].update(challenge_started_day=3),
            lambda d:d['state']['goal'].pop('challenge_started_day'),
            lambda d:d['state'].update(objective='popularity'),
            lambda d:d['state'].pop('objective'),lambda d:d['state'].pop('contact_customer'),
        ):
            bad=copy.deepcopy(source); mutate(bad); bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class PopularityChallengeGuiTests(unittest.TestCase):
    setUp=PopularityChallengeTests.setUp
    game=PopularityChallengeTests.game

    def test_start_button_confirmation_cancel_progress_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.game(); app=CafeInteractionWindow(root,s)
        self.assertIn('人気3段階へ挑戦',app.goal_button['text'])
        app.show_goal(); window=app.goal_window; self.assertFalse(window.enable_button.instate(['disabled']))
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.enable_button.invoke()
        self.assertEqual(before,s.core.snapshot())
        with patch('tkinter.messagebox.askyesno',return_value=True):window.enable_button.invoke()
        self.assertNotIn('tracking_only',s.core.goal)
        self.assertEqual(len(window.history.get_children()),3)
        self.assertIn('自由営業から挑戦',app.objective_progress.get())
        window.window.geometry('500x400'); root.update()
        self.assertGreater(window.history.winfo_height(),0); window.window.destroy()
