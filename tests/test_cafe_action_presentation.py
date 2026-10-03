import unittest
import os
from types import SimpleNamespace

import test_cafe_player as fixtures
from cat_cafe_sim.cafe_action_presentation import current_scene, interaction_scene


class ActionPresentationTests(unittest.TestCase):
    setUp = fixtures.PlayerTests.setUp
    session = fixtures.PlayerTests.session

    def test_read_only_waiting_rest_and_player_interaction(self):
        s = self.session()
        cat_id = 'playtest-mike'
        before = s.core.log()
        self.assertEqual(current_scene(s)['scene'], 'normal')
        self.assertEqual(s.core.log(), before)
        s.set_shifts([])
        self.assertEqual(current_scene(s)['scene'], 'sleep')
        s.play_with_player(cat_id)
        self.assertEqual(current_scene(s)['scene'], 'normal')
        s.player_command('direct')
        before = s.core.log()
        self.assertEqual(current_scene(s)['scene'], 'play')
        self.assertEqual(s.core.log(), before)
        s.player_command('switch', 'pet')
        self.assertEqual(current_scene(s)['scene'], 'normal')
        s.player_command('direct')
        self.assertEqual(current_scene(s)['scene'], 'pet')
        s.player_command(finish=True)
        self.assertEqual(current_scene(s)['scene'], 'sleep')

    def test_unsupported_and_rejected_actions_do_not_show_wrong_pose(self):
        for mode in ('ball', 'brush', 'voice', 'presence'):
            self.assertEqual(interaction_scene([dict(action='direct', before=dict(mode=mode))]), 'normal')
        for action in ('pause', 'switch', 'connect'):
            self.assertEqual(interaction_scene([dict(action=action, before=dict(mode='teaser'))]), 'normal')
        for reaction in ('turn_away', 'confused', 'listless'):
            self.assertEqual(interaction_scene([dict(action='direct', before=dict(mode='pet'),
                                                    normal_reaction=reaction)]), 'normal')

    def test_customer_interaction_uses_only_active_record(self):
        s = self.session()
        item = SimpleNamespace(cat_id='playtest-mike', records=[dict(action='direct', before=dict(mode='pet'))])
        view_session = SimpleNamespace(core=s.core, profiles=s.profiles, active_interactions={'seat-1': item})
        self.assertEqual(current_scene(view_session)['scene'], 'pet')
        view_session.active_interactions.clear()
        self.assertEqual(current_scene(view_session)['scene'], 'normal')

    def test_sick_and_fallback_cat(self):
        s = self.session()
        s.core.cats['playtest-mike'].health_status = 'sick'
        self.assertEqual(current_scene(s)['room'], '療養スペース')
        self.assertEqual(current_scene(s)['scene'], 'sleep')
        del s.core.cats['playtest-mike']
        self.assertEqual(current_scene(s)['cat_id'], next(iter(s.core.cats)))

    @unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires a display')
    def test_live_preview_tracks_replacement_and_cancels_timer(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_action_preview_gui import CatActionPreviewWindow
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        holder = [self.session()]
        preview = CatActionPreviewWindow(root, session_provider=lambda: holder[0])
        root.update()
        self.assertEqual(preview.scene.get(), 'normal')
        holder[0].set_shifts([])
        preview.sync()
        self.assertEqual(preview.scene.get(), 'sleep')
        self.assertIn('休養スペース', preview.game_status.get())
        preview.auto.set(False)
        preview.sync()
        preview.buttons['pet'].invoke()
        self.assertEqual(preview.scene.get(), 'pet')
        holder[0] = self.session()
        preview.auto.set(True)
        preview.sync()
        self.assertEqual(preview.scene.get(), 'normal')
        self.assertIn('disabled', preview.buttons['play'].state())
        preview.window.destroy()
        self.assertIsNone(preview.timer)
        root.update()
