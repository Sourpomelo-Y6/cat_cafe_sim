"""目標別おまかせの開始・ログ・中断・結果確認を実画面で検証する。"""
import os
import tempfile
import time
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_autoplay_gui import autoplay_available, objective_targets
from cat_cafe_sim.core import cafe_player
from cat_cafe_sim.storage.cafe_saves import load_game


class ObjectiveGuiFixtures:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sequence = 0

    def session(self, objective, *, easy=True):
        self.sequence += 1
        conditions = starting_conditions(objective)
        conditions['store_events']['probability'] = 0
        conditions.pop('intake_request')
        if easy:
            conditions['bond'] = dict(target=1, affinity=.5)
            conditions['patron'].pop('members', None)
            conditions['patron']['target'] = 25
        return create_game(Path(self.temp.name)/str(self.sequence), conditions)


class ObjectiveAvailabilityTests(ObjectiveGuiFixtures, unittest.TestCase):
    def test_saved_native_goals_enable_autoplay_without_adding_popularity_goal(self):
        for objective in ('bond', 'patron'):
            session = self.session(objective)
            before = session.core.snapshot()
            self.assertTrue(autoplay_available(session))
            self.assertEqual(set(objective_targets(session.core)), {objective})
            self.assertEqual(session.core.snapshot(), before)
            self.assertTrue(session.core.goal['tracking_only'])

    def test_confirmed_popularity_result_does_not_stop_native_goal_again(self):
        session = self.session('bond')
        self.challenge(session)
        for stage in range(3):
            player = AutoPlayer(session, objective='bond', mode='basic', max_days=10, stop_on_goal=True)
            self.assertEqual(player.run().reason, 'goal_cleared')
            if stage<2:
                session.advance_goal();session.next_day()
        self.assertFalse(autoplay_available(session))
        session.continue_goal()
        self.assertTrue(autoplay_available(session))
        self.assertEqual(AutoPlayer(session, objective='bond', mode='clear', max_days=10,
                                   stop_on_goal=True).run().reason, 'completed')
        self.assertFalse(autoplay_available(session))

    @staticmethod
    def challenge(session):
        from cat_cafe_sim.core.cafe_popularity_challenge import rules
        selected = rules(session.core)
        selected['goal']['target'] = 101
        selected['goal']['stages'] = [dict(target=102, days=20), dict(target=103, days=20)]
        session.start_popularity_challenge(selected)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1', 'requires a display')
class ObjectiveAutoPlayGuiTests(ObjectiveGuiFixtures, unittest.TestCase):
    def app(self, objective, **kwargs):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = CafeInteractionWindow(root, self.session(objective, **kwargs))
        self.addCleanup(app.stop)
        root.update()
        self.assertTrue(app.autoplay_button.instate(['!disabled']))
        return app

    def dialog(self, app, mode='安定経営'):
        app.show_autoplay()
        window = app.autoplay_window
        window.mode.set(mode)
        window.interval_ms = 0
        return window

    def finish(self, app, window):
        deadline = time.monotonic()+60
        while window.running and time.monotonic()<deadline:app.root.update()
        self.assertFalse(window.running)
        self.assertIsNone(window.timer)

    def one_step(self, window):
        window.window.after_cancel(window.timer)
        window.timer = None
        window.interval_ms = 10000
        window.advance()

    def test_bond_completion_logs_results_and_preserves_pending_goal(self):
        app = self.app('bond')
        window = self.dialog(app)
        self.assertEqual(window.objective.get(), '好感度')
        self.assertEqual(tuple(window.objective_selector['values']), ('好感度',))
        window.start()
        self.assertTrue(window.objective_selector.instate(['disabled']))
        self.finish(app, window)
        self.assertEqual(window.player.objective, 'bond')
        self.assertEqual(window.player.result.reason, 'completed')
        self.assertFalse(app.session.core.bond_goal['continued'])
        self.assertIn('好感度目標', window.progress.get())
        self.assertIn('交流操作：', window.log.get('1.0', 'end'))
        self.assertIn('交流結果：', window.log.get('1.0', 'end'))
        self.assertIn('残り体力', window.log.get('1.0', 'end'))
        rows=[window.decision_table.item(i,'values') for i in window.decision_table.get_children()]
        self.assertTrue(any(row[2]=='交流' and '体力を残す' in row[3] for row in rows))
        self.assertTrue(window.start_button.instate(['disabled']))
        self.assertEqual(load_game(app.session.checkpoint_path)[0].core.snapshot(),app.session.core.snapshot())
        window.window.geometry('600x480');app.root.update()
        self.assertGreater(window.decision_table.winfo_height(), 40)
        window.close();app.show_bond_goal()
        self.assertIsNotNone(app.clear_results_window)

    def test_bond_cancel_during_exchange_save_resume_matches_shared_player(self):
        app = self.app('bond')
        window = self.dialog(app, '積極経営')
        window.start();self.one_step(window);self.one_step(window)
        self.assertTrue(cafe_player.active(app.session.core))
        window.stop()
        before=app.session.core.snapshot()
        self.assertEqual(window.player.result.reason,'cancelled')
        app.root.update();self.assertEqual(app.session.core.snapshot(),before)
        resumed=load_game(app.session.checkpoint_path)[0]
        reference=load_game(app.session.checkpoint_path)[0]
        window.close();app.replace_game(resumed)
        window=self.dialog(app,'積極経営')
        expected=AutoPlayer(reference,objective='bond',mode='fast',max_days=10,stop_on_goal=True).run()
        window.start();self.finish(app,window)
        self.assertEqual(window.player.result,expected)
        self.assertEqual(app.session.core.snapshot(),reference.core.snapshot())

    def test_fast_patron_recruitment_decision_and_cancel_resume(self):
        app = self.app('patron', easy=False)
        window = self.dialog(app, '積極経営')
        window.start()
        self.one_step(window)
        self.one_step(window)
        self.assertEqual(len(app.session.core.cats), 6)
        self.assertTrue(any('black' in values for values in app.session.core.cat_features.values()))
        rows = [window.decision_table.item(i, 'values') for i in window.decision_table.get_children()]
        self.assertTrue(any(row[2]=='受け入れ' and '予備資金' in row[3] for row in rows))
        self.assertIn('リン', window.log.get('1.0', 'end'))
        window.stop()
        resumed = load_game(app.session.checkpoint_path)[0]
        self.assertEqual(resumed.core.snapshot(), app.session.core.snapshot())
        window.close()
        app.replace_game(resumed)
        window = self.dialog(app, '積極経営')
        window.start()
        self.finish(app, window)
        self.assertEqual(window.player.result.reason, 'day_limit')
        self.assertEqual(window.player.result.days, 10)
        self.assertIn('訪問結果：', window.log.get('1.0', 'end'))
        self.assertEqual(len(app.session.core.cats), 6)
        self.assertEqual(load_game(app.session.checkpoint_path)[0].core.snapshot(), app.session.core.snapshot())

    def test_patron_dispatch_cancel_resume_return_log_and_result(self):
        app=self.app('patron')
        window=self.dialog(app)
        self.assertEqual(window.objective.get(),'有力者')
        window.start();self.one_step(window)
        self.assertTrue(any(e['status']=='travelling' for e in app.session.core.activities['events'].values()))
        window.stop();resumed=load_game(app.session.checkpoint_path)[0]
        self.assertEqual(resumed.core.snapshot(),app.session.core.snapshot())
        window.close();app.replace_game(resumed)
        window=self.dialog(app);window.start();self.finish(app,window)
        self.assertEqual(window.player.result.reason,'completed')
        self.assertIn('訪問結果：',window.log.get('1.0','end'))
        self.assertIn('満足度',window.progress.get())
        self.assertFalse(app.session.core.patron['continued'])
        self.assertTrue(app.autoplay_button.instate(['disabled']))
        window.close();app.show_patron()
        self.assertIsNotNone(app.clear_results_window)

    def test_basic_ten_day_limit_leaves_native_objectives_untouched(self):
        for objective in ('bond','patron'):
            with self.subTest(objective=objective):
                app=self.app(objective,easy=False)
                window=self.dialog(app,'基礎営業');window.start();self.finish(app,window)
                self.assertEqual(window.player.result.reason,'day_limit')
                self.assertEqual(window.player.result.days,10)
                self.assertEqual(sum(cafe_player.state(app.session.core)['total'].values()),0)
                self.assertFalse((app.session.core.activities or {}).get('events', {}))
                if objective=='patron':
                    for member in app.session.core.patron['rules']['members']:
                        self.assertIn(member['name'],window.progress.get())
                window.close()

    def test_goal_selector_and_other_goal_stop_then_resume(self):
        app=self.app('bond')
        ObjectiveAvailabilityTests.challenge(app.session);app.refresh()
        window=self.dialog(app,'基礎営業')
        self.assertEqual(tuple(window.objective_selector['values']),('人気','好感度'))
        self.assertEqual(window.objective.get(),'好感度')
        window.objective.set('人気');window._controls()
        self.assertIn('人気：',window.progress.get())
        window.objective.set('好感度');window.start();self.finish(app,window)
        self.assertEqual(window.player.result.reason,'goal_cleared')
        self.assertEqual(app.session.core.bond_goal['status'],'active')
        window.close();app.session.advance_goal();app.refresh()
        window=self.dialog(app);window.start();self.finish(app,window)
        self.assertEqual(window.player.result.reason,'completed')
        self.assertEqual(len(app.session.core.goal['history']), 1)
        self.assertEqual(app.session.core.goal['history'][0]['status'], 'cleared')
        self.assertIn('bond',app.session.core.clear_results)


    def test_normal_three_patrons_use_shared_dispatch_and_keep_progress_visible(self):
        app=self.app('patron',easy=False)
        window=self.dialog(app);window.start();self.finish(app,window)
        self.assertEqual(window.player.result.reason,'day_limit')
        self.assertEqual(window.player.result.days,10)
        self.assertGreater(app.session.core.patron['satisfaction'],0)
        self.assertIn('訪問結果：',window.log.get('1.0','end'))
        for member in app.session.core.patron['rules']['members']:
            self.assertIn(member['name'],window.progress.get())
        self.assertEqual(load_game(app.session.checkpoint_path)[0].core.snapshot(),app.session.core.snapshot())
        window.window.geometry('600x480');app.root.update()
        self.assertGreater(window.decision_table.winfo_height(),40)
        for button in (window.start_button, window.stop_button):
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), window.window.winfo_rootx()+window.window.winfo_width())

    def test_native_goal_stops_for_popularity_expiry_and_resumes_after_confirmation(self):
        from cat_cafe_sim.core.cafe_popularity_challenge import rules
        app=self.app('bond')
        selected=rules(app.session.core);selected['goal']['days']=1
        app.session.start_popularity_challenge(selected);app.refresh()
        window=self.dialog(app,'基礎営業');window.start();self.finish(app,window)
        self.assertEqual(window.player.result.reason,'expired')
        self.assertTrue(window.start_button.instate(['disabled']))
        self.assertEqual(app.session.core.bond_goal['status'],'active')
        window.close();app.session.continue_goal();app.refresh()
        window=self.dialog(app);window.start();self.finish(app,window)
        self.assertEqual(window.player.result.reason,'completed')

    def test_normal_bond_six_cats_finish_across_separate_ten_day_batches(self):
        app=self.app('bond',easy=False)
        outcomes=[]
        for batch in range(3):
            window=self.dialog(app);window.start();self.finish(app,window)
            outcomes.append(window.player.result.reason)
            self.assertLessEqual(window.player.result.days,10)
            saved=load_game(app.session.checkpoint_path)[0]
            self.assertEqual(saved.core.snapshot(),app.session.core.snapshot())
            window.close()
            if outcomes[-1]=='completed':break
            app.replace_game(saved)
        self.assertEqual(outcomes,['day_limit','day_limit','completed'])
        self.assertEqual(len(app.session.core.bond_goal['achieved_cats']),6)
        self.assertTrue(all(value>=80 for value in cafe_player.state(app.session.core)['affinity'].values()))
