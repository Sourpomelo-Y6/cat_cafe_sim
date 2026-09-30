"""撮影スタジオの初回限定紹介、飼育枠・保存と再試行。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cafe_photo_dispatch as photo
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_dispatch_unlocks import photo_destination
from cat_cafe_sim.core.cafe_dispatch_introduction import rules, for_departure, waiting, admission_reason, expenses
from cat_cafe_sim.core.cafe_activities import destinations
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_housing import capacity
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.storage.cafe_saves import save_game


class PhotoIntroductionTests(unittest.TestCase):
    setUp=photo.PhotoDispatchTests.setUp
    reload_replay=photo.PhotoDispatchTests.reload_replay
    unlock=photo.PhotoDispatchTests.unlock

    def rejected(self,s,action,error=ValueError):
        before,stored=s.core.snapshot(),s.store._read()
        with self.assertRaises(error):action()
        self.assertEqual(s.core.snapshot(),before);self.assertEqual(s.store._read(),stored)

    def game(self,mode='free',legacy=False,no_introductions=False,seats=2,full=False):
        selected=starting_conditions(mode)
        for key in ('store_events','intake_request','regular_introduction','customer_trust','customer_discontent'):
            selected.pop(key)
        selected['management'].update(starting_funds=10000,stress_per_service_tick=0)
        selected['growth']['threshold']=1000
        selected['dispatch_unlocks']['cat_photo_studio']['popularity']=100
        selected['dispatch_unlocks']['shopping_street_event']['popularity']=100
        selected['seat_count']=seats
        if legacy:selected['dispatch_introduction'].pop('photo_studio')
        if no_introductions:selected.pop('dispatch_introduction')
        if full:
            selected['profiles']['cats']['sixth']=copy.deepcopy(selected['profiles']['cats']['cat-mike'])
            selected['traits']['sixth']=copy.deepcopy(selected['traits']['cat-mike'])
        return self.unlock(create_game(Path(self.temp.name)/'games',selected))

    def depart(self,s,key='cat-mike'):
        s.dispatch(key,photo_destination(s.core));return f'dispatch-{s.core.day}-{key}'

    def receive(self,s,event_id,choice='decline',rest=True):
        if rest:s.day_off()
        else:
            while not s.core.closed:s.automatic_step()
        s.resolve_dispatch_choice(event_id,choice)
        if s.core.closed:s.next_day()
        if rest:s.day_off()
        else:
            while not s.core.closed:s.automatic_step()
        s.resolve_activity(event_id)

    def test_all_modes_first_candidate_fixed_at_departure(self):
        for mode in ('free','popularity','bond','patron'):
            s=self.game(mode);event_id=self.depart(s)
            row=s.core.activities['events'][event_id]['introduction']
            self.assertEqual(row['status'],'scheduled');self.assertEqual(row['candidate']['cost'],250)
            self.assertEqual(row['candidate']['features'],['white','short_hair'])
            self.assertEqual(row['candidate']['trait']['id'],'hospitality')
            self.assertIn('ルカ',row['candidate']['name']);self.assertFalse(waiting(s.core))
            self.rejected(s,lambda:s.resolve_dispatch_introduction(event_id,'accept'))
            self.reload_replay(s)

    def test_accept_decline_return_finance_details_and_one_time(self):
        for seats in (1,2):
            for choice in ('accept','decline'):
                s=self.game(seats=seats);event_id=self.depart(s);s=self.reload_replay(s)
                self.receive(s,event_id,'accept');s=self.reload_replay(s)
                offered=copy.deepcopy(s.core.activities['events'][event_id]['introduction']);key=offered['cat_id']
                self.assertEqual(len(waiting(s.core)),1)
                for action in (s.day_off,s.automatic_step,lambda:s.set_shifts([])):
                    self.rejected(s,action)
                funds=s.core.funds;s.resolve_dispatch_introduction(event_id,choice)
                self.assertEqual(s.core.funds,funds-(250 if choice=='accept' else 0))
                self.assertEqual(expenses(s.core),250 if choice=='accept' else 0)
                self.assertEqual(s.core.summary()['dispatch_income'],450)
                if choice=='accept':
                    self.assertEqual(s.core.activity(key),'cafe');self.assertNotIn(key,s.core.working_cats)
                    self.assertEqual(s.core.management['stress'][key],0)
                    self.assertEqual(s.core.traits[key]['id'],'hospitality')
                    self.assertEqual(s.profiles[key]['personality'],offered['candidate']['personality'])
                    self.assertEqual(dict(cat_details(s,key)['basic'])['加入経路'],'派遣先からの紹介')
                    self.assertIn('加入',str(cat_events(s.core,key)))
                else:self.assertNotIn(key,s.core.cats)
                s=self.reload_replay(s);before=s.core.snapshot()
                with patch.object(s.store,'_write',side_effect=AssertionError('duplicate')):
                    s.resolve_dispatch_introduction(event_id,choice);s.resolve_activity(event_id)
                self.assertEqual(s.core.snapshot(),before)
                self.rejected(s,lambda:s.resolve_dispatch_introduction(event_id,'decline' if choice=='accept' else 'accept'))
                self.assertIsNone(for_departure(s.core,photo_destination(s.core),set()))
                second=self.depart(s);self.assertNotIn('introduction',s.core.activities['events'][second])
                self.reload_replay(s)

    def test_closed_return_defers_until_preparation(self):
        s=self.game();event_id=self.depart(s);self.receive(s,event_id,rest=False)
        self.assertTrue(s.core.closed);self.assertFalse(waiting(s.core))
        self.assertEqual(s.core.activities['events'][event_id]['introduction']['status'],'scheduled')
        self.rejected(s,lambda:s.resolve_dispatch_introduction(event_id,'accept'))
        s=self.reload_replay(s);s.next_day();self.assertEqual(len(waiting(s.core)),1)
        s.resolve_dispatch_introduction(event_id,'decline');self.reload_replay(s)

    def test_full_housing_expansion_rechecks_and_expenses(self):
        s=self.game(full=True);event_id=self.depart(s);self.receive(s,event_id)
        self.assertIn('満員',admission_reason(s.core,event_id))
        self.rejected(s,lambda:s.resolve_dispatch_introduction(event_id,'accept'))
        funds=s.core.funds;s.purchase_housing();self.assertEqual(capacity(s.core),9)
        self.assertEqual(s.core.funds,funds-500);self.assertEqual(len(waiting(s.core)),1)
        s=self.reload_replay(s);s.resolve_dispatch_introduction(event_id,'accept')
        self.assertEqual(len(s.core.cats),7);self.assertEqual(s.core.funds,funds-750)
        self.assertEqual(s.core.summary()['housing_expenses'],500);self.assertEqual(s.core.summary()['recruitment_expenses'],250)
        self.reload_replay(s)
        for full in (True,False):
            s=self.game(full=full);event_id=self.depart(s);self.receive(s,event_id)
            if not full:s.core.funds=250
            self.rejected(s,lambda:s.resolve_dispatch_introduction(event_id,'accept'))
            funds=s.core.funds;s.resolve_dispatch_introduction(event_id,'decline')
            self.assertEqual(s.core.funds,funds);self.assertFalse(waiting(s.core))

    def test_simultaneous_photo_dispatch_reserves_only_one_and_shop_independent(self):
        s=self.game(full=True);s.purchase_housing()
        first=self.depart(s);second=self.depart(s,'sixth')
        shop=destinations()[1]
        self.assertIsNotNone(for_departure(s.core,shop,set()))
        self.assertIn('introduction',s.core.activities['events'][first]);self.assertNotIn('introduction',s.core.activities['events'][second])
        s.day_off();s.resolve_dispatch_choice(first,'decline');s.resolve_dispatch_choice(second,'accept');s.day_off()
        s.resolve_activity(first);s.resolve_activity(second);self.assertEqual(len(waiting(s.core)),1)
        s.resolve_dispatch_introduction(first,'decline')
        s.dispatch('cat-mike',shop);third=f'dispatch-{s.core.day}-cat-mike'
        self.assertIn('セナ',s.core.activities['events'][third]['introduction']['candidate']['name'])
        self.assertNotEqual(s.core.activities['events'][third]['introduction']['cat_id'],s.core.activities['events'][first]['introduction']['cat_id'])
        self.reload_replay(s)

    def test_old_rules_and_old_departures_do_not_gain_introduction(self):
        for no_intro in (False,True):
            s=self.game(legacy=True,no_introductions=no_intro);event_id=self.depart(s)
            self.assertNotIn('introduction',s.core.activities['events'][event_id])
            s=self.reload_replay(s);self.receive(s,event_id);self.assertFalse(waiting(s.core))
            self.reload_replay(s)
        s=self.game();s.core.dispatch('cat-mike',photo_destination(s.core));event_id='dispatch-2-cat-mike'
        s=self.reload_replay(s);s.day_off();s.day_off();s.resolve_activity(event_id)
        self.assertNotIn('introduction',s.core.activities['events'][event_id]);self.reload_replay(s)

    def test_store_registration_save_failures_and_candidate_fixed(self):
        s=self.game();event_id=self.depart(s);offered=copy.deepcopy(s.core.activities['events'][event_id]['introduction'])
        with patch('cat_cafe_sim.core.cafe_dispatch_introduction.configured',side_effect=AssertionError('changed')):
            s=self.reload_replay(s);self.receive(s,event_id)
            with patch.object(s.store,'_write',side_effect=OSError('full')):
                self.rejected(s,lambda:s.resolve_dispatch_introduction(event_id,'accept'),OSError)
            s.resolve_dispatch_introduction(event_id,'accept');funds=s.core.funds
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
            s=self.reload_replay(s);s.resolve_dispatch_introduction(event_id,'accept')
            self.assertEqual(s.core.funds,funds)
            self.assertEqual(s.core.activities['events'][event_id]['introduction']['candidate'],offered['candidate'])
            self.assertEqual(len(s.core.cats),6)

    def test_invalid_rules_candidates_and_duplicate_photo_introduction(self):
        for mutate in (lambda d:d['photo_studio'].update(destination='shopping_street_event'),
                       lambda d:d['photo_studio']['candidate'].update(cost=True),lambda d:d['photo_studio'].update(extra=True)):
            bad=rules();mutate(bad)
            with self.assertRaises(ValueError):rules(bad)
        s=self.game(full=True);first=self.depart(s);second=self.depart(s,'sixth');source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['dispatch_introduction'].pop('photo_studio'),
                       lambda d:d['state']['activities']['events'][first]['introduction']['candidate'].update(cost=999),
                       lambda d:d['state']['activities']['events'][first]['introduction'].update(presented_day=1)):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        bad=copy.deepcopy(source);row=copy.deepcopy(bad['state']['activities']['events'][first]['introduction'])
        row['cat_id']='dispatch-rescue-2';row['candidate']['name']='ルカ（派遣紹介2）'
        bad['state']['activities']['events'][second]['introduction']=row;bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class PhotoIntroductionGuiTests(unittest.TestCase):
    setUp=PhotoIntroductionTests.setUp
    game=PhotoIntroductionTests.game
    unlock=PhotoIntroductionTests.unlock
    depart=PhotoIntroductionTests.depart
    receive=PhotoIntroductionTests.receive

    def test_notice_close_housing_accept_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game(full=True);app=CafeInteractionWindow(root,s)
        app.activity_button.invoke();activity=app.activity_window
        index=next(i for i,row in enumerate(activity.destinations) if row['id']=='cat_photo_studio')
        activity.destination_choice.current(index);activity.select_destination()
        activity.cats.selection_set('cat-mike');activity.buttons();before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:activity.send_button.invoke()
        self.assertIn('保護猫の紹介',confirm.call_args.args[1]);self.assertEqual(s.core.snapshot(),before)
        activity.window.destroy();event_id=self.depart(s);self.receive(s,event_id);app.refresh()
        self.assertIn('紹介された猫',app.notice.get());app.attention_button.invoke();dialog=app.dispatch_introduction_window
        dialog.window.geometry('560x420');root.update()
        self.assertIn('撮影スタジオ',dialog.title.get());self.assertTrue(dialog.accept_button.instate(['disabled']))
        self.assertTrue(dialog.decline_button.instate(['!disabled']));dialog.close();self.assertEqual(len(waiting(s.core)),1)
        app.attention_button.invoke();dialog=app.dispatch_introduction_window
        dialog.housing_button.invoke();housing=dialog.housing_window
        with patch('tkinter.messagebox.askyesno',return_value=True):housing.purchase_button.invoke()
        housing.close();root.update();self.assertTrue(dialog.accept_button.instate(['!disabled']))
        self.assertLessEqual(dialog.decline_button.winfo_rooty()+dialog.decline_button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
        with patch('tkinter.messagebox.askyesno',return_value=True):dialog.accept_button.invoke()
        self.assertIn('迎えました',dialog.notice.get());self.assertEqual(len(s.core.cats),7)
