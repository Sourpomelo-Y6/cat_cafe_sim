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

    def test_dashboard_tabs_preserve_state_keep_log_visible_and_pause(self):
        import copy
        app = self.app
        self.root.deiconify()
        self.root.geometry('860x600')
        self.root.update()
        before = copy.deepcopy(self.session.core.log())
        for page in (app.preparation_page, app.results_page, app.business_page):
            app.pages.select(page)
            self.root.update()
            self.assertEqual(self.session.core.log(), before)
            self.assertTrue(app.history.winfo_ismapped())
            self.assertGreaterEqual(app.history.winfo_height(), 120)
            self.assertLessEqual(app.history.winfo_rooty() + app.history.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
        self.assertGreaterEqual(app.roster.winfo_height(), 100)
        app.running = True
        app.timer = self.root.after(10000, lambda: None)
        app.pages.select(app.preparation_page)
        self.root.update()
        self.assertFalse(app.running)
        self.assertIsNone(app.timer)
        app.pages.select(app.business_page)
        self.root.update()
        self.assertFalse(app.running)

    def test_bond_goal_start_cancel_progress_attention_and_continue(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        self.app.replace_game(CafeInteractionSession(store=self.store), False)
        app = self.app
        self.root.deiconify()
        self.root.geometry('860x660')
        app.session.enable_management()
        app.show_bond_goal()
        window = app.bond_goal_window
        window.window.geometry('580x420')
        self.root.update()
        self.assertEqual(app.pages.select(), str(app.results_page))
        self.assertTrue(app.bond_goal_button.winfo_ismapped())
        self.assertLessEqual(app.instructions.winfo_rooty() + app.instructions.winfo_height(),
                             app.results_page.winfo_rooty() + app.results_page.winfo_height())
        self.assertGreaterEqual(app.history.winfo_height(), 120)
        self.assertGreaterEqual(window.cats.winfo_height(), 100)
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.enable_button.invoke()
        self.assertIsNone(app.session.core.bond_goal)
        with patch('cat_cafe_sim.cafe_bond_goal_gui.rules', return_value=dict(target=1, affinity=.5)), \
                patch('tkinter.messagebox.askyesno', return_value=True):
            window.enable_button.invoke()
        window.window.destroy()
        key = next(iter(app.session.core.cats))
        app.session.play_with_player(key)
        app.session.player_command('direct')
        app.session.player_command(finish=True)
        app.refresh()
        self.root.update()
        self.assertIn('disabled', app.run_button.state())
        app.attention_button.invoke()
        window = app.bond_goal_window
        self.root.update()
        self.assertIn('1 / 1', window.status.get())
        self.assertEqual(window.cats.item(key, 'values')[-1], '対象')
        window.continue_button.invoke()
        self.assertTrue(app.session.core.bond_goal['continued'])
        self.assertNotIn('disabled', app.run_button.state())

    def test_customer_directory_pause_layout_and_named_assignment(self):
        import copy
        from cat_cafe_sim.cafe_customers import customer_label
        app = self.app
        self.root.deiconify()
        self.root.geometry('860x660')
        app.running = True
        app.timer = self.root.after(10000, lambda: None)
        before = copy.deepcopy(app.session.core.log())
        store_before = self.store.path.read_bytes()
        app.show_customers()
        window = app.customers_window
        window.window.geometry('660x520')
        self.root.update()
        self.assertFalse(app.running)
        self.assertIsNone(app.timer)
        self.assertEqual(app.session.core.log(), before)
        self.assertEqual(self.store.path.read_bytes(), store_before)
        self.assertEqual(app.pages.select(), str(app.preparation_page))
        for table in (window.customers, window.cats):
            self.assertGreaterEqual(table.winfo_height(), 100)
            self.assertLessEqual(table.winfo_rooty() + table.winfo_height(),
                                 window.window.winfo_rooty() + window.window.winfo_height())
        self.assertIn('佐藤', window.customers.item('guest-1', 'values')[0])
        self.assertGreaterEqual(app.history.winfo_height(), 120)
        window.customers.selection_set('guest-2')
        window.select()
        self.assertIn('guest-2', window.details.get())
        window.window.destroy()
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        app.replace_game(CafeInteractionSession(store=self.store))
        app.session.step()
        app.pages.select(app.business_page)
        app.refresh()
        customer_id = app.session.core.queue[0]
        app.queue.set(customer_label(customer_id))
        app.queue.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(app.customer.get(), customer_id)
        self.assertEqual(app.queue.get(), customer_label(customer_id))
        app.start_button.invoke()
        self.assertTrue(any(item.customer_id == customer_id for item in app.session.active_interactions.values()))

    def test_dashboard_direct_equipment_and_event_routes(self):
        app = self.app
        app.show_equipment()
        self.assertEqual(app.pages.select(), str(app.preparation_page))
        self.assertEqual(app.equipment_window.window.master, self.root)
        app.equipment_window.window.destroy()
        app.show_adoption()
        self.assertEqual(app.pages.select(), str(app.results_page))
        self.assertEqual(app.adoption_window.window.master, self.root)

    def test_goal_enable_clear_resume_and_layout(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        from cat_cafe_sim.core.cafe_goal import rules, pending
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        self.app.session=CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),opening_ticks=2,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        self.app.session.enable_management()
        self.app.logged=0;self.app.refresh()
        self.app.goal_button.invoke();window=self.app.goal_window
        with patch('tkinter.messagebox.askyesno',return_value=False):window.enable_button.invoke()
        self.assertIsNone(self.app.session.core.goal)
        with patch('cat_cafe_sim.cafe_goal_gui.rules',return_value=dict(rules(),target=105)), patch('tkinter.messagebox.askyesno',return_value=True):
            window.enable_button.invoke()
        self.assertIn('100 / 105',self.app.instructions.cget('text'))
        window.window.destroy()
        while not self.app.session.core.closed:self.app.session.automatic_step()
        self.app.refresh()
        self.assertTrue(pending(self.app.session.core))
        self.assertIn('disabled',self.app.day_button.state())
        save_game(self.app.session,self.path)
        self.app.session,_=load_game(self.path)
        self.app.logged=0;self.app.refresh()
        self.app.goal_button.invoke();window=self.app.goal_window
        self.root.deiconify();self.root.geometry('860x600')
        window.window.geometry('500x300');self.root.update()
        self.assertIn('クリア',window.status.get())
        for widget in (self.app.goal_button, window.continue_button):
            self.assertTrue(widget.winfo_ismapped())
            parent=self.root if widget==self.app.goal_button else window.window
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),parent.winfo_rootx()+parent.winfo_width())
        self.assertLessEqual(window.continue_button.winfo_rooty()+window.continue_button.winfo_height(),window.window.winfo_rooty()+window.window.winfo_height())
        window.continue_button.invoke()
        self.assertFalse(pending(self.app.session.core))
        self.assertNotIn('disabled',self.app.day_button.state())
        self.assertIn('disabled',window.continue_button.state())
        window.window.destroy()
        self.app.session.next_day()
        save_game(self.app.session,self.path)
        self.assertTrue(load_game(self.path)[0].core.goal['continued'])

    def test_recruitment_confirmation_save_resume_roster_choices_and_layout(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        self.app.session=CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),initial_funds=401))
        self.app.logged=0;self.app.refresh()
        self.app.activity_button.invoke();activity=self.app.activity_window
        activity.recruitment_button.invoke();window=activity.recruitment_window
        self.root.deiconify();window.window.deiconify()
        window.window.geometry('500x440');self.root.update()
        for widget in (window.receive_button,window.close_button,window.cats,window.details):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(),15)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                 window.window.winfo_rooty()+window.window.winfo_height())
        key=window.cats.selection()[0]
        self.assertIn('201',window.notice.get())
        with patch('tkinter.messagebox.askyesno',return_value=False):
            window.receive_button.invoke()
        self.assertNotIn(key,self.app.session.core.cats)
        with patch.object(self.store,'_write',side_effect=OSError('full')), \
                patch('tkinter.messagebox.askyesno',return_value=True), \
                patch('tkinter.messagebox.showerror') as error:
            window.receive_button.invoke()
            error.assert_called_once()
        self.assertEqual(self.app.session.core.funds,401)
        with patch('tkinter.messagebox.askyesno',return_value=True):
            window.receive_button.invoke()
        self.assertEqual(self.app.session.core.funds,201)
        self.assertIn(key,self.app.roster.get_children())
        self.assertIn(key,self.app.cat_labels.values())
        self.assertIn('disabled',window.receive_button.state())
        window.close_button.invoke();activity.close_button.invoke()
        self.app.roster.selection_set(key)
        self.app.cat_details_button.invoke()
        details=self.app.cat_details_window
        self.assertIn('ハル',str([details.tables['basic'].item(i)['values'] for i in details.tables['basic'].get_children()]))
        details.window.destroy()
        self.app.session.set_shifts([key])
        self.app.refresh()
        self.app.session.automatic_step()
        label=next(label for label,value in self.app.cat_labels.items() if value==key)
        self.app.cat_choice.set(label);self.app.refresh()
        self.app.start_button.invoke()
        self.assertEqual(next(iter(self.app.session.active_interactions.values())).cat_id,key)
        save_game(self.app.session,self.path)
        self.app.session,_=load_game(self.path)
        self.app.logged=0;self.app.refresh()
        self.app.activity_button.invoke();activity=self.app.activity_window
        activity.recruitment_button.invoke();window=activity.recruitment_window
        self.assertIn('受入済み',str(window.cats.item(key)['values']))
        other=next(k for k in window.cats.get_children() if k!=key)
        window.cats.selection_set(other);window.selection_changed()
        self.assertIn('disabled',window.receive_button.state())
        window.close_button.invoke();activity.close_button.invoke()

    def test_rest_space_purchase_forecast_and_history(self):
        from dataclasses import asdict, replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.cafe_health import HealthRules
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        keys = list(self.session.core.cats)
        core = MultiSeatCafeCore(replace(Config.load(), initial_funds=1000, opening_ticks=2, arrival_ticks=(0,0)), cat_ids=keys, compact=True)
        core.set_shifts(keys, dict(max_fatigue=100, fatigue_per_service_tick=40, rest_day_recovery=20))
        core.enable_health(asdict(HealthRules(max_probability=0)))
        self.app.session = CafeInteractionSession(core=core, store=self.store, interaction_config=replace(RelationshipConfig(), ticks=1))
        while not core.closed:
            self.app.session.automatic_step()
        self.app.session.next_day()
        key = next(k for k in keys if core.cats[k].fatigue == 40)
        self.app.logged = 0
        self.app.refresh()
        funds = core.funds
        self.app.expansion_button.invoke()
        expansion = self.app.expansion_window
        expansion.equipment_button.invoke()
        window = expansion.equipment_window
        self.assertIn('疲労回復＋10', window.details.get())
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.purchase_button.invoke()
        self.assertIsNone(core.rest_space)
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.purchase_button.invoke()
        self.assertEqual(core.funds, funds-400)
        self.assertEqual(core.cats[key].fatigue, 40)
        self.assertIn('disabled', window.purchase_button.state())
        self.assertIn('設置済み', window.status.get())
        self.root.deiconify()
        window.window.geometry('500x340')
        self.root.update()
        self.assertTrue(window.purchase_button.winfo_ismapped())
        self.assertLessEqual(window.close_button.winfo_rooty()+window.close_button.winfo_height(), window.window.winfo_rooty()+window.window.winfo_height())
        window.close_button.invoke()
        expansion.close_button.invoke()
        self.app.shift_button.invoke()
        shifts = self.app.shift_window
        self.assertEqual(shifts.forecasts[key]['rest']['fatigue'], 10)
        shifts.window.destroy()
        self.app.session.day_off()
        self.assertEqual(core.cats[key].fatigue, 10)
        self.app.refresh()
        self.app.history_button.invoke()
        history = self.app.history_window
        row = history.days.get_children()[-1]
        self.assertEqual(history.days.set(row, '設備費用'), '400')
        history.window.destroy()

    def test_expansion_confirmation_three_seats_layout_and_history(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        self.app.session = CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(), initial_funds=1000, opening_ticks=4, arrival_ticks=(0,0,0)),
            interaction_config=replace(RelationshipConfig(), ticks=2))
        self.app.logged = 0
        self.app.refresh()
        self.app.expansion_button.invoke()
        window = self.app.expansion_window
        self.assertIn('2席 → 3席', window.details.get())
        self.assertIn('500', window.details.get())
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.purchase_button.invoke()
        self.assertEqual(len(self.app.session.core.seats), 2)
        self.assertEqual(self.app.session.core.funds, 1000)
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.purchase_button.invoke()
        self.assertIn('購入済み', window.notice.get())
        self.assertIn('disabled', window.purchase_button.state())
        self.assertIn('seat-3', self.app.seat_selector['values'])
        self.assertEqual(self.app.session.core.funds, 500)
        window.close_button.invoke()
        self.app.session.step()
        for i, key in enumerate(list(self.app.session.core.cats)[:3], 1):
            self.app.session.start(f'guest-{i}', key, f'seat-{i}')
        self.app.refresh()
        self.root.deiconify()
        self.root.geometry('860x600')
        self.root.update()
        self.assertIn('seat-3', self.app.details.get())
        self.assertGreaterEqual(self.app.history.winfo_height(), 100)
        while not self.app.session.core.closed:
            self.app.session.automatic_step()
        self.app.refresh()
        self.app.history_button.invoke()
        history = self.app.history_window
        row = history.days.get_children()[0]
        self.assertEqual(history.days.set(row, '席数'), '3')
        self.assertEqual(history.days.set(row, '増設費用'), '500')
        history.window.destroy()

    def test_customer_preferences_preview_details_candidates_and_layout(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        self.app.session = CafeInteractionSession(store=self.store)
        keys = list(self.app.session.core.cats)
        self.app.session.core.initialize_preferences({keys[0]: ['white', 'long_hair'], keys[1]: ['black', 'short_hair']},
                                                    dict(pool=['white'], tension_multiplier=1.25))
        self.app.session.step()
        self.app.logged = 0
        self.app.refresh()
        self.assertIn('白猫好き', self.app.details.get())
        self.assertIn('1.25', self.app.details.get())
        before = self.app.session.core.snapshot()
        self.app.compatibility_button.invoke()
        window = self.app.compatibility_window
        self.assertIn('白猫好き', window.notice.get())
        self.assertIn('一致：', window.cats.set(keys[0], '相性'))
        self.assertIn('一致なし', window.cats.set(keys[1], '相性'))
        self.root.deiconify()
        window.window.geometry('500x320')
        self.root.update()
        for widget in (window.cats, window.close_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(), 15)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), window.window.winfo_rooty()+window.window.winfo_height())
        self.assertEqual(self.app.session.core.snapshot(), before)
        window.close_button.invoke()
        self.app.roster.selection_set(keys[0])
        self.app.cat_details_button.invoke()
        details = self.app.cat_details_window
        self.assertIn('白猫・長毛', str([details.tables['basic'].item(i)['values'] for i in details.tables['basic'].get_children()]))
        details.window.destroy()
        self.app.session.start('guest-1', keys[0])
        self.assertEqual(self.app.session.core.active.config.customer_tension_multiplier, 1.25)
        self.app.refresh()
        self.root.geometry('860x600')
        self.root.update()
        self.assertGreaterEqual(self.app.history.winfo_height(), 100)

    def test_patron_enable_dispatch_clear_and_continue(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.cafe_patron import rules
        self.app.session = CafeInteractionSession(store=self.store)
        self.app.session.enable_management()
        self.app.logged = 0
        self.app.refresh()
        self.app.activity_button.invoke()
        activity = self.app.activity_window
        activity.patron_button.invoke()
        window = activity.patron_window
        selected = rules()
        selected['target'] = 25
        with patch('cat_cafe_sim.cafe_patron_gui.rules', return_value=selected), \
                patch('tkinter.messagebox.askyesno', return_value=False):
            window.enable_button.invoke()
        self.assertIsNone(self.app.session.core.patron)
        with patch('cat_cafe_sim.cafe_patron_gui.rules', return_value=selected), \
                patch('tkinter.messagebox.askyesno', return_value=True):
            window.enable_button.invoke()
        self.assertIn('0 / 25', window.status.get())
        window.close_button.invoke()
        activity.destination_choice.current(3)
        activity.select_destination()
        with patch('tkinter.messagebox.askyesno', return_value=True):
            activity.send_button.invoke()
        self.app.session.day_off()
        self.app.session.day_off()
        activity.refresh()
        activity.receive_button.invoke()
        self.assertIn('disabled', self.app.run_button.state())
        activity.patron_button.invoke()
        window = activity.patron_window
        self.assertIn('25 / 25', window.status.get())
        self.assertIn('目標達成', window.notice.get())
        self.root.deiconify()
        window.window.geometry('500x320')
        self.root.update()
        self.assertTrue(window.continue_button.winfo_ismapped())
        window.continue_button.invoke()
        self.assertTrue(self.app.session.core.patron['continued'])
        self.assertNotIn('disabled', self.app.run_button.state())
        window.close_button.invoke()
        activity.close_button.invoke()

    def test_dispatch_destination_selection_conditions_and_confirmation(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.cafe_traits import definitions
        self.app.session = CafeInteractionSession(store=self.store)
        keys = list(self.app.session.core.cats)
        self.app.session.core.initialize_traits({keys[1]: definitions()['outgoing']})
        self.app.logged = 0
        self.app.refresh()
        self.app.activity_button.invoke()
        window = self.app.activity_window
        self.assertEqual(len(window.destination_choice['values']), 3)
        window.destination_choice.current(2)
        window.select_destination()
        window.cats.selection_set(keys[0])
        window.buttons()
        self.assertIn('disabled', window.send_button.state())
        self.assertIn('外出好き', window.selection_info.get())
        window.cats.selection_set(keys[1])
        window.buttons()
        self.assertNotIn('disabled', window.send_button.state())
        self.assertIn('562.5', window.selection_info.get())
        with patch('tkinter.messagebox.askyesno', return_value=False) as confirm:
            window.send_button.invoke()
            self.assertIn('郊外への出張訪問：3日間', confirm.call_args.args[1])
        self.assertEqual(self.app.session.core.activity(keys[1]), 'cafe')
        with patch('tkinter.messagebox.askyesno', return_value=True):
            window.send_button.invoke()
        event = next(iter(self.app.session.core.activities['events'].values()))
        self.assertEqual(event['destination']['id'], 'out_of_town_visit')
        self.assertEqual(event['remaining'], 3)
        self.assertEqual(window.events.set(event['id'], '報酬'), '562.5')
        window.close_button.invoke()

    def test_periodic_recruitment_schedule_and_new_candidates(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        self.app.session = CafeInteractionSession(store=self.store)
        self.app.logged = 0
        self.app.refresh()
        self.app.activity_button.invoke()
        activity = self.app.activity_window
        activity.recruitment_button.invoke()
        window = activity.recruitment_window
        self.assertIn('4日目', window.schedule.get())
        original = set(window.cats.get_children())
        window.close_button.invoke()
        activity.close_button.invoke()
        for _ in range(3):
            self.app.session.day_off()
        self.app.refresh()
        self.app.activity_button.invoke()
        activity = self.app.activity_window
        activity.recruitment_button.invoke()
        window = activity.recruitment_window
        self.assertEqual(len(window.cats.get_children()), 6)
        self.assertTrue(original <= set(window.cats.get_children()))
        self.assertIn('7日目', window.schedule.get())
        added = next(key for key in window.cats.get_children() if key not in original)
        window.cats.selection_set(added)
        window.selection_changed()
        values = [window.details.item(key)['values'] for key in window.details.get_children()]
        self.assertIn(['提示日', '4日目'], values)
        window.close_button.invoke()
        activity.close_button.invoke()

    def test_management_enable_missing_return_cost_game_over_and_layout(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        from cat_cafe_sim.core.cafe_management import rules, waiting, is_over
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        self.app.session=CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),opening_ticks=2,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        self.app.logged=0;self.app.refresh()
        self.app.activity_button.invoke();activity=self.app.activity_window
        activity.management_button.invoke();window=activity.management_window
        selected=dict(rules(),stress_per_service_tick=2,runaway_threshold=2,return_stress=0,kitten_probability=1,kitten_cost=2000)
        with patch('cat_cafe_sim.cafe_management_gui.rules',return_value=selected), \
                patch('tkinter.messagebox.askyesno',return_value=False):
            window.enable_button.invoke()
        self.assertIsNone(self.app.session.core.management)
        with patch('cat_cafe_sim.cafe_management_gui.rules',return_value=selected), \
                patch('tkinter.messagebox.askyesno',return_value=True):
            window.enable_button.invoke()
        self.assertEqual(self.app.session.core.funds,1000)
        key=next(iter(self.app.session.core.cats))
        self.assertEqual(self.app.roster.set(key,'stress'),'0')
        self.assertIn('disabled',window.enable_button.state())
        window.close_button.invoke();activity.close_button.invoke()
        while not self.app.session.core.closed:self.app.session.automatic_step()
        self.app.session.next_day();self.app.session.day_off();self.app.session.day_off()
        save_game(self.app.session,self.path)
        self.app.session,_=load_game(self.path)
        self.app.logged=0;self.app.refresh()
        self.assertTrue(waiting(self.app.session.core))
        self.app.activity_button.invoke();activity=self.app.activity_window
        activity.management_button.invoke();window=activity.management_window
        self.root.deiconify();window.window.deiconify()
        window.window.geometry('500x440');self.root.update()
        for widget in (window.return_button,window.close_button,window.cats,window.events):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(),15)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                 window.window.winfo_rooty()+window.window.winfo_height())
        with patch('tkinter.messagebox.askyesno',return_value=False):
            window.return_button.invoke()
        self.assertFalse(is_over(self.app.session.core))
        with patch('tkinter.messagebox.askyesno',return_value=True):
            window.return_button.invoke()
        self.assertTrue(is_over(self.app.session.core))
        self.assertIn('ゲームオーバー',window.notice.get())
        self.assertIn('ゲームオーバー',self.app.notice.get())
        self.assertIn('disabled',self.app.run_button.state())
        self.assertIn('disabled',self.app.day_off_button.state())
        self.assertIn('disabled',window.return_button.state())
        window.close_button.invoke();activity.close_button.invoke()
        save_game(self.app.session,self.path)
        loaded,_=load_game(self.path)
        self.assertTrue(is_over(loaded.core))

    def test_adoption_toggle_offer_save_confirm_and_small_window(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        from cat_cafe_sim.core.cafe_adoption import waiting
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        key=next(iter(self.session.core.cats))
        warm=self.store.begin(replace(RelationshipConfig(),ticks=1,
            affinity_favorable=80,affinity_enthusiastic=80),key,'guest-1')
        warm.step('direct');self.store.apply(warm)
        self.app.session=CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(),opening_ticks=4,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        self.app.logged=0;self.app.refresh()
        self.app.activity_button.invoke()
        activity=self.app.activity_window
        activity.adoption_button.invoke()
        adoption=activity.adoption_window
        self.assertFalse(adoption.option.get())
        adoption.toggle.invoke()
        self.assertTrue(self.app.session.core.adoption['enabled'])
        adoption.close_button.invoke();activity.close_button.invoke()
        self.app.session.automatic_step()
        self.app.auto_assign.set(True);self.app.running=True
        with patch('tkinter.messagebox.showerror') as errors:
            self.app.advance()
            errors.assert_not_called()
        self.assertFalse(self.app.running)
        self.assertTrue(waiting(self.app.session.core))
        self.assertIn('disabled',self.app.run_button.state())
        save_game(self.app.session,self.path)
        self.app.session,_=load_game(self.path)
        self.app.logged=0;self.app.refresh()
        self.app.activity_button.invoke();activity=self.app.activity_window
        self.assertIn('回答待ち1件',activity.adoption_button.cget('text'))
        activity.adoption_button.invoke();adoption=activity.adoption_window
        self.root.deiconify();adoption.window.deiconify()
        adoption.window.geometry('500x400');self.root.update()
        self.assertIn('disabled',adoption.toggle.state())
        self.assertNotIn('disabled',adoption.accept_button.state())
        for widget in (adoption.accept_button,adoption.decline_button,adoption.close_button,adoption.events):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(),15)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                 adoption.window.winfo_rooty()+adoption.window.winfo_height())
        with patch('tkinter.messagebox.askyesno',return_value=False):
            adoption.accept_button.invoke()
        self.assertTrue(waiting(self.app.session.core))
        with patch('tkinter.messagebox.askyesno',return_value=True):
            adoption.accept_button.invoke()
        self.assertEqual(self.app.session.core.activity(key),'adopted')
        self.assertIn('disabled',adoption.accept_button.state())
        self.assertEqual(adoption.events.item(adoption.events.get_children()[0],'values')[-1],'譲渡成立')
        self.assertNotIn('disabled',self.app.run_button.state())
        adoption.close_button.invoke();activity.close_button.invoke()

    def test_player_play_details_buttons_save_resume_and_close(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        from cat_cafe_sim.core.cafe_player import remaining, current
        self.app.session=CafeInteractionSession(store=self.store)
        self.app.logged=0;self.app.refresh()
        key=next(iter(self.app.session.core.cats))
        self.app.roster.selection_set(key)
        self.app.cat_details_button.invoke()
        dialog=self.app.cat_details_window
        self.root.deiconify();dialog.window.deiconify();self.root.update()
        dialog.play_button.invoke()
        play=dialog.player_window
        play.window.geometry('600x480');self.root.update()
        self.assertEqual(remaining(self.app.session.core),2)
        self.assertIn('disabled',self.app.run_button.state())
        play.selector.current(play.targets.index('voice'))
        play.buttons['switch'].invoke()
        self.assertIn('disabled',play.buttons['intense'].state())
        play.buttons['direct'].invoke()
        self.assertEqual(len(current(self.app.session.core).records),2)
        self.assertEqual(len(play.history.get_children()),2)
        for widget in (play.finish_button,play.close_button,play.history):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(),15)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                 play.window.winfo_rooty()+play.window.winfo_height())
        play.close_button.invoke()
        self.assertFalse(play.window.winfo_exists())
        dialog.close_button.invoke()
        self.assertFalse(self.app.running)
        save_game(self.app.session,self.path)
        self.app.session,_=load_game(self.path)
        self.app.logged=0;self.app.refresh()
        self.app.cat_details_button.invoke();dialog=self.app.cat_details_window
        self.assertIn('進行中',dialog.play_button.cget('text'))
        dialog.play_button.invoke();play=dialog.player_window
        self.assertEqual(len(play.history.get_children()),2)
        self.assertEqual(remaining(self.app.session.core),2)
        play.finish_button.invoke()
        self.assertIsNone(current(self.app.session.core))
        self.assertIn('確定',play.result.get())
        self.assertNotIn('disabled',self.app.run_button.state())
        play.close_button.invoke()
        for _ in range(2):
            dialog.play_button.invoke()
            dialog.player_window.finish_button.invoke()
            dialog.player_window.close_button.invoke()
        self.assertIn('disabled',dialog.play_button.state())
        dialog.close_button.invoke()
        self.app.session.day_off();self.app.refresh()
        self.app.cat_details_button.invoke();dialog=self.app.cat_details_window
        self.assertNotIn('disabled',dialog.play_button.state())
        dialog.close_button.invoke()
        self.app.session.automatic_step();self.app.refresh()
        self.app.cat_details_button.invoke();dialog=self.app.cat_details_window
        self.assertIn('disabled',dialog.play_button.state())
        dialog.close_button.invoke()

    def test_dispatch_window_departure_saved_return_and_small_layout(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        self.app.session=CafeInteractionSession(store=self.store)
        self.app.logged=0
        self.app.refresh()
        self.app.activity_button.invoke()
        window=self.app.activity_window
        key=next(iter(self.app.session.core.cats))
        window.cats.selection_set(key)
        self.root.deiconify();window.window.geometry('500x400');self.root.update()
        with patch('tkinter.messagebox.askyesno',return_value=True):
            window.send_button.invoke()
        self.assertEqual(self.app.session.core.activity(key),'dispatched')
        self.assertEqual(window.cats.item(key,'values')[1],'派遣中')
        for button in (window.send_button,window.receive_button,window.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                                 window.window.winfo_rooty()+window.window.winfo_height())
        window.window.destroy()
        self.app.session.day_off()
        save_game(self.app.session,self.path)
        self.app.session,_=load_game(self.path)
        self.app.logged=0;self.app.refresh()
        self.assertIn('disabled',self.app.day_off_button.state())
        self.assertIn('確認待ち',self.app.notice.get())
        self.app.activity_button.invoke();window=self.app.activity_window
        self.assertNotIn('disabled',window.receive_button.state())
        before=self.app.session.core.funds
        window.receive_button.invoke();window.receive_button.invoke()
        self.assertEqual(self.app.session.core.funds,before+100)
        self.assertEqual(self.app.session.core.activity(key),'cafe')
        self.assertNotIn('disabled',self.app.day_off_button.state())
        self.assertIn('disabled',window.receive_button.state())
        window.window.destroy()

    def test_health_results_sick_work_lock_and_recovered_return(self):
        from dataclasses import asdict,replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.cafe_health import HealthRules
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        key=next(iter(self.session.core.cats))
        core=MultiSeatCafeCore(replace(Config.load(),opening_ticks=3,arrival_ticks=(0,)),cat_ids=[key])
        core.set_shifts([key],dict(max_fatigue=100,fatigue_per_service_tick=10,rest_day_recovery=5))
        core.enable_health(asdict(HealthRules(safe_fatigue=0,probability_per_fatigue=1,max_probability=1)))
        self.app.session=CafeInteractionSession(core=core,store=self.store,
            interaction_config=replace(RelationshipConfig(),ticks=2))
        self.app.logged=0
        while not core.closed:self.app.session.automatic_step()
        self.app.refresh()
        row=self.app.roster.item(self.app.roster.get_children()[0],'values')
        self.assertEqual(row[4],'療養')
        self.assertEqual(row[6],'療養あと2日')
        self.assertEqual(self.app.roster.set(self.app.roster.get_children()[0],'stress'),'未導入')
        with patch('tkinter.messagebox.askyesno',return_value=False) as dialog:
            self.app.day_button.invoke()
        self.assertIn('発症',dialog.call_args.args[1])
        self.assertIn('療養あと2日',dialog.call_args.args[1])
        self.app.history_button.invoke()
        history=self.app.history_window
        values=history.cats.item(history.cats.get_children()[0],'values')
        self.assertIn('発症',values[-1])
        history.window.destroy()
        self.app.session.next_day();self.app.refresh()
        self.app.shift_button.invoke()
        shifts=self.app.shift_window
        self.root.deiconify();shifts.window.deiconify();self.root.update()
        self.assertIn('disabled',shifts.work_button.state())
        self.assertEqual(shifts.tree.set(key,'health'),'療養あと2日')
        shifts.set_selected(True)
        self.assertNotIn(key,shifts.working)
        shifts.save_button.invoke()
        for _ in range(2):
            while not core.closed:self.app.session.automatic_step()
            self.app.session.next_day()
        self.app.refresh()
        self.app.shift_button.invoke()
        shifts=self.app.shift_window
        self.root.update()
        self.assertNotIn('disabled',shifts.work_button.state())
        self.assertEqual(shifts.tree.set(key,'health'),'健康')
        shifts.work_button.invoke();shifts.save_button.invoke()
        self.assertEqual([cat.id for cat in self.app.session.available_cats()],[key])
        self.assertFalse(self.app.running)

    def test_day_off_guidance_cancel_skip_and_history(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        self.assertIn('disabled',self.app.day_off_button.state())
        self.app.session=CafeInteractionSession(store=self.store)
        self.app.session.set_shifts([])
        self.app.logged=0;self.app.refresh()
        self.assertIn('今日は休業する',self.app.notice.get())
        before=self.app.session.core.snapshot()
        self.app.toggle()
        with patch('tkinter.messagebox.askyesno',return_value=False):
            self.app.day_off_button.invoke()
        self.assertEqual(self.app.session.core.snapshot(),before)
        self.assertFalse(self.app.running)
        with patch('tkinter.messagebox.askyesno',return_value=True):
            self.app.day_off_button.invoke()
        self.assertEqual(self.app.session.core.day,2)
        self.assertEqual(self.app.session.core.visits,{})
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)
        self.app.history_button.invoke()
        history=self.app.history_window
        self.assertEqual(history.days.item(history.days.get_children()[0],'values')[-1],'休業日')
        history.window.destroy()
        self.root.deiconify();self.root.geometry('860x600');self.root.update()
        button=self.app.day_off_button
        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
        self.app.session.automatic_step();self.app.refresh()
        self.assertIn('disabled',button.state())

    def test_rest_proposal_is_editable_cancelable_and_saved_explicitly(self):
        while not self.session.core.closed:self.session.automatic_step()
        self.session.next_day();self.app.refresh()
        ranked=sorted(self.session.core.cats, key=lambda key:(-self.session.core.cats[key].fatigue,key))
        expected=set(ranked[2:])
        before=self.session.core.log()
        self.app.shift_button.invoke()
        dialog=self.app.shift_window
        dialog.proposal_button.invoke()
        self.assertEqual(dialog.working,expected)
        self.assertEqual(self.session.core.log(),before)
        dialog.window.destroy()
        self.assertEqual(self.session.core.log(),before)
        self.app.shift_button.invoke()
        dialog=self.app.shift_window
        dialog.proposal_button.invoke()
        dialog.tree.selection_set(ranked[0]);dialog.set_selected(True)
        expected.add(ranked[0])
        self.assertEqual(dialog.working,expected)
        dialog.save_button.invoke()
        self.assertEqual(self.session.core.working_cats,expected)
        self.assertFalse(self.app.running)

    def test_all_rest_proposal_guides_to_day_off_without_advancing(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
        from cat_cafe_sim.core.config import Config
        from unittest.mock import patch
        ids=list(self.session.core.cats)[:2]
        self.app.session=CafeInteractionSession(core=MultiSeatCafeCore(Config.load(), cat_ids=ids),store=self.store)
        self.app.logged=0;self.app.refresh()
        before=self.app.session.core.log()
        self.app.shift_button.invoke();dialog=self.app.shift_window
        dialog.proposal_button.invoke()
        self.assertFalse(dialog.working)
        self.assertIn('全員休養',dialog.schedule_note.get())
        self.assertIn('今日は休業する',dialog.schedule_note.get())
        self.assertEqual(self.app.session.core.log(),before)
        self.root.deiconify();dialog.window.geometry('500x400');self.root.update()
        self.assertGreater(dialog.tree.winfo_height(),40)
        self.assertLess(dialog.save_button.winfo_rooty()+dialog.save_button.winfo_height(),
                        dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.save_button.invoke()
        self.assertEqual(self.app.session.core.day,1)
        self.assertIn('今日は休業する',self.app.notice.get())
        with patch('tkinter.messagebox.askyesno',return_value=True):
            self.app.day_off_button.invoke()
        self.assertEqual(self.app.session.core.day,2)
        self.assertEqual(self.app.session.core.day_results[-1]['day_type'],'day_off')

    def test_cat_details_selection_pause_switch_and_small_layout(self):
        ids=list(self.session.core.cats)
        self.app.roster.selection_set(ids[1])
        before=self.session.core.log()
        saved=self.store.path.read_bytes()
        self.app.toggle()
        self.app.cat_details_button.invoke()
        dialog=self.app.cat_details_window
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)
        self.assertEqual(dialog.ids[dialog.selector.current()],ids[1])
        dialog.selector.current(0);dialog.refresh()
        values=[dialog.tables['basic'].item(key,'values') for key in dialog.tables['basic'].get_children()]
        self.assertIn(('猫ID',ids[0]),values)
        self.root.deiconify();dialog.window.geometry('500x400');self.root.update()
        for index,key in enumerate(('basic','relationships','history')):
            dialog.notebook.select(index);self.root.update()
            self.assertGreater(dialog.tables[key].winfo_height(),40)
        self.assertLess(dialog.close_button.winfo_rooty()+dialog.close_button.winfo_height(),
                        dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.close_button.invoke()
        self.assertFalse(self.app.running)
        self.assertEqual(self.session.core.log(),before)
        self.assertEqual(self.store.path.read_bytes(),saved)

    def test_shift_forecasts_show_basis_and_do_not_change_state(self):
        while not self.session.core.closed:self.session.automatic_step()
        self.session.next_day();self.app.refresh()
        before=self.session.core.log()
        self.app.shift_button.invoke()
        dialog=self.app.shift_window
        self.root.deiconify();dialog.window.deiconify()
        dialog.window.geometry('500x400');self.root.update()
        key=next(iter(self.session.core.cats))
        self.assertEqual(dialog.tree.set(key,'basis'),str(self.session.core.day_results[-1]['cats'][key]['service_ticks']))
        self.assertIn('%',dialog.tree.set(key,'work_forecast'))
        self.assertIn('%',dialog.tree.set(key,'rest_forecast'))
        self.assertIn('前日の接客',dialog.forecast_note.get())
        self.assertGreater(dialog.tree.winfo_height(),40)
        self.assertLess(dialog.save_button.winfo_rooty()+dialog.save_button.winfo_height(),
                        dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.set_selected(False)
        dialog.window.destroy()
        self.assertEqual(self.session.core.log(),before)

    def test_shift_dialog_cancel_save_pause_and_lock_after_start(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        self.assertIn('disabled',self.app.shift_button.state())
        self.app.session=CafeInteractionSession(store=self.store)
        self.app.logged=0
        self.app.refresh()
        key=next(iter(self.app.session.core.cats))
        self.app.toggle()
        self.app.shift_button.invoke()
        dialog=self.app.shift_window
        self.assertFalse(self.app.running)
        self.assertIsNone(self.app.timer)
        dialog.tree.selection_set(key)
        dialog.set_selected(False)
        dialog.window.destroy()
        self.assertIn(key,self.app.session.core.working_cats)
        self.app.shift_button.invoke()
        dialog=self.app.shift_window
        dialog.tree.selection_set(key)
        dialog.set_selected(False)
        self.root.deiconify();dialog.window.deiconify()
        self.root.update()
        self.assertGreater(dialog.tree.winfo_height(),40)
        dialog.save_button.invoke()
        self.assertNotIn(key,self.app.session.core.working_cats)
        rows=[self.app.roster.item(item,'values') for item in self.app.roster.get_children()]
        self.assertEqual(rows[0][4],'休養')
        self.assertEqual(rows[0][5],'0')
        self.app.session.automatic_step()
        self.app.refresh()
        self.assertIn('disabled',self.app.shift_button.state())

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
        self.assertIn('2日目',self.app.phase.get())
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


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'GUI tests require an explicit display')
class CafeStartWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_start_gui import CafeStartWindow
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.directory = Path(self.temp.name) / 'games'
        self.start = CafeStartWindow(self.root, self.directory)
        self.addCleanup(lambda: self.start.app.stop() if hasattr(self.start, 'app') else None)

    def test_cancel_create_and_restart_failure_then_success(self):
        from cat_cafe_sim.storage.cafe_saves import load_game
        self.start.new_button.invoke()
        self.start.new_window.cancel_button.invoke()
        self.assertFalse(self.directory.exists())
        self.start.new_button.invoke()
        self.start.new_window.start_button.invoke()
        app = self.start.app
        first = app.session
        self.assertFalse(app.running)
        self.assertEqual(first.core.funds, 1000)
        self.root.geometry('860x600'); self.root.update()
        for button in (app.new_game_button, app.save_button, app.open_button, app.history_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
        app.new_game_button.invoke()
        with patch('tkinter.messagebox.askyesnocancel', return_value=None):
            app.new_game_window.start_button.invoke()
        self.assertIs(app.session, first)
        with patch('tkinter.messagebox.askyesnocancel', return_value=True), patch.object(app,'save_game',return_value=False):
            app.new_game_window.start_button.invoke()
        self.assertIs(app.session, first)
        with patch('tkinter.messagebox.askyesnocancel', return_value=False), \
                patch('cat_cafe_sim.cafe_start_gui.create_game',side_effect=OSError('full')), \
                patch('tkinter.messagebox.showerror') as error:
            app.new_game_window.start_button.invoke()
            error.assert_called_once()
        self.assertIs(app.session, first)
        self.assertNotIn('disabled', app.new_game_window.start_button.state())
        with patch('tkinter.messagebox.askyesnocancel', return_value=True), \
                patch('tkinter.filedialog.asksaveasfilename',return_value=str(first.checkpoint_path)):
            app.new_game_window.start_button.invoke()
        self.assertIsNot(app.session, first)
        self.assertNotEqual(app.session.store.path, first.store.path)
        self.assertFalse(app.running)
        self.assertIsNone(app.timer)
        self.assertEqual(load_game(first.checkpoint_path)[0].core.snapshot(), first.core.snapshot())
        self.assertEqual(app.session.core.funds, 1000)

    def test_traits_details_dispatch_preview_return_and_recruitment(self):
        self.start.new_button.invoke();self.start.new_window.start_button.invoke()
        app=self.start.app
        app.roster.selection_set('cat-mike');app.cat_details_button.invoke()
        details=app.cat_details_window
        rows=[details.tables['basic'].item(i,'values') for i in details.tables['basic'].get_children()]
        self.assertIn(('特性','接客好き'),rows)
        self.assertIn(('接客ストレス','通常の0.5倍'),rows)
        self.assertIn(('接客疲労','通常の1.25倍'),rows)
        details.window.destroy()
        app.activity_button.invoke();activity=app.activity_window
        activity.cats.selection_set('cat-tama')
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:
            activity.send_button.invoke()
        self.assertIn('報酬 125',confirm.call_args.args[1])
        self.assertIn('ストレス ＋10',confirm.call_args.args[1])
        self.assertEqual(app.session.core.activity('cat-tama'),'cafe')
        with patch('tkinter.messagebox.askyesno',return_value=True):activity.send_button.invoke()
        app.session.day_off();activity.refresh();app.refresh()
        activity.window.geometry('500x400');self.root.update()
        self.assertEqual(activity.events.set('dispatch-1-cat-tama','報酬'),'125')
        self.assertEqual(activity.events.set('dispatch-1-cat-tama','帰還ストレス増加'),'10')
        for widget in (activity.receive_button,activity.cats,activity.events):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(),15)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),activity.window.winfo_rooty()+activity.window.winfo_height())
        activity.receive_button.invoke()
        self.assertEqual(app.session.core.funds,1125)
        self.assertEqual(app.roster.set('cat-tama','stress'),'10')
        activity.recruitment_button.invoke();window=activity.recruitment_window
        self.root.update()
        selected=window.cats.selection()[0]
        self.assertEqual(window.cats.set(selected,'特性'),'接客好き')
        rows=[window.details.item(i,'values') for i in window.details.get_children()]
        self.assertIn(('接客ストレス','通常の0.5倍'),rows)
        self.assertIn(('接客疲労','通常の1.25倍'),rows)
        window.close_button.invoke();activity.close_button.invoke()

    def test_resume_cancel_invalid_and_game_over_restart(self):
        from dataclasses import replace
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.core.config import Config
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
        from cat_cafe_sim.core.human_cat_types import Personality
        from cat_cafe_sim.core.cafe_management import rules
        from cat_cafe_sim.storage.relationships import RelationshipStore
        from cat_cafe_sim.storage.cafe_saves import save_game, load_game
        with patch('tkinter.filedialog.askopenfilename', return_value=''):
            self.start.resume_button.invoke()
        self.assertTrue(self.start.frame.winfo_exists())
        with patch('tkinter.filedialog.askopenfilename', return_value=str(self.directory/'absent.json')), \
                patch('tkinter.messagebox.showerror') as error:
            self.start.resume_button.invoke(); error.assert_called_once()
        self.assertTrue(self.start.frame.winfo_exists())
        store = RelationshipStore(Path(self.temp.name)/'relations.json')
        store.register_cat('cat', '猫', Personality())
        s = CafeInteractionSession(store=store, cafe_config=replace(Config.load(), opening_ticks=2, arrival_ticks=(0,)),
                                   interaction_config=replace(RelationshipConfig(), ticks=1))
        s.enable_management(dict(rules(), runaway_threshold=1, return_stress=0, popularity_loss=100))
        while not s.core.closed: s.automatic_step()
        self.assertIsNotNone(s.core.management['game_over'])
        path = Path(self.temp.name)/'ended.json'
        save_game(s,path,auto_assign=True)
        with patch('tkinter.filedialog.askopenfilename', return_value=str(path)):
            self.start.resume_button.invoke()
        app = self.start.app
        self.assertFalse(app.running)
        self.assertTrue(app.auto_assign.get())
        self.assertIn('ゲームオーバー', app.notice.get())
        self.assertIn('disabled', app.run_button.state())
        self.assertEqual(app.new_game_button.cget('text'), '結果・再開始…')
        app.new_game_button.invoke()
        window = app.new_game_window
        window.window.geometry('500x430'); self.root.update()
        for widget in (window.start_button, window.cancel_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),window.window.winfo_rooty()+window.window.winfo_height())
        window.start_button.invoke()
        self.assertIsNone(app.session.core.management['game_over'])
        self.assertEqual(app.session.core.day,1)
        self.assertEqual(app.session.core.management['popularity'],100)
        self.assertIsNotNone(load_game(path)[0].core.management['game_over'])
