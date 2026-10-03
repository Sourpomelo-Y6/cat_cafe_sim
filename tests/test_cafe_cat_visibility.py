"""譲渡後の非表示・履歴閲覧・空の一覧を実際の画面で確認する。"""
import os
import unittest

import test_cafe_adoption as fixtures
from cat_cafe_sim.cafe_cat_visibility import visible_cat_ids
from cat_cafe_sim.cafe_cat_details import cat_details


class AdoptionVisibilityTests(unittest.TestCase):
    setUp = fixtures.AdoptionTests.setUp
    warm = fixtures.AdoptionTests.warm
    session = fixtures.AdoptionTests.session
    offer = fixtures.AdoptionTests.offer
    reload = fixtures.AdoptionTests.reload

    def adopted_session(self):
        self.warm()
        session = self.session(seats=1)
        session.resolve_adoption(self.offer(session), 'accept')
        return session

    def test_adopted_record_survives_filter_and_save_resume(self):
        session = self.adopted_session()
        before = session.core.snapshot()
        relationships = self.store.path.read_bytes()
        self.assertEqual(visible_cat_ids(session.core), ['b', 'c'])
        self.assertEqual(visible_cat_ids(session.core, True), ['a', 'b', 'c'])
        details = cat_details(session, 'a')
        self.assertIn('譲渡先', dict(details['basic']))
        self.assertEqual(session.core.snapshot(), before)
        self.assertEqual(self.store.path.read_bytes(), relationships)
        resumed = self.reload(session)
        self.assertEqual(visible_cat_ids(resumed.core), ['b', 'c'])
        self.assertEqual(cat_details(resumed, 'a'), details)

    def test_legacy_session_shows_all_cats(self):
        session = self.session()
        self.assertIsNone(session.core.adoption)
        self.assertEqual(visible_cat_ids(self.reload(session).core), ['a', 'b', 'c'])

    def test_dispatch_is_still_visible(self):
        session = self.session(seats=1)
        session.dispatch('a')
        self.assertEqual(session.core.activity('a'), 'dispatched')
        self.assertEqual(visible_cat_ids(session.core), ['a', 'b', 'c'])


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'requires a display')
class AdoptionVisibilityGuiTests(unittest.TestCase):
    setUp = AdoptionVisibilityTests.setUp
    warm = AdoptionVisibilityTests.warm
    session = AdoptionVisibilityTests.session
    offer = AdoptionVisibilityTests.offer
    adopted_session = AdoptionVisibilityTests.adopted_session
    def root(self):
        import tkinter as tk
        root = tk.Tk()
        self.addCleanup(root.destroy)
        return root

    def test_main_roster_updates_selection_count_and_empty_state(self):
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        session = self.adopted_session()
        root = self.root()
        app = CafeInteractionWindow(root, session)
        self.addCleanup(app.stop)
        root.update()
        self.assertEqual(app.roster.get_children(), ('b', 'c'))
        self.assertIn('猫 2匹', app.status.get())
        app.show_adopted.set(True);app.refresh()
        self.assertEqual(app.roster.get_children(), ('a', 'b', 'c'))
        app.roster.selection_set('a')
        app.show_adopted.set(False);app.refresh()
        self.assertNotIn('a', app.roster.selection())
        app.show_cat_details()
        self.assertNotIn('a', app.cat_details_window.ids)
        app.cat_details_window.window.destroy()
        # Isolate the all-adopted display edge without triggering unrelated events.
        for key in session.core.cats:session.core.activities['cats'][key] = 'adopted'
        app.refresh();root.update()
        self.assertEqual(app.roster.get_children(), ())
        self.assertEqual(app.cat_selector['values'], '')
        self.assertTrue(app.cat_details_button.instate(['disabled']))
        app.show_adopted.set(True);app.refresh()
        self.assertEqual(len(app.roster.get_children()), 3)

    def test_detail_keeps_records_and_handles_hiding_last_cat(self):
        from cat_cafe_sim.cafe_cat_details import CafeCatDetailsWindow
        session = self.adopted_session()
        root = self.root()
        dialog = CafeCatDetailsWindow(root, session, 'a')
        root.update()
        self.assertTrue(dialog.show_adopted.get())
        self.assertTrue(dialog.play_button.instate(['disabled']))
        self.assertTrue(any(row[0]=='譲渡先' for row in
            (dialog.tables['basic'].item(key, 'values') for key in dialog.tables['basic'].get_children())))
        dialog.show_adopted.set(False);dialog.filter_cats()
        self.assertEqual(dialog.ids, ['b', 'c'])
        for key in session.core.cats:session.core.activities['cats'][key] = 'adopted'
        dialog.filter_cats();root.update()
        self.assertEqual(dialog.ids, [])
        self.assertTrue(dialog.play_button.instate(['disabled']))
        dialog.show_adopted.set(True);dialog.filter_cats()
        self.assertEqual(len(dialog.ids), 3)
        self.assertTrue(dialog.play_button.instate(['disabled']))

    def test_other_lists_filter_without_changing_schedule(self):
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        from cat_cafe_sim.cafe_shift_gui import CafeShiftWindow
        from cat_cafe_sim.cafe_items_gui import CafeItemsWindow
        from cat_cafe_sim.cafe_preferences_gui import CafePreferencesWindow
        from cat_cafe_sim.cafe_customers_gui import CafeCustomersWindow
        session = self.adopted_session()
        root = self.root()
        before = session.core.snapshot()
        for factory, table_name, refresh in (
            (lambda: CafeActivityWindow(root, session, lambda: None), 'cats', 'refresh'),
            (lambda: CafeShiftWindow(root, session, lambda: None), 'tree', 'refresh_schedule'),
            (lambda: CafeItemsWindow(root, session, lambda: None), 'cats', 'selection_changed'),
            (lambda: CafePreferencesWindow(root, session, 'guest-1'), 'cats', 'refresh'),
            (lambda: CafeCustomersWindow(root, session), 'cats', 'select'),
        ):
            with self.subTest(table=table_name, refresh=refresh):
                dialog = factory();root.update()
                table = getattr(dialog, table_name)
                self.assertEqual(table.get_children(), ('b', 'c'))
                dialog.show_adopted.set(True);getattr(dialog, refresh)()
                self.assertEqual(table.get_children(), ('a', 'b', 'c'))
                table.selection_set('a');root.update()
                if hasattr(dialog, 'send_button'):self.assertTrue(dialog.send_button.instate(['disabled']))
                if hasattr(dialog, 'work_button'):self.assertTrue(dialog.work_button.instate(['disabled']))
                dialog.show_adopted.set(False);getattr(dialog, refresh)();root.update()
                self.assertEqual(table.get_children(), ('b', 'c'))
                self.assertNotIn('a', table.selection())
                dialog.window.destroy()
        self.assertEqual(session.core.snapshot(), before)
