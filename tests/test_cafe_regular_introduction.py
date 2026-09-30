import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_regular_introduction import pending, rules, reserved_ids, first_regular
from cat_cafe_sim.core.cafe_player import legacy_play
from cat_cafe_sim.storage.cafe_saves import load_game, save_game
from cat_cafe_sim.storage.relationships import RelationshipConflict


class RegularIntroductionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sequence=0

    def game(self,mode='free', *, fast=True, intake=False, legacy=False, full=False, expensive=False, seats=2):
        self.sequence+=1
        selected=starting_conditions(mode)
        selected['seat_count']=seats
        if not intake:selected.pop('intake_request')
        else:selected['intake_request']['day']=2
        if legacy:selected.pop('regular_introduction')
        selected['management']['starting_funds']=10000
        selected['management']['stress_per_service_tick']=0
        selected.pop('dispatch_unlocks')
        selected.pop('customer_trust')
        selected.pop('customer_discontent')
        selected['store_events']['probability']=0
        selected['growth']['threshold']=1000
        if fast:selected['customer_loyalty']=dict(gain=25,threshold=25)
        if full:
            selected['profiles']['cats']['sixth']=copy.deepcopy(selected['profiles']['cats']['cat-mugi'])
        if expensive:selected['regular_introduction']['candidate']['cost']=100000
        if mode=='popularity':
            selected['goal']['target']=105
        return create_game(Path(self.temp.name)/str(self.sequence),selected)

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def offered(self,s):
        self.close(s)
        if s.core.goal['status']=='cleared':s.continue_goal()
        s.next_day(); self.assertTrue(pending(s.core)); return s

    def reload(self,s):
        save_game(s,s.checkpoint_path); loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot()); return loaded

    def replay(self,s):
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def rejected(self,s,action):
        before=s.core.snapshot()
        with self.assertRaises(ValueError):action()
        self.assertEqual(before,s.core.snapshot())

    def test_default_threshold_first_customer_and_next_preparation_once(self):
        s=self.game(fast=False); self.close(s)
        self.assertIsNone(first_regular(s.core)); self.assertFalse(pending(s.core)); self.replay(s)
        s.next_day(); self.assertFalse(pending(s.core))
        for _ in range(12):
            self.close(s)
            self.assertFalse(pending(s.core))
            first=first_regular(s.core); s.next_day()
            if first:break
        self.assertTrue(pending(s.core)); data=s.core.regular_introduction
        self.assertEqual((data['regular_day'],data['customer_id']),first)
        self.assertEqual(data['presented_day'],first[0]+1)
        self.assertEqual(s.core.customer_loyalty['customers'][data['customer_id']]['score'],100)
        self.assertEqual(data['rules']['candidate']['cost'],200)
        self.assertEqual(len(s.core.cats),5); self.replay(s)
        s.resolve_regular_introduction('decline')
        for _ in range(3):s.day_off()
        self.assertEqual(sum(e['kind']=='regular_introduction_waiting' for e in s.core.events),1)
        self.replay(s)

    def test_accept_cat_profile_features_bond_growth_shifts_finance_and_replay(self):
        s=self.game('bond'); s.play_with_player('cat-mugi'); s.player_command(finish=True)
        s=self.offered(s); key=s.core.regular_introduction['rules']['cat_id']
        funds=s.core.funds; rule=copy.deepcopy(s.core.regular_introduction['rules'])
        s.resolve_regular_introduction('accept')
        self.assertEqual(s.core.funds,funds-200); self.assertEqual(len(s.core.cats),6)
        self.assertEqual(s.profiles[key]['name'],rule['candidate']['name'])
        self.assertEqual(s.profiles[key]['personality'],rule['candidate']['personality'])
        self.assertEqual(s.core.traits[key],rule['candidate']['trait'])
        self.assertEqual(s.core.cat_features[key],rule['candidate']['features'])
        self.assertEqual(s.core.cats[key].stamina,s.core.config.max_stamina)
        self.assertEqual(s.core.cats[key].health_status,'healthy')
        self.assertEqual(s.core.management['stress'][key],0)
        self.assertEqual(s.core.player_bond['affinity'][key],0)
        self.assertIn(key,s.core.growth['cats']); self.assertNotIn(key,s.core.working_cats)
        self.assertEqual(s.core.summary()['recruitment_expenses'],200)
        from cat_cafe_sim.cafe_cat_details import cat_details
        from cat_cafe_sim.cafe_cat_events import cat_events
        self.assertEqual(dict(cat_details(s,key)['basic'])['加入経路'],'常連からの紹介')
        self.assertTrue(any(row[1]=='加入' for row in cat_events(s.core,key)))
        before=s.core.snapshot()
        with patch.object(s.store,'_write',side_effect=AssertionError('duplicate')):
            s.resolve_regular_introduction('accept')
        self.assertEqual(before,s.core.snapshot()); self.rejected(s,lambda:s.resolve_regular_introduction('decline'))
        s=self.reload(s); s.set_shifts(['cat-mugi',key]); self.close(s); s.next_day()
        self.assertEqual(s.core.day_results[-1]['summary']['recruitment_expenses'],200)
        self.assertEqual(s.core.summary()['recruitment_expenses'],0); self.replay(s)

    def test_waiting_gates_progress_and_viewing_does_not_resolve(self):
        s=self.offered(self.game()); self.replay(s)
        for action in (s.day_off,s.automatic_step,s.open_recruitment,s.expand_seats,s.start_popularity_challenge,
                       lambda:s.play_with_player('cat-mugi'),lambda:legacy_play(s.core,'cat-mugi')):
            self.rejected(s,action)
        s.resolve_regular_introduction('decline'); self.assertFalse(pending(s.core)); s.day_off(); self.replay(s)

    def test_full_or_poor_cannot_accept_but_can_decline_without_penalty(self):
        for options in (dict(full=True),dict(expensive=True)):
            s=self.offered(self.game(**options)); before=s.core.snapshot(); profiles=s.store._read()
            self.rejected(s,lambda:s.resolve_regular_introduction('accept'))
            s.resolve_regular_introduction('decline')
            for key in ('funds','management','customer_loyalty','cats'):
                self.assertEqual(before[key],s.core.snapshot()[key])
            self.assertEqual(profiles,s.store._read()); self.replay(s)

    def test_intake_and_regular_introduction_can_be_answered_in_either_order(self):
        for regular_first in (True,False):
            s=self.offered(self.game(intake=True))
            self.assertEqual(s.core.intake_request['status'],'waiting'); self.replay(s)
            first,second=(s.resolve_regular_introduction,s.resolve_intake_request) if regular_first else (s.resolve_intake_request,s.resolve_regular_introduction)
            first('accept'); second('decline')
            self.assertEqual(len(s.core.cats),6); self.replay(s)

    def test_return_and_dispatch_introduction_coexist_without_deadlock(self):
        from cat_cafe_sim.core.cafe_activities import destinations
        for regular_first in (True,False):
            s=self.game()
            destination=next(row for row in destinations(s.core) if row['id']=='shopping_street_event')
            s.dispatch('cat-mike',destination); s.day_off()
            event=next(iter(s.core.activities['events'].values()))
            s.resolve_dispatch_choice(event['id'],'decline'); self.close(s)
            self.rejected(s,lambda:s.resolve_regular_introduction('decline'))
            s.resolve_activity(event['id']); s.next_day()
            self.assertTrue(pending(s.core)); self.assertEqual(event['introduction']['status'],'waiting')
            self.replay(s)
            first,second=(s.resolve_regular_introduction,lambda choice:s.resolve_dispatch_introduction(event['id'],choice)) if regular_first else (lambda choice:s.resolve_dispatch_introduction(event['id'],choice),s.resolve_regular_introduction)
            first('accept'); second('decline'); self.replay(s)

    def test_write_failure_is_atomic_and_retry_registers_once(self):
        s=self.offered(self.game()); before=s.core.log(); profiles=s.store._read()
        with patch.object(s.store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.resolve_regular_introduction('accept')
        self.assertEqual(before,s.core.log()); self.assertEqual(profiles,s.store._read())
        s=self.reload(s); s.resolve_regular_introduction('accept'); self.replay(s)
        self.assertEqual(sum(e['kind']=='regular_introduction_resolved' for e in s.core.events),1)

    def test_legacy_is_unchanged_all_modes_and_saved_rules(self):
        s=self.offered(self.game())
        with patch('cat_cafe_sim.core.cafe_regular_introduction.rules',side_effect=lambda data:rules(data)):
            self.replay(s)
        for mode in ('popularity','patron','bond','free'):
            s=self.offered(self.game(mode)); s.resolve_regular_introduction('decline'); self.replay(s)
        s=self.game(legacy=True); self.close(s); s.next_day(); s.day_off(); self.replay(s)
        self.assertIsNone(s.core.regular_introduction); self.assertNotIn('regular_introduction',s.core.snapshot())

    def test_pending_goal_can_be_confirmed_before_introduction_after_day_off(self):
        s=self.game('popularity'); self.close(s); self.replay(s)
        self.rejected(s,s.next_day); s.continue_goal(); s.next_day()
        self.assertTrue(pending(s.core))
        # Next-stage selection remains blocked until the introduction is answered.
        self.rejected(s,s.advance_goal)
        s.resolve_regular_introduction('decline'); s.advance_goal(); s.day_off(); self.replay(s)

    def test_id_reservations_and_conflicting_relationship_profile(self):
        s=self.game(); key=next(iter(reserved_ids(s.core)))
        from cat_cafe_sim.core.cafe_recruitment import open_candidates
        self.rejected(s,lambda:open_candidates(s.core,{key:rules()['candidate']}))
        self.rejected(s,lambda:s.core.initialize_pet_shop({key:rules()['candidate']}))
        from cat_cafe_sim.core.cafe_intake_request import rules as intake_rules
        row=intake_rules(); row['cat_id']=key
        self.rejected(s,lambda:s.core.initialize_intake_request(row))
        s=self.offered(s); s.store.register_cat(key,'別の猫',s.interaction_config.personality)
        before=s.core.snapshot()
        with self.assertRaises(RelationshipConflict):s.resolve_regular_introduction('accept')
        self.assertEqual(before,s.core.snapshot())

    def test_single_seat_join_checkpoint_replay_and_later_service(self):
        s=self.offered(self.game(seats=1)); s.resolve_regular_introduction('accept')
        key=s.core.regular_introduction['rules']['cat_id']
        self.assertEqual(len(s.core.cats),6); self.replay(s)
        s.set_shifts([key]); self.close(s); s.next_day(); self.replay(s)

    def test_initialization_rules_game_over_and_pending_save(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.storage.relationships import RelationshipStore
        old=CafeInteractionSession(store=RelationshipStore(Path(self.temp.name)/'old.json'))
        self.rejected(old,old.core.initialize_regular_introduction)
        s=self.game(); self.rejected(s,s.core.initialize_regular_introduction)
        for mutate in (lambda d:d.update(cat_id=''),lambda d:d['candidate'].update(cost=-1),
                       lambda d:d['candidate'].update(features=['unknown'])):
            selected=rules(); mutate(selected)
            with self.assertRaises(ValueError):rules(selected)
        s=self.game(); s.step(); s.start(s.core.queue[0],s.available_cats()[0].id,'seat-1'); s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.finish()
        self.rejected(s,lambda:s.resolve_regular_introduction('decline'))
        s=self.offered(self.game()); s.core.management['game_over']=dict(reason='funds',day=s.core.day)
        self.rejected(s,lambda:s.resolve_regular_introduction('accept'))
        self.rejected(s,lambda:s.resolve_regular_introduction('decline'))

    def test_invalid_state_profile_and_missing_dependencies_rejected(self):
        s=self.offered(self.game()); source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['regular_introduction'].update(status='accepted'),
            lambda d:d['state']['regular_introduction'].update(customer_id='unknown'),
            lambda d:d['state']['regular_introduction'].update(regular_day=2),
            lambda d:d['state']['regular_introduction'].update(presented_day=1),
            lambda d:d['state']['regular_introduction']['rules'].update(cat_id='cat-mugi'),
            lambda d:d['state'].pop('customer_loyalty'),
        ):
            bad=copy.deepcopy(source); mutate(bad); bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        s.resolve_regular_introduction('accept'); self.replay(s)
        source=checkpoint(s.core,set()); bad=copy.deepcopy(source)
        bad['state']['cat_features'][s.core.regular_introduction['rules']['cat_id']]=['white']
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)
        bad=copy.deepcopy(s.checkpoint_baseline); key=s.core.regular_introduction['rules']['cat_id']
        bad['cats'][key]['name']='改変'
        from cat_cafe_sim.storage.cafe_saves import validate_progress
        with self.assertRaises(RelationshipConflict):validate_progress(s.core,bad,bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class RegularIntroductionGuiTests(unittest.TestCase):
    setUp=RegularIntroductionTests.setUp
    game=RegularIntroductionTests.game
    close=RegularIntroductionTests.close
    offered=RegularIntroductionTests.offered

    def test_preparation_attention_cancel_accept_history_and_small_window(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.offered(self.game()); app=CafeInteractionWindow(root,s)
        root.geometry('860x660'); root.update()
        self.assertIn('常連',app.notice.get()); self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke(); window=app.regular_introduction_window
        window.window.geometry('560x420'); root.update()
        self.assertIn('さんから',window.title.get())
        self.assertFalse(window.accept_button.instate(['disabled']))
        for button in (window.accept_button,window.decline_button,window.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),window.window.winfo_rooty()+window.window.winfo_height())
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):window.accept_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):window.accept_button.invoke()
        self.assertEqual(s.core.regular_introduction['status'],'accepted')
        self.assertTrue(window.accept_button.instate(['disabled']))
        self.assertFalse(app.run_button.instate(['disabled']))
        window.close_button.invoke(); app.regular_introduction_button.invoke()
        self.assertIn('迎えました',app.regular_introduction_window.notice.get())
        app.regular_introduction_window.window.destroy()

    def test_full_offer_can_decline_and_legacy_button_is_disabled(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_regular_introduction_gui import CafeRegularIntroductionWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.offered(self.game(full=True)); window=CafeRegularIntroductionWindow(root,s,lambda:None)
        self.assertTrue(window.accept_button.instate(['disabled']))
        self.assertFalse(window.decline_button.instate(['disabled']))
        self.assertIn('満員',window.notice.get())
        with patch('tkinter.messagebox.askyesno',return_value=True):window.decline_button.invoke()
        self.assertEqual(s.core.regular_introduction['status'],'declined'); window.window.destroy()
        s=self.game(legacy=True); app=CafeInteractionWindow(root,s)
        self.assertTrue(app.regular_introduction_button.instate(['disabled']))
