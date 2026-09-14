from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core.human_cat_interaction import HumanCatInteraction, InteractionConfig, verify
from cat_cafe_sim.human_cat_gui import PlaySession, history_row


class PlaySessionTests(unittest.TestCase):
    def test_gui_session_matches_cli_core_and_replay(self):
        config = InteractionConfig.load()
        ui = PlaySession(config)
        cli = HumanCatInteraction(config)
        for action in ('direct', 'direct', 'pause', 'feint', 'switch', 'adapt'):
            self.assertEqual(ui.act(action), cli.step(action))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'play.json'
            ui.save(path)
            self.assertEqual(verify(path).log(), cli.log())

    def test_restart_validates_before_replacing_and_clears_history(self):
        ui = PlaySession(InteractionConfig())
        ui.act('direct')
        old = ui.core.log()
        for values in (('abc', '1', '100'), ('nan', '1', '100'), ('1', '3', '100'), ('1', '1', '0')):
            with self.assertRaises(ValueError):
                ui.restart(*values)
            self.assertEqual(ui.core.log(), old)
        ui.restart('0', '2', '20')
        self.assertEqual(ui.core.records, [])
        self.assertEqual(ui.core.state['stamina'], 20)
        self.assertEqual(ui.act('direct')['reaction'], 'turn_away')

    def test_japanese_history_and_end(self):
        ui = PlaySession(InteractionConfig(ticks=1))
        record = ui.act('direct')
        self.assertEqual(history_row(record)[:3], (1, '素直に動かす', '好意的に応じる'))
        self.assertEqual(ui.core.valid_actions(), ())


# デスクトップ環境で明示的に有効化するウィジェット検証。
import os
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.human_cat_gui import InteractionWindow
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = InteractionWindow(self.root, InteractionConfig(ticks=3))
        self.root.update_idletasks()

    def test_buttons_history_restart_and_end(self):
        app = self.app
        app.buttons['switch'].invoke()
        self.assertTrue(app.buttons['intense'].instate(['disabled']))
        app.buttons['intense'].invoke()
        self.assertEqual(len(app.session.core.records), 1)
        app.buttons['direct'].invoke()
        app.buttons['pause'].invoke()
        self.assertTrue(all(b.instate(['disabled']) for b in app.buttons.values()))
        self.assertEqual(len(app.history.get_children()), 3)
        self.assertIn('時間になり', app.reaction.get())
        app.play.set('0')
        app.pet.set('2')
        app.stamina.set('20')
        app.restart()
        self.assertEqual(app.history.get_children(), ())
        self.assertEqual(app.session.core.config.preferences, (0, 2))
        self.assertTrue(all(b.instate(['!disabled']) for b in app.buttons.values()))
        before = app.session.core.log()
        app.stamina.set('nan')
        with patch('tkinter.messagebox.showerror') as error:
            app.restart()
            error.assert_called_once()
        self.assertEqual(app.session.core.log(), before)

    def test_save_cancel_success_and_io_error(self):
        app = self.app
        app.buttons['direct'].invoke()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''), patch.object(app.session, 'save') as save:
            app.save_log()
            save.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'ui.json')
            with patch('tkinter.filedialog.asksaveasfilename', return_value=path):
                app.save_log()
            self.assertEqual(verify(path).log(), app.session.core.log())
        with patch('tkinter.filedialog.asksaveasfilename', return_value='/unused.json'), \
                patch.object(app.session, 'save', side_effect=OSError('test error')), \
                patch('tkinter.messagebox.showerror') as error:
            app.save_log()
            error.assert_called_once()


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class SpecialWindowTests(unittest.TestCase):
    def test_special_reservations_buttons_history_and_save(self):
        import tkinter as tk
        from cat_cafe_sim.human_cat_gui import InteractionWindow
        from cat_cafe_sim.core.human_cat_special import SpecialConfig, SpecialInteraction
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = InteractionWindow(root, SpecialConfig())
        self.assertTrue(app.buttons['connect'].instate(['disabled']))
        app.session.core = SpecialInteraction(tension=100, engagement=80)
        app.refresh()
        root.update_idletasks()
        self.assertTrue(app.buttons['connect'].instate(['!disabled']))
        self.assertTrue(app.buttons['direct'].instate(['disabled']))
        self.assertIn('心をつかむ',app.special_status.get())
        app.buttons['connect'].invoke()
        self.assertIn('200',app.special_status.get())
        self.assertIn('心を開く',app.reaction.get())
        self.assertTrue(all(b.instate(['disabled']) for b in app.buttons.values()))
        self.assertEqual(len(app.history.item(app.history.get_children()[0])['values']),7)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'special.json')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=path):
                app.save_log()
            self.assertEqual(verify(path).log(), app.session.core.log())
        app.restart()
        self.assertEqual(app.session.core.state['bonus_funds'],0)
        self.assertEqual(app.session.core.state['tension'],0)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class TypesWindowTests(unittest.TestCase):
    def test_selection_personality_restart_and_specials(self):
        import tkinter as tk
        from cat_cafe_sim.human_cat_gui import InteractionWindow
        from cat_cafe_sim.core.human_cat_types import TypesConfig, TypesInteraction
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        app=InteractionWindow(root,TypesConfig())
        controls=app.type_controls
        original=app.session.core.log()
        controls.preset.set('穏やかな甘えん坊');controls.select_preset()
        target=next(label for label,key in controls.labels.items() if key=='brush')
        controls.target.set(target);app.refresh()
        self.assertEqual(app.session.core.log(),original)
        app.buttons['switch'].invoke()
        self.assertEqual(app.session.core.state['mode'],'brush')
        self.assertTrue(app.buttons['intense'].instate(['disabled']))
        self.assertTrue(app.buttons['switch'].instate(['disabled']))
        values=controls.pending.to_dict();values['type_preferences']['brush']=1.9
        controls.accept_details(values)
        self.assertEqual(app.session.core.config.personality.type_preferences[5],1)
        app.restart()
        self.assertEqual(app.session.core.config.personality.type_preferences[5],1.9)
        self.assertEqual(app.history.get_children(),())
        pending=controls.pending
        values['switch_affinity']=3
        with self.assertRaises(ValueError):controls.accept_details(values)
        self.assertEqual(controls.pending,pending)
        # Open actual editor and close without accepting: no change to staged settings.
        controls.edit();root.update_idletasks()
        dialogs=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(dialogs),1)
        dialogs[0].destroy()
        self.assertEqual(controls.pending,pending)
        app.session.core=TypesInteraction(TypesConfig(),tension=100,engagement=100)
        app.refresh()
        self.assertTrue(app.buttons['switch'].instate(['disabled']))
        app.buttons['connect'].invoke()
        self.assertIn('200',app.special_status.get())
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'types.json')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=path):app.save_log()
            self.assertEqual(verify(path).log(),app.session.core.log())


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class RelationshipWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.human_cat_relationship_gui import RelationshipWindow
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.app=RelationshipWindow(self.root,RelationshipConfig(),Path(self.temp.name)/'relations.json')
        self.root.update_idletasks()

    def test_finish_reunion_pair_switch_and_retry(self):
        app=self.app
        self.assertIn('初対面',app.greeting_text.get())
        app.buttons['direct'].invoke()
        with patch.object(app,'show_result'):
            app.finish_button.invoke()
        self.assertTrue(app.session.persisted)
        self.assertEqual(app.session.core.result()['affinity_delta'],.5)
        self.assertTrue(all(b.instate(['disabled']) for b in app.buttons.values()))
        app.restart()
        self.assertEqual(app.session.core.state['affinity_start'],.5)
        self.assertIn('再会',app.greeting_text.get())
        app.customer_id.set('guest-2');app.restart()
        self.assertEqual(app.session.core.state['affinity_start'],0)
        self.assertIn('初対面',app.greeting_text.get())
        app.buttons['direct'].invoke()
        with patch.object(app.session.store,'_write',side_effect=OSError('test failure')), \
                patch('tkinter.messagebox.showerror') as error,patch.object(app,'show_result'):
            app.finish()
            error.assert_called_once()
        self.assertFalse(app.session.persisted)
        self.assertTrue(app.persist_button.instate(['!disabled']))
        app.persist_button.invoke()
        self.assertTrue(app.session.persisted)
        self.assertEqual(app.session.store.snapshot('cat-1','guest-2')['affinity'],.5)
        app.show_result()
        self.root.update_idletasks()

    def test_log_and_actions_remain_visible_at_small_window_size(self):
        app = self.app
        self.root.deiconify()
        self.root.geometry('860x600')
        self.root.update()
        for tab in app.tabs.tabs():
            app.tabs.select(tab)
            self.root.update()
            self.assertTrue(app.history.winfo_ismapped())
            self.assertGreaterEqual(app.history.winfo_height(), 120)
            bottom = self.root.winfo_rooty() + self.root.winfo_height()
            for widget in (app.history, app.finish_button, app.buttons['direct']):
                self.assertGreaterEqual(widget.winfo_rooty(), self.root.winfo_rooty())
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)

    def test_cat_registration_persists_name_and_personality_on_reunion(self):
        app = self.app
        original = app.session.core.config.personality
        app.cat_name.set('ミケ')
        app.register_button.invoke()
        self.assertEqual(app.session.store.cat_profile('cat-1')['name'], 'ミケ')
        self.assertTrue(app.name_entry.instate(['disabled']))
        app.type_controls.pending = app.type_controls.presets['活発な探検家']
        app.customer_id.set('another-guest')
        app.restart()
        self.assertEqual(app.session.core.config.personality, original)
        self.assertEqual(app.cat_name.get(), 'ミケ')
        with patch.object(app, 'show_result'):
            app.finish()
        browser = app.show_relationships()
        self.assertEqual(browser.tree.item(browser.tree.get_children()[0], 'values')[0], 'ミケ')
        browser.dialog.destroy()
        app.cat_id.set('new-cat'); app.restart()
        self.assertEqual(app.session.core.config.personality, app.type_controls.pending)
        self.assertFalse(app.name_entry.instate(['disabled']))
        app.cat_name.set('タマ')
        with patch.object(app, 'show_result'):
            app.finish()
        self.assertEqual(app.session.store.cat_profile('new-cat')['name'], 'タマ')

    def test_relationship_list_empty_select_cancel_and_reunite(self):
        app = self.app
        browser = app.show_relationships()
        self.assertEqual(browser.tree.get_children(), ())
        self.assertTrue(browser.reunion_button.instate(['disabled']))
        self.assertFalse(app.session.store.path.exists())
        other = app.session.store.begin(app.session.base_config, 'other-cat', 'other-guest')
        other.step('direct'); other.finish(); app.session.store.apply(other)
        browser.reload()
        item = browser.tree.get_children()[0]
        values = browser.tree.item(item, 'values')
        self.assertEqual(values[:4], ('other-cat', 'other-cat', 'other-guest', '0.5'))
        self.assertIn('+0.5', values[5])
        browser.tree.selection_set(item)
        browser.selection_changed()
        self.assertTrue(browser.reunion_button.instate(['!disabled']))
        app.buttons['direct'].invoke()
        old_session = app.session
        with patch.object(app, 'resolve_current', return_value=False):
            browser.reunion_button.invoke()
        self.assertIs(app.session, old_session)
        self.assertEqual(app.cat_id.get(), 'cat-1')
        self.assertTrue(browser.dialog.winfo_exists())
        with patch.object(app, 'resolve_current', return_value=True):
            browser.reunion_button.invoke()
        self.assertEqual(app.session.core.cat_id, 'other-cat')
        self.assertEqual(app.session.core.customer_id, 'other-guest')
        self.assertEqual(app.session.core.state['affinity_start'], .5)
        self.assertIn('再会', app.greeting_text.get())
        self.assertFalse(browser.dialog.winfo_exists())

    def test_relationship_list_uses_next_store_and_handles_read_failure(self):
        from cat_cafe_sim.storage.relationships import RelationshipStore
        app = self.app
        app.next_store = RelationshipStore(Path(self.temp.name) / 'next.json')
        next_core = app.next_store.begin(app.session.base_config, 'next-cat', 'next-guest')
        next_core.finish(); app.next_store.apply(next_core)
        browser = app.show_relationships()
        self.assertEqual(len(browser.tree.get_children()), 1)
        with patch.object(browser.store, 'list_relationships', side_effect=OSError('read error')), \
                patch('tkinter.messagebox.showerror') as error:
            browser.reload()
        error.assert_called_once()
        self.assertEqual(browser.tree.get_children(), ())
        self.assertTrue(browser.reunion_button.instate(['disabled']))
        browser.reload()
        browser.tree.selection_set(browser.tree.get_children()[0])
        browser.reunite()
        self.assertEqual(app.session.store.path, app.next_store.path)
        self.assertEqual(app.session.core.cat_id, 'next-cat')

    def test_resolve_cancel_discard_and_save(self):
        import tkinter as tk
        from tkinter import ttk
        app=self.app
        app.buttons['direct'].invoke()
        before=app.session.core.log()
        def select(label):
            def click():
                for dialog in self.root.winfo_children():
                    if isinstance(dialog,tk.Toplevel):
                        for child in dialog.winfo_children():
                            if isinstance(child,ttk.Button) and child.cget('text')==label:
                                child.invoke();return
                self.fail('decision button not found')
            self.root.after(10,click)
        select('戻る')
        self.assertFalse(app.resolve_current())
        self.assertEqual(app.session.core.log(),before)
        select('試遊・未保存結果を破棄')
        self.assertTrue(app.resolve_current())
        self.assertFalse(app.session.store.path.exists())
        # Decision alone has no side effect; caller performs the transition.
        select('切り上げて結果を保存')
        self.assertTrue(app.resolve_current())
        self.assertTrue(app.session.persisted)
        self.assertEqual(app.session.store.snapshot('cat-1','guest-1')['affinity'],.5)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class CafeInteractionWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.cafe_interaction_gui import ManualCafeInteractionWindow
        from cat_cafe_sim.storage.relationships import RelationshipStore
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.session=CafeInteractionSession(store=RelationshipStore(Path(self.temp.name)/'relations.json'))
        self.app=ManualCafeInteractionWindow(self.root,self.session)

    def test_wait_select_interact_finish_and_log_visibility(self):
        self.app.wait_button.invoke()
        self.assertEqual(self.app.customer.get(),'guest-1')
        self.app.start_button.invoke()
        self.assertIsNotNone(self.session.core.active)
        self.app.buttons['direct'].invoke()
        self.app.finish_button.invoke()
        self.assertEqual(self.session.core.funds,10)
        self.assertEqual(self.session.core.cat.stamina,95)
        self.assertEqual(self.session.store.snapshot('cat-1','guest-1')['affinity'],.5)
        self.assertFalse(self.session.pending)
        self.assertGreater(len(self.app.history.get_children()),3)
        self.root.deiconify();self.root.geometry('860x600');self.root.update()
        self.assertGreaterEqual(self.app.history.winfo_height(),120)
        self.assertLessEqual(self.app.history.winfo_rooty()+self.app.history.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())

    def test_save_failure_blocks_actions_until_retry(self):
        self.app.wait_button.invoke();self.app.start_button.invoke();self.app.buttons['direct'].invoke()
        with patch.object(self.session.store,'_write',side_effect=OSError('full')), patch('tkinter.messagebox.showerror') as error:
            self.app.finish_button.invoke()
        error.assert_called_once()
        self.assertTrue(self.app.wait_button.instate(['disabled']))
        self.assertTrue(self.app.retry_button.instate(['!disabled']))
        self.app.retry_button.invoke()
        self.assertFalse(self.session.pending)
        self.assertEqual(self.session.core.funds,10)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class AutomaticCafeWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.storage.relationships import RelationshipStore
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.session=CafeInteractionSession(store=RelationshipStore(Path(self.temp.name)/'relations.json'))
        self.app=CafeInteractionWindow(self.root,self.session)
        self.addCleanup(self.app.stop)

    def drive(self):
        if self.app.timer is not None:
            self.root.after_cancel(self.app.timer)
            self.app.timer=None
        self.app.advance()

    def test_manual_assignment_starts_automatic_exchange_and_can_pause(self):
        self.root.deiconify();self.root.geometry('860x600');self.root.update()
        self.assertFalse(self.app.actions_frame.winfo_ismapped())
        self.assertFalse(self.app.finish_button.winfo_ismapped())
        self.app.run_button.invoke();self.drive();self.drive()
        self.assertFalse(self.app.running)  # 来店後は割り当てを待つ。
        self.assertEqual(self.session.core.tick,1)
        self.app.start_button.invoke()
        self.assertTrue(self.app.running)
        self.drive()
        self.assertEqual(len(self.session.core.active.records),1)
        self.app.run_button.invoke()
        before=self.session.core.log();self.drive()
        self.assertEqual(self.session.core.log(),before)
        self.assertIsNone(self.app.timer)
        self.assertGreaterEqual(self.app.history.winfo_height(),120)
        for widget in (self.app.history,self.app.start_button,self.app.run_button):
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())

    def test_auto_assignment_to_closing_and_single_timer(self):
        self.app.auto_assign.set(True);self.app.refresh()
        self.assertTrue(self.app.start_button.instate(['disabled']))
        self.app.run_button.invoke()
        timer=self.app.timer;self.app.schedule()
        self.assertEqual(self.app.timer,timer)
        for _ in range(50):
            if not self.app.running:break
            self.drive()
        self.assertTrue(self.session.core.closed)
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)
        self.assertFalse(self.session.pending)

    def test_auto_save_failure_pauses_until_retry_and_explicit_resume(self):
        from dataclasses import replace
        self.session.interaction_config=replace(self.session.interaction_config,ticks=1)
        self.app.auto_assign.set(True);self.app.toggle();self.drive()
        with patch.object(self.session.store,'_write',side_effect=OSError('full')),patch('tkinter.messagebox.showerror'):
            self.drive()
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)
        self.assertTrue(self.app.run_button.instate(['disabled']))
        self.app.retry_button.invoke()
        self.assertFalse(self.session.pending)
        self.assertFalse(self.app.running)
        self.assertEqual(self.session.core.funds,10)
        self.app.run_button.invoke()
        self.assertTrue(self.app.running)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class CafeRosterWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.storage.relationships import RelationshipStore
        from cat_cafe_sim.core.human_cat_types import load_presets
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        store=RelationshipStore(Path(self.temp.name)/'relations.json')
        store.register_cat('cat-a','ミケ',load_presets()['穏やかな甘えん坊'])
        store.register_cat('cat-b','タマ',load_presets()['活発な探検家'])
        self.session=CafeInteractionSession(store=store)
        self.app=CafeInteractionWindow(self.root,self.session)
        self.addCleanup(self.app.stop)

    def test_roster_selection_assigns_chosen_cat_and_preserves_other_stamina(self):
        self.session.step();self.app.refresh()
        rows=[self.app.roster.item(item,'values') for item in self.app.roster.get_children()]
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][:4],('タマ（cat-b）','活発な探検家','100','0'))
        self.app.cat_choice.set('タマ（cat-b）');self.app.refresh();self.app.start_button.invoke()
        self.app.stop()
        self.assertEqual(self.session.core.active.cat_id,'cat-b')
        self.session.automatic_step(auto_assign=False);self.app.refresh()
        self.assertEqual(self.session.core.cats['cat-b'].stamina,95)
        self.assertEqual(self.session.core.cats['cat-a'].stamina,100)
        self.root.deiconify();self.root.geometry('860x600');self.root.update()
        self.assertGreaterEqual(self.app.history.winfo_height(),120)
        self.assertLessEqual(self.app.history.winfo_rooty()+self.app.history.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())

    def test_unavailable_cat_cannot_be_assigned_but_other_can(self):
        self.session.step()
        self.session.core.cats['cat-a'].health_status='sick'
        self.app.refresh()
        self.assertTrue(self.app.start_button.instate(['disabled']))
        self.app.cat_choice.set('タマ（cat-b）');self.app.refresh()
        self.assertTrue(self.app.start_button.instate(['!disabled']))
        self.app.auto_assign.set(True);self.app.refresh()
        self.session.automatic_step()
        self.assertEqual(self.session.core.active.cat_id,'cat-b')


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class MultiSeatCafeWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.storage.relationships import RelationshipStore
        from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        store=RelationshipStore(Path(self.temp.name)/'relations.json');add_playtest_cats(store)
        self.session=CafeInteractionSession(store=store,cafe_config=replace(Config.load(),arrival_ticks=(0,0)))
        self.app=CafeInteractionWindow(self.root,self.session);self.addCleanup(self.app.stop)

    def test_two_manual_assignments_and_visible_seat_status(self):
        self.session.step();self.app.refresh()
        labels=list(self.app.cat_labels)
        self.app.cat_choice.set(labels[0]);self.app.seat_choice.set('seat-2')
        self.app.refresh();self.app.start_button.invoke();self.app.stop()
        self.assertIn('seat-2',self.session.active_interactions)
        self.app.cat_choice.set(labels[1]);self.app.refresh()
        self.assertEqual(self.app.seat_choice.get(),'seat-1')
        self.app.start_button.invoke();self.app.stop()
        self.assertEqual(len(self.session.active_interactions),2)
        self.session.automatic_step();self.app.refresh()
        for key in ('seat-1','seat-2'):
            self.assertIn(key,self.app.details.get())
        self.assertTrue(self.app.start_button.instate(['disabled']))
        self.root.deiconify();self.root.geometry('860x600');self.root.update()
        self.assertGreaterEqual(self.app.history.winfo_height(),120)
        self.assertLessEqual(self.app.history.winfo_rooty()+self.app.history.winfo_height(),
                             self.root.winfo_rooty()+self.root.winfo_height())

    def test_auto_assignment_uses_two_seats_and_completion_is_shown(self):
        from dataclasses import replace
        self.session.interaction_config=replace(self.session.interaction_config,ticks=1)
        self.app.auto_assign.set(True);self.app.refresh()
        self.session.automatic_step();self.session.automatic_step();self.app.refresh()
        self.assertEqual(len(self.session.core.outcomes),2)
        self.assertIn('直近の会計',self.app.details.get())
        rows=[self.app.history.item(item,'values')[1] for item in self.app.history.get_children()]
        self.assertTrue(any('seat-1' in row and '会計' in row for row in rows))
        self.assertTrue(any('seat-2' in row and '会計' in row for row in rows))


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class CafeSaveWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.storage.relationships import RelationshipStore
        from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.store=RelationshipStore(Path(self.temp.name)/'relations.json');add_playtest_cats(self.store)
        self.session=CafeInteractionSession(store=self.store,cafe_config=replace(Config.load(),arrival_ticks=(0,0,1)))
        self.session.automatic_step();self.session.automatic_step()
        self.app=CafeInteractionWindow(self.root,self.session);self.addCleanup(self.app.stop)
        self.path=Path(self.temp.name)/'day.json'

    def test_history_empty_two_days_and_pause(self):
        self.app.toggle()
        self.app.history_button.invoke()
        window=self.app.history_window
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)
        self.assertEqual(len(window.days.get_children()),0)
        window.window.destroy()
        for day in (1,2):
            while not self.session.core.closed:
                self.session.automatic_step()
            if day==1:self.session.next_day()
        self.app.history_button.invoke()
        window=self.app.history_window
        self.addCleanup(window.window.destroy)
        self.assertEqual(len(window.days.get_children()),2)
        self.assertEqual(len(window.cats.get_children()),2*len(self.session.core.cats))
        self.root.deiconify()
        window.window.deiconify()
        window.window.geometry('640x420')
        self.root.update()
        self.assertGreater(window.days.winfo_height(),30)
        self.assertGreater(window.cats.winfo_height(),30)

    def test_closed_result_cancel_and_next_day_pause(self):
        self.assertIn('disabled',self.app.day_button.state())
        while not self.session.core.closed:
            self.session.automatic_step()
        self.app.refresh()
        with patch('tkinter.messagebox.askyesno',return_value=False) as dialog:
            self.app.day_button.invoke()
        self.assertIn('売上',dialog.call_args.args[1])
        self.assertIn('親しみ',dialog.call_args.args[1])
        self.assertEqual(self.session.core.day,1)
        with patch('tkinter.messagebox.askyesno',return_value=True):
            self.app.day_button.invoke()
        self.assertEqual(self.session.core.day,2)
        self.assertIn('2日目',self.app.status.get())
        self.assertIn('disabled',self.app.day_button.state())
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)

    def test_save_open_restores_both_seats_and_pauses_timer(self):
        self.app.auto_assign.set(True);self.app.toggle()
        before=self.session.core.snapshot()
        with patch('tkinter.filedialog.asksaveasfilename',return_value=str(self.path)):
            self.app.save_button.invoke()
        self.assertFalse(self.app.running);self.assertIsNone(self.app.timer)
        self.session.automatic_step();self.app.refresh()
        with patch('tkinter.filedialog.askopenfilename',return_value=str(self.path)),patch('tkinter.messagebox.askyesnocancel',return_value=False):
            self.app.open_button.invoke()
        self.assertIsNot(self.app.session,self.session)
        self.assertEqual(self.app.session.core.snapshot(),before)
        self.assertTrue(self.app.auto_assign.get())
        self.assertFalse(self.app.running);self.assertIsNone(self.app.timer)
        self.assertEqual(len(self.app.session.active_interactions),2)
        self.app.run_button.invoke()
        self.assertTrue(self.app.running)

    def test_pending_loaded_result_retry_uses_loaded_session(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        from cat_cafe_sim.storage.relationships import RelationshipStore
        from cat_cafe_sim.storage.cafe_saves import save_game
        other_store=RelationshipStore(Path(self.temp.name)/'other.json')
        other=CafeInteractionSession(store=other_store,cafe_config=replace(Config.load(),arrival_ticks=(0,)),
                                     interaction_config=replace(RelationshipConfig(),ticks=1))
        other.automatic_step()
        with patch.object(other_store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):other.automatic_step()
        save_game(other,self.path,auto_assign=True)
        original=self.store.path.read_bytes()
        with patch('tkinter.filedialog.askopenfilename',return_value=str(self.path)),patch('tkinter.messagebox.askyesnocancel',return_value=False):
            self.app.open_game()
        self.assertTrue(self.app.retry_button.instate(['!disabled']))
        self.assertTrue(self.app.run_button.instate(['disabled']))
        self.app.retry_button.invoke()
        self.assertFalse(self.app.session.pending)
        self.assertEqual(other_store.snapshot('cat-1','guest-1')['affinity'],.5)
        self.assertEqual(self.store.path.read_bytes(),original)
        self.assertFalse(self.app.running)

    def test_failed_or_cancelled_open_preserves_current_session(self):
        self.path.write_text('{bad')
        before=self.session.core.snapshot()
        with patch('tkinter.filedialog.askopenfilename',return_value=str(self.path)),patch('tkinter.messagebox.showerror') as error:
            self.app.open_game()
        error.assert_called_once()
        with patch('tkinter.filedialog.askopenfilename',return_value=''):
            self.app.open_game()
        self.assertIs(self.app.session,self.session)
        self.assertEqual(self.session.core.snapshot(),before)

    def test_close_saves_active_exchange_without_finishing_and_cancel_keeps_window(self):
        from cat_cafe_sim.storage.cafe_saves import load_game
        before=self.session.core.snapshot()
        with patch.object(self.root,'destroy') as destroy,patch('tkinter.messagebox.askyesnocancel',return_value=True),patch('tkinter.filedialog.asksaveasfilename',return_value=''):
            self.app.close();destroy.assert_not_called()
        with patch.object(self.root,'destroy') as destroy,patch('tkinter.messagebox.askyesnocancel',return_value=True),patch('tkinter.filedialog.asksaveasfilename',return_value=str(self.path)):
            self.app.close();destroy.assert_called_once()
        self.assertEqual(load_game(self.path)[0].core.snapshot(),before)
        self.assertEqual(len(self.session.active_interactions),2)
