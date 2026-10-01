"""用品体験会の出発日による出来事選択と、固定記録の互換。"""
import copy
import os
import unittest
from unittest.mock import patch
import test_cafe_product_trial_dispatch as fixtures
from cat_cafe_sim.core.cafe_dispatch_encounters import for_destination, pending
from cat_cafe_sim.core.cafe_dispatch_unlocks import trial_destination
from cat_cafe_sim.core.cafe_activities import reward, destinations
from cat_cafe_sim.core.cafe_items import inventory
from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class ProductModelRequestTests(unittest.TestCase):
    setUp=fixtures.ProductTrialDispatchTests.setUp
    game=fixtures.ProductTrialDispatchTests.game
    unlock=fixtures.ProductTrialDispatchTests.unlock
    reload_replay=fixtures.ProductTrialDispatchTests.reload_replay
    rejected=fixtures.ProductTrialDispatchTests.rejected

    def ready(self):
        s=self.unlock(self.game());s.day_off()
        self.assertEqual(s.core.day,3)
        return s

    def depart(self):
        s=self.ready();s.dispatch('cat-mugi',trial_destination(s.core))
        return s,'dispatch-3-cat-mugi'

    def test_selection_preview_is_stable_exclusive_and_other_destinations_unchanged(self):
        s=self.ready();destination=trial_destination(s.core);before=s.core.snapshot()
        for day in (1,2,3,4):
            self.assertEqual(for_destination(destination,day)['id'],'product_model_request' if day%2 else 'extra_product_trial')
            for other in destinations(s.core):
                if other['id']!=destination['id']:
                    self.assertEqual(for_destination(other,day),for_destination(other))
        row=next(r for r in comparison_rows(s,'cat-mugi') if r['destination']['id']==destination['id'])
        self.assertIn('撮影モデル',row['detail']);self.assertIn('報酬 450',row['options'][0])
        self.assertIn('疲労 +15',row['options'][0]);self.assertIn('ストレス +15',row['options'][0])
        self.assertEqual(s.core.snapshot(),before)
        s.dispatch('cat-mugi',destination)
        event=s.core.activities['events']['dispatch-3-cat-mugi']
        self.assertEqual(event['encounter']['rules'],for_destination(destination,3))
        self.assertEqual(sum(k=='encounter' for k in event),1)
        self.reload_replay(s)

    def test_choices_business_day_off_pending_return_items_and_no_duplicate(self):
        for choice in ('accept','decline'):
            for rest in (True,False):
                with self.subTest(choice=choice,rest=rest):
                    s,key=self.depart();s=self.reload_replay(s)
                    if rest:s.day_off()
                    else:
                        while not s.core.closed:s.automatic_step()
                    self.assertTrue(pending(s.core.activities['events'][key]))
                    for action in (s.day_off,s.next_day,lambda:s.resolve_activity(key)):
                        self.rejected(s,action)
                    s=self.reload_replay(s);funds=s.core.funds
                    fatigue=s.core.cats['cat-mugi'].fatigue;stress=s.core.management['stress']['cat-mugi']
                    s.resolve_dispatch_choice(key,choice);delta=15 if choice=='accept' else 0
                    self.assertEqual(s.core.funds,funds)
                    self.assertEqual(s.core.cats['cat-mugi'].fatigue,fatigue+delta)
                    self.assertEqual(s.core.management['stress']['cat-mugi'],stress+delta)
                    expected=450 if choice=='accept' else 300
                    self.assertEqual(reward(s.core,s.core.activities['events'][key]),expected)
                    before=s.core.snapshot();s.resolve_dispatch_choice(key,choice);self.assertEqual(s.core.snapshot(),before)
                    self.rejected(s,lambda:s.resolve_dispatch_choice(key,'decline' if choice=='accept' else 'accept'))
                    s=self.reload_replay(s)
                    if s.core.closed:s.next_day()
                    s.day_off();funds=s.core.funds;s.resolve_activity(key)
                    self.assertEqual(s.core.funds,funds+expected)
                    self.assertEqual(inventory(s.core)[key]['id'],'special_care_set')
                    before=s.core.snapshot();s.resolve_activity(key);self.assertEqual(s.core.snapshot(),before)
                    self.reload_replay(s)

    def test_saved_settings_retry_caps_and_old_departure_stay_fixed(self):
        s,key=self.depart();original=copy.deepcopy(s.core.activities['events'][key]['encounter']['rules'])
        with patch('cat_cafe_sim.core.cafe_dispatch_encounters.for_destination',side_effect=AssertionError('current config')):
            s=self.reload_replay(s);s.day_off()
            capped=copy.deepcopy(s.core);capped.cats['cat-mugi'].fatigue=95;capped.management['stress']['cat-mugi']=95
            capped.resolve_dispatch_choice(key,'accept')
            self.assertEqual(capped.cats['cat-mugi'].fatigue,100);self.assertEqual(capped.management['stress']['cat-mugi'],100)
            s.resolve_dispatch_choice(key,'accept')
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
            s=self.reload_replay(s);before=s.core.snapshot();s.resolve_dispatch_choice(key,'accept')
            self.assertEqual(s.core.snapshot(),before);s.day_off();s.resolve_activity(key)
            self.reload_replay(s)
            self.assertEqual(s.core.activities['events'][key]['encounter']['rules'],original)
        s=self.ready();legacy=for_destination(trial_destination(s.core),2)
        with patch('cat_cafe_sim.core.cafe_dispatch_encounters.for_destination',return_value=legacy):
            s.dispatch('cat-mugi',trial_destination(s.core))
        s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice('dispatch-3-cat-mugi','accept');s.day_off()
        self.assertEqual(reward(s.core,s.core.activities['events']['dispatch-3-cat-mugi']),400)
        self.reload_replay(s)

    def test_invalid_days_and_config_duplicates_rejected(self):
        s=self.ready();destination=trial_destination(s.core)
        for day in (0,-1,True,1.5):
            with self.assertRaises(ValueError):for_destination(destination,day)
        original=for_destination(destination,2)
        for rows in ([original,original],[original,dict(original,id='unexpected')]):
            with patch('cat_cafe_sim.core.cafe_dispatch_encounters.json.loads',return_value=rows):
                with self.assertRaises(ValueError):for_destination(destination,3)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires display')
class ProductModelRequestGuiTests(unittest.TestCase):
    setUp=ProductModelRequestTests.setUp
    game=ProductModelRequestTests.game
    unlock=ProductModelRequestTests.unlock
    ready=ProductModelRequestTests.ready

    def test_preview_confirmation_choices_and_return(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.ready();app=CafeInteractionWindow(root,s);app.activity_button.invoke();w=app.activity_window
        w.destination_choice.current(next(i for i,r in enumerate(w.destinations) if r['id']=='cat_product_trial'));w.select_destination()
        w.cats.selection_set('cat-mugi');w.buttons();before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.send_button.invoke()
        self.assertIn('撮影モデル',ask.call_args.args[1]);self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.send_button.invoke()
        s.day_off();w.refresh();w.events.selection_set('dispatch-3-cat-mugi');w.buttons();w.receive_button.invoke()
        child=w.choice_window;child.window.geometry('560x360');root.update()
        self.assertIn('疲労 +15',child.buttons['accept']['text']);self.assertIn('ストレス +15',child.buttons['accept']['text'])
        child.buttons['accept'].invoke();root.update();self.assertIn('帰還報酬：450',child.notice.get())
        self.assertLessEqual(child.buttons['decline'].winfo_rooty()+child.buttons['decline'].winfo_height(),child.window.winfo_rooty()+child.window.winfo_height())
        child.close();s.day_off();w.refresh();w.events.selection_set('dispatch-3-cat-mugi');w.buttons();w.receive_button.invoke();w.result_button.invoke()
        self.assertIn('資金報酬合計：450',w.result_text.get('1.0','end'))
