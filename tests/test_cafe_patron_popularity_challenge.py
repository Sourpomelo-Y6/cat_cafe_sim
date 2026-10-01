"""有力者への派遣と途中開始の人気挑戦の併用・保存・結果確認。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cafe_popularity_challenge as helpers
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_objective import progress
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_goal import pending as goal_pending
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_patron import pending as patron_pending
from cat_cafe_sim.core.cafe_popularity_challenge import CUSTOMERS, rules
from cat_cafe_sim.core.cafe_reservation import waiting


class PatronPopularityChallengeTests(unittest.TestCase):
    setUp=helpers.PopularityChallengeTests.setUp
    close=helpers.PopularityChallengeTests.close
    reload=helpers.PopularityChallengeTests.reload
    easy=helpers.PopularityChallengeTests.easy
    rejected=helpers.PopularityChallengeTests.rejected

    def game(self, *, easy_patron=False):
        self.sequence+=1
        selected=starting_conditions('patron'); selected.pop('intake_request')
        selected['management']['starting_funds']=10000
        selected['store_events']['probability']=0
        selected['growth']['threshold']=1000
        if easy_patron:
            selected['patron']['target']=25
            selected['patron']['destination']['days']=1
        return create_game(Path(self.temp.name)/str(self.sequence),selected)

    def dispatch(self,s,key='cat-mugi'):
        s.dispatch(key,s.core.patron['rules']['destination'])
        return f'dispatch-{s.core.day}-{key}'

    def replay(self,s):
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_start_preserves_existing_trip_satisfaction_and_store_history(self):
        s=self.game(); first=self.dispatch(s); s.day_off(); s.day_off(); s.resolve_activity(first)
        self.assertEqual(s.core.patron['satisfaction'],25)
        second=self.dispatch(s); before=s.core.snapshot()
        s.start_popularity_challenge(self.easy(s))
        for key,value in before.items():
            if key!='goal':self.assertEqual(s.core.snapshot()[key],value)
        self.assertEqual(s.core.objective,'patron')
        self.assertEqual(s.core.goal['days'],before['goal']['days'])
        self.assertEqual(s.core.goal['challenge_started_day'],3)
        self.assertIn('満足度 25',progress(s.core)); self.assertIn('12日目まで',progress(s.core))
        self.rejected(s,s.start_popularity_challenge); self.replay(s)
        s.day_off(); s.day_off(); s.resolve_activity(second)
        self.assertEqual(s.core.patron['satisfaction'],50); self.replay(s)

    def test_simultaneous_expiry_and_multiple_returns_confirm_in_either_order(self):
        for patron_first in (True,False):
            with self.subTest(patron_first=patron_first):
                s=self.game(easy_patron=True)
                ids=[self.dispatch(s,key) for key in ('cat-mugi','cat-sora')]
                selected=self.easy(s); selected['goal']['days']=1
                s.start_popularity_challenge(selected); s.day_off()
                self.assertTrue(goal_pending(s.core)); self.assertFalse(patron_pending(s.core))
                self.rejected(s,s.start_popularity_challenge); self.rejected(s,s.continue_goal)
                s.resolve_activity(ids[0]); self.assertTrue(patron_pending(s.core))
                self.rejected(s,s.continue_patron); self.replay(s)
                s.resolve_activity(ids[1]); before=s.core.snapshot(); s.resolve_activity(ids[1])
                self.assertEqual(s.core.snapshot(),before)
                self.assertEqual(s.core.patron['satisfaction'],25)
                self.assertEqual(set(s.core.clear_results),{'patron'}); self.replay(s)
                first,second=(s.continue_patron,s.continue_goal) if patron_first else (s.continue_goal,s.continue_patron)
                first(); self.rejected(s,s.day_off); self.replay(s)
                second(); s.day_off(); self.replay(s)

    def test_closed_day_results_and_return_can_be_confirmed_and_reopened(self):
        s=self.game(easy_patron=True); event=self.dispatch(s)
        selected=rules(s.core); selected['goal']['days']=1
        s.start_popularity_challenge(selected); self.close(s)
        self.assertTrue(s.core.closed); self.assertEqual(s.core.goal['status'],'expired')
        self.rejected(s,s.continue_goal); s.resolve_activity(event)
        self.assertTrue(patron_pending(s.core)); self.assertTrue(goal_pending(s.core)); self.replay(s)
        s.continue_goal(); self.rejected(s,s.next_day); s.continue_patron(); s.next_day()
        self.assertEqual(s.core.patron['resolved_day'],1); self.assertEqual(s.core.goal['resolved_day'],1)
        self.replay(s)

    def test_simultaneous_stage_clear_and_patron_clear_block_advance_until_confirmed(self):
        s=self.game(easy_patron=True); self.close(s); s.next_day()
        self.assertGreaterEqual(s.core.management['popularity'],105)
        event=self.dispatch(s); s.start_popularity_challenge(self.easy(s)); s.day_off()
        self.assertEqual(s.core.goal['status'],'cleared')
        self.rejected(s,s.advance_goal)
        s.resolve_activity(event); self.assertTrue(patron_pending(s.core)); self.assertTrue(goal_pending(s.core))
        self.rejected(s,s.advance_goal); self.replay(s)
        result=copy.deepcopy(s.core.clear_results['patron'])
        s.continue_patron(); s.advance_goal(); self.close(s)
        self.assertTrue(goal_pending(s.core)); self.assertFalse(patron_pending(s.core))
        self.assertEqual(s.core.clear_results['patron'],result); self.replay(s)

    def test_expired_popularity_can_continue_and_clear_patron_later(self):
        s=self.game(easy_patron=True)
        for _ in range(11):s.day_off()
        s.start_popularity_challenge()
        for _ in range(20):s.day_off()
        self.assertEqual(s.core.goal['resolved_day'],31)
        self.assertEqual(s.core.patron['status'],'active')
        self.rejected(s,lambda:self.dispatch(s)); self.replay(s)
        s.continue_goal(); event=self.dispatch(s); s.day_off(); s.resolve_activity(event)
        self.assertTrue(patron_pending(s.core)); self.assertFalse(goal_pending(s.core))
        s.continue_patron(); s.day_off(); self.rejected(s,s.start_popularity_challenge); self.replay(s)

    def test_patron_clear_before_start_keeps_achievement_after_confirmation(self):
        s=self.game(easy_patron=True); event=self.dispatch(s); s.day_off()
        self.rejected(s,s.start_popularity_challenge)
        s.resolve_activity(event); self.rejected(s,s.start_popularity_challenge); self.replay(s)
        s.continue_patron(); before=copy.deepcopy(s.core.patron)
        result=copy.deepcopy(s.core.clear_results['patron'])
        s.start_popularity_challenge(self.easy(s)); self.close(s)
        self.assertEqual(s.core.patron,before); self.assertEqual(s.core.clear_results['patron'],result)
        self.replay(s)

    def test_all_stages_customers_and_four_through_six_seats_with_patron(self):
        helpers.PopularityChallengeTests.test_all_three_stages_unlock_customers_and_four_through_six_seats(self)

    def test_both_final_results_and_further_returns_keep_original_achievements(self):
        s=self.game(easy_patron=True); s.start_popularity_challenge(self.easy(s))
        for stage in range(3):
            self.close(s)
            self.assertEqual(s.core.goal['status'],'cleared'); self.assertEqual(s.core.patron['status'],'active')
            (s.advance_goal if stage<2 else s.continue_goal)(); s.next_day()
            if waiting(s.core):s.resolve_reservation('decline')
        popularity=copy.deepcopy(s.core.clear_results['popularity'])
        event=self.dispatch(s); s.day_off(); s.resolve_activity(event)
        self.assertEqual(set(s.core.clear_results),{'popularity','patron'})
        self.assertEqual(s.core.clear_results['popularity'],popularity); self.replay(s)
        s.continue_patron(); results=copy.deepcopy(s.core.clear_results); achieved=s.core.patron['resolved_day']
        event=self.dispatch(s); s.day_off(); s.resolve_activity(event)
        self.assertEqual(s.core.clear_results,results); self.assertEqual(s.core.patron['resolved_day'],achieved)
        self.assertFalse(patron_pending(s.core)); self.replay(s)

    def test_old_tracking_and_corrupt_patron_or_objective_are_rejected(self):
        s=self.game(); event=self.dispatch(s); s.day_off(); self.replay(s)
        self.assertTrue(s.core.goal['tracking_only']); self.assertNotIn('challenge_started_day',s.core.goal)
        self.assertTrue(all(getattr(s.core,key) is None for key in CUSTOMERS))
        s.start_popularity_challenge(); source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state'].pop('patron'),
            lambda d:d['state']['patron'].update(started_day=2),
            lambda d:d['state']['patron'].update(satisfaction=25),
            lambda d:d['state']['patron']['rules']['destination'].update(reward=999),
            lambda d:d['state'].update(objective='bond'),
            lambda d:d['state'].update(objective='popularity'),
            lambda d:d['state'].pop('objective'),
            lambda d:d['state'].pop('reservation'),
        ):
            bad=copy.deepcopy(source); mutate(bad)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        self.replay(s)

    def test_frozen_rules_save_failure_retry_and_game_over(self):
        s=self.game(); s.start_popularity_challenge(self.easy(s))
        with patch('cat_cafe_sim.core.cafe_popularity_challenge.rules',side_effect=lambda core,data:rules(core,data)):
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.step(); s.start(s.core.queue[0],s.available_cats()[0].id,'seat-1'); s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.finish()
        self.rejected(s,s.start_popularity_challenge); s=self.reload(s); s.persist(); self.close(s)
        self.replay(s)
        s=self.game(easy_patron=True); event=self.dispatch(s); s.start_popularity_challenge()
        s.core.management['game_over']=dict(reason='funds',day=1)
        for action in (s.start_popularity_challenge,s.continue_goal,s.continue_patron,lambda:s.resolve_activity(event)):
            self.rejected(s,action)
        self.assertEqual(s.core.patron['status'],'active')


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class PatronPopularityChallengeGuiTests(unittest.TestCase):
    setUp=helpers.PopularityChallengeTests.setUp
    game=PatronPopularityChallengeTests.game

    def test_start_cancel_confirmation_and_both_progress_displays(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.game(easy_patron=True); app=CafeInteractionWindow(root,s)
        self.assertIn('人気3段階へ挑戦',app.goal_button['text'])
        app.show_goal(); window=app.goal_window
        self.assertFalse(window.enable_button.instate(['disabled']))
        self.assertIn('有力者目標を維持',window.notice.get())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.enable_button.invoke()
        self.assertEqual(before,s.core.snapshot())
        with patch('tkinter.messagebox.askyesno',return_value=True) as confirm:window.enable_button.invoke()
        self.assertIn('有力者の派遣・満足度・成果',confirm.call_args.args[1])
        for text in (app.objective_progress.get(),app.results_summary.get()):
            self.assertIn('満足度',text); self.assertIn('人気目標',text)
        root.geometry('860x660'); window.window.geometry('500x400'); root.update()
        self.assertGreater(window.history.winfo_height(),0)
        self.assertGreaterEqual(app.history.winfo_height(),120)
        window.window.destroy(); app.show_patron()
        self.assertIn('挑戦中',app.patron_window.status.get()); app.patron_window.window.destroy()
