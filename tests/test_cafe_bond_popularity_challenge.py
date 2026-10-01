"""好感度目標と途中開始の人気挑戦が独立して進行することを確認する。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cafe_popularity_challenge as helpers
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_objective import progress
from cat_cafe_sim.core.cafe_bond_goal import pending as bond_pending
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_goal import pending as goal_pending
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_popularity_challenge import CUSTOMERS


class BondPopularityChallengeTests(unittest.TestCase):
    setUp=helpers.PopularityChallengeTests.setUp
    close=helpers.PopularityChallengeTests.close
    reload=helpers.PopularityChallengeTests.reload
    easy=helpers.PopularityChallengeTests.easy
    rejected=helpers.PopularityChallengeTests.rejected

    def game(self, *, easy_bond=False):
        self.sequence+=1
        selected=starting_conditions('bond'); selected.pop('intake_request')
        selected['management']['starting_funds']=10000
        selected['store_events']['probability']=0
        selected['growth']['threshold']=1000
        if easy_bond:selected['bond']=dict(target=1,affinity=.5)
        return create_game(Path(self.temp.name)/str(self.sequence),selected)

    def play(self,s):
        s.play_with_player('cat-mugi'); s.player_command('direct'); s.player_command(finish=True)

    def replay(self,s):
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_start_preserves_bond_progress_store_and_history(self):
        s=self.game(); self.play(s); self.close(s); s.next_day()
        before=s.core.snapshot(); s.start_popularity_challenge(self.easy(s))
        for key,value in before.items():
            if key!='goal':self.assertEqual(s.core.snapshot()[key],value)
        self.assertEqual(s.core.objective,'bond')
        self.assertEqual(s.core.goal['days'],before['goal']['days'])
        self.assertEqual(s.core.goal['challenge_started_day'],2)
        self.assertIn('好感度目標',progress(s.core)); self.assertIn('11日目まで',progress(s.core))
        self.rejected(s,s.start_popularity_challenge); self.replay(s)

    def test_bond_clear_blocks_advance_until_its_own_result_is_confirmed(self):
        s=self.game(easy_bond=True); s.start_popularity_challenge(self.easy(s))
        self.close(s); s.continue_goal(); s.next_day()
        self.play(s)
        self.assertTrue(bond_pending(s.core)); self.assertFalse(goal_pending(s.core))
        self.assertEqual(set(s.core.clear_results),{'bond'})
        self.rejected(s,s.advance_goal); self.rejected(s,s.day_off); self.replay(s)
        bond=copy.deepcopy(s.core.bond_goal); result=copy.deepcopy(s.core.clear_results['bond'])
        s.continue_bond_goal(); s.advance_goal(); self.close(s)
        self.assertTrue(goal_pending(s.core)); self.assertFalse(bond_pending(s.core))
        self.assertEqual(s.core.bond_goal['achieved_cats'],bond['achieved_cats'])
        self.assertEqual(s.core.clear_results['bond'],result); self.replay(s)

    def test_expired_popularity_keeps_bond_active_and_allows_later_clear(self):
        s=self.game(easy_bond=True)
        for _ in range(11):s.day_off()
        s.start_popularity_challenge()
        for _ in range(20):s.day_off()
        self.assertEqual(s.core.goal['resolved_day'],31)
        self.assertEqual(s.core.goal['status'],'expired'); self.assertEqual(s.core.bond_goal['status'],'active')
        self.rejected(s,lambda:self.play(s)); self.replay(s)
        s.continue_goal(); self.play(s)
        self.assertTrue(bond_pending(s.core)); self.assertFalse(goal_pending(s.core))
        self.assertEqual(set(s.core.clear_results),{'bond'})
        s.continue_bond_goal(); s.day_off(); self.rejected(s,s.start_popularity_challenge); self.replay(s)

    def test_bond_clear_before_start_requires_confirmation_and_keeps_result(self):
        s=self.game(easy_bond=True); self.play(s)
        self.rejected(s,s.start_popularity_challenge); self.replay(s)
        s.continue_bond_goal(); before=copy.deepcopy(s.core.bond_goal)
        result=copy.deepcopy(s.core.clear_results['bond'])
        s.start_popularity_challenge(self.easy(s)); self.close(s)
        self.assertEqual(s.core.bond_goal,before); self.assertEqual(s.core.clear_results['bond'],result)
        self.replay(s)

    def test_all_stages_customers_and_seats_with_bond_still_active(self):
        helpers.PopularityChallengeTests.test_all_three_stages_unlock_customers_and_four_through_six_seats(self)
        # The helper uses this class's bond fixture and exercises real closing/save/replay.

    def test_final_popularity_and_bond_clear_results_survive_independent_continuation(self):
        from cat_cafe_sim.core.cafe_reservation import waiting
        s=self.game(easy_bond=True); s.start_popularity_challenge(self.easy(s))
        for stage in range(3):
            self.close(s)
            self.assertEqual(s.core.goal['status'],'cleared')
            self.assertEqual(s.core.bond_goal['status'],'active')
            (s.advance_goal if stage<2 else s.continue_goal)(); s.next_day()
            if waiting(s.core):s.resolve_reservation('decline')
        popularity=copy.deepcopy(s.core.clear_results['popularity'])
        self.play(s); self.assertTrue(bond_pending(s.core))
        self.assertEqual(set(s.core.clear_results),{'popularity','bond'})
        self.assertEqual(s.core.clear_results['popularity'],popularity); self.replay(s)
        s.continue_bond_goal(); s.day_off()
        self.assertTrue(s.core.goal['continued']); self.assertTrue(s.core.bond_goal['continued'])
        self.replay(s)

    def test_tracking_legacy_and_corrupt_objective_or_bond_are_rejected(self):
        s=self.game(); s.day_off(); self.replay(s)
        self.assertTrue(s.core.goal['tracking_only']); self.assertNotIn('challenge_started_day',s.core.goal)
        self.assertTrue(all(getattr(s.core,key) is None for key in CUSTOMERS))
        s.start_popularity_challenge(); source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state'].pop('bond_goal'),
            lambda d:d['state']['bond_goal'].update(started_day=2),
            lambda d:d['state'].update(objective='patron'),
            lambda d:d['state'].pop('objective'),
            lambda d:d['state'].pop('reservation'),
        ):
            bad=copy.deepcopy(source); mutate(bad)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        self.replay(s)

    def test_start_blocked_by_exchange_pending_save_and_game_over(self):
        s=self.game(); s.play_with_player('cat-mugi'); self.rejected(s,s.start_popularity_challenge)
        s=self.game(); s.step(); s.start(s.core.queue[0],s.available_cats()[0].id,'seat-1'); s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.finish()
        self.rejected(s,s.start_popularity_challenge)
        s=self.reload(s); s.persist(); self.close(s); s.next_day(); s.start_popularity_challenge(); self.replay(s)
        s=self.game(); s.core.management['game_over']=dict(reason='funds',day=1)
        self.rejected(s,s.start_popularity_challenge)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class BondPopularityChallengeGuiTests(unittest.TestCase):
    setUp=helpers.PopularityChallengeTests.setUp
    game=BondPopularityChallengeTests.game

    def test_confirmation_and_both_progress_displays_and_result_windows(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.game(easy_bond=True); app=CafeInteractionWindow(root,s)
        self.assertIn('人気3段階へ挑戦',app.goal_button['text'])
        app.show_goal(); window=app.goal_window
        self.assertFalse(window.enable_button.instate(['disabled']))
        self.assertIn('好感度目標を維持',window.notice.get())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.enable_button.invoke()
        self.assertEqual(before,s.core.snapshot())
        with patch('tkinter.messagebox.askyesno',return_value=True) as confirm:window.enable_button.invoke()
        self.assertIn('好感度目標',confirm.call_args.args[1])
        for text in (app.objective_progress.get(),app.results_summary.get()):
            self.assertIn('好感度目標',text); self.assertIn('人気目標',text)
        root.geometry('860x660'); window.window.geometry('500x400'); root.update()
        self.assertGreater(window.history.winfo_height(),0)
        window.window.destroy(); app.show_bond_goal()
        self.assertIn('挑戦中',app.bond_goal_window.status.get())
        app.bond_goal_window.window.destroy()
