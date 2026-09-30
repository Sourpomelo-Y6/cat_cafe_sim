import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_visiting_cat import progress, rules, reserved_ids, admission_reason
from cat_cafe_sim.storage.cafe_saves import load_game, save_game, validate_progress
from cat_cafe_sim.storage.relationships import RelationshipConflict


class VisitingCatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.sequence=0

    def game(self,mode='popularity',*,legacy=False,full=False,seats=2,coexist=False):
        self.sequence+=1; selected=starting_conditions(mode)
        selected['seat_count']=seats
        selected['management'].update(starting_funds=10000,stress_per_service_tick=0)
        selected['store_events']['probability']=0
        selected['growth']['threshold']=1000
        selected['goal'].update(target=105,stages=[dict(days=30,target=250),dict(days=30,target=300)])
        selected.pop('customer_discontent'); selected.pop('customer_trust')
        if not coexist:selected.pop('intake_request'); selected.pop('regular_introduction')
        else:
            selected['intake_request']['day']=2
            selected['customer_loyalty']=dict(gain=25,threshold=25)
        if legacy:selected.pop('visiting_cat')
        if full:selected['profiles']['cats']['sixth']=copy.deepcopy(selected['profiles']['cats']['cat-mugi'])
        return create_game(Path(self.temp.name)/str(self.sequence),selected)

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def offered(self,s):
        if s.core.goal.get('tracking_only'):
            from cat_cafe_sim.core.cafe_popularity_challenge import rules as challenge_rules
            selected=challenge_rules(s.core)
            selected['goal'].update(target=105,stages=[dict(days=30,target=250),dict(days=30,target=300)])
            s.start_popularity_challenge(selected)
        self.close(s); self.assertEqual(s.core.goal['status'],'cleared')
        s.advance_goal(); s.next_day(); self.assertEqual(s.core.visiting_cat['status'],'visiting')
        return s

    def ready(self,s):
        s=self.offered(s)
        for i in range(3):
            s.resolve_visiting_cat('interact')
            if i<2:s.day_off()
        self.assertEqual(s.core.visiting_cat['status'],'ready'); return s

    def reload(self,s):
        save_game(s,s.checkpoint_path); loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot()); return loaded

    def replay(self,s):
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def rejected(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(before,s.core.log())

    def test_unlock_next_day_once_daily_skip_and_optional_progress(self):
        s=self.game(); self.assertEqual(s.core.visiting_cat['status'],'untriggered')
        key=next(iter(reserved_ids(s.core))); self.assertNotIn(key,s.core.cats)
        self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s=self.offered(s); before=s.core.snapshot(); s.resolve_visiting_cat('skip')
        self.assertEqual(progress(s.core),0)
        for field in ('funds','cats','management','customer_loyalty'):
            self.assertEqual(before[field],s.core.snapshot()[field])
        self.rejected(s,lambda:s.resolve_visiting_cat('interact')); self.replay(s)
        s.day_off(); s.resolve_visiting_cat('interact'); self.assertEqual(progress(s.core),1)
        self.rejected(s,lambda:s.resolve_visiting_cat('interact')); self.rejected(s,lambda:s.resolve_visiting_cat('accept'))
        s=self.reload(s); s.day_off(); s.day_off()
        self.assertEqual(progress(s.core),1)
        s.resolve_visiting_cat('interact'); s.day_off(); s.resolve_visiting_cat('interact')
        self.assertEqual(s.core.visiting_cat['status'],'ready'); self.assertNotIn(key,s.core.cats)
        self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s.day_off(); s.resolve_visiting_cat('skip'); self.assertEqual(progress(s.core),3)
        self.assertEqual(s.core.visiting_cat['presented_day'],2); self.replay(s)

    def test_accept_profile_traits_health_growth_shifts_finance_and_history(self):
        s=self.game('bond'); s.play_with_player('cat-mugi'); s.player_command(finish=True)
        s=self.ready(s); data=copy.deepcopy(s.core.visiting_cat)
        key=data['rules']['cat_id']; row=data['rules']['candidate']; funds=s.core.funds
        self.assertEqual(len(s.core.cats),5); self.assertNotIn(key,s.core.player_bond['affinity'])
        s.resolve_visiting_cat('accept'); self.assertEqual(s.core.funds,funds-200)
        self.assertEqual(len(s.core.cats),6); self.assertEqual(s.profiles[key]['name'],'ココ')
        self.assertEqual(s.profiles[key]['personality'],row['personality'])
        self.assertEqual(s.core.traits[key],row['trait']); self.assertEqual(s.core.cat_features[key],row['features'])
        self.assertEqual(s.core.cats[key].stamina,s.core.config.max_stamina)
        self.assertEqual((s.core.cats[key].fatigue,s.core.management['stress'][key],s.core.player_bond['affinity'][key]),(0,0,0))
        self.assertEqual(s.core.cats[key].health_status,'healthy'); self.assertNotIn(key,s.core.working_cats)
        self.assertEqual(s.core.growth['cats'][key]['service'],0)
        from cat_cafe_sim.cafe_cat_details import cat_details
        from cat_cafe_sim.cafe_cat_events import cat_events
        self.assertEqual(dict(cat_details(s,key)['basic'])['加入経路'],'店先に通う猫')
        self.assertEqual(sum(row[1]=='店先での交流' for row in cat_events(s.core,key)),3)
        self.assertTrue(any(row[1]=='加入' for row in cat_events(s.core,key)))
        before=s.core.log()
        with patch.object(s.store,'_write',side_effect=AssertionError('duplicate')):s.resolve_visiting_cat('accept')
        self.assertEqual(s.core.log(),before); self.rejected(s,lambda:s.resolve_visiting_cat('skip'))
        s=self.reload(s); s.set_shifts([key,'cat-mugi']); self.close(s)
        self.assertEqual(s.core.summary()['recruitment_expenses'],200)
        s.next_day(); self.assertEqual(s.core.day_results[-1]['summary']['recruitment_expenses'],200)
        self.assertEqual(s.core.summary()['recruitment_expenses'],0); self.replay(s)

    def test_full_housing_retains_ready_progress_and_accept_after_expansion(self):
        s=self.ready(self.game(full=True)); funds=s.core.funds
        self.assertIn('満員',admission_reason(s.core)); self.rejected(s,lambda:s.resolve_visiting_cat('accept'))
        s.day_off(); self.assertEqual(progress(s.core),3)
        s.purchase_housing(); before=s.core.funds; s.resolve_visiting_cat('accept')
        self.assertEqual(s.core.funds,before-200); self.assertEqual(len(s.core.cats),7)
        self.assertLess(s.core.funds,funds); self.replay(s)

    def test_cost_boundary_no_charge_for_interaction_and_ready_state_survives(self):
        s=self.ready(self.game()); s.core.funds=200
        self.rejected(s,lambda:s.resolve_visiting_cat('accept')); self.assertEqual(progress(s.core),3)
        s.core.funds=201; s.core.recorded_digest=None; s.resolve_visiting_cat('accept')
        self.assertEqual(s.core.funds,1); self.assertEqual(s.core.summary()['recruitment_expenses'],200)

    def test_accept_write_failure_is_atomic_retry_registers_once(self):
        s=self.ready(self.game()); before=s.core.log(); profiles=s.store._read()
        with patch.object(s.store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.resolve_visiting_cat('accept')
        self.assertEqual(before,s.core.log()); self.assertEqual(profiles,s.store._read())
        s=self.reload(s); s.resolve_visiting_cat('accept'); self.replay(s)
        self.assertEqual(sum(e['kind']=='visiting_cat_resolved' and e['choice']=='accept' for e in s.core.events),1)

    def test_checkpoint_failure_keeps_one_interaction_and_one_acceptance(self):
        s=self.offered(self.game()); s.resolve_visiting_cat('interact')
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        s=self.reload(s); self.assertEqual(progress(s.core),1)
        self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        for _ in range(2):s.day_off(); s.resolve_visiting_cat('interact')
        s.resolve_visiting_cat('accept'); funds=s.core.funds
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        s=self.reload(s); s.resolve_visiting_cat('accept'); self.assertEqual(s.core.funds,funds); self.replay(s)

    def test_modes_late_challenge_old_save_and_fixed_rules(self):
        for mode in ('popularity','free','bond','patron'):
            s=self.offered(self.game(mode)); s.resolve_visiting_cat('interact')
            with patch('cat_cafe_sim.core.cafe_visiting_cat.rules',side_effect=lambda data:rules(data)):self.replay(s)
        s=self.game('free'); self.close(s); s.next_day(); s=self.offered(s)
        self.assertEqual(s.core.visiting_cat['presented_day'],3); self.replay(s)
        s=self.game(legacy=True); self.close(s); s.advance_goal(); s.next_day()
        self.assertIsNone(s.core.visiting_cat); self.assertNotIn('visiting_cat',s.core.snapshot())
        self.rejected(s,lambda:s.resolve_visiting_cat('interact')); self.replay(s)

    def test_single_seat_join_active_service_save_and_replay(self):
        s=self.ready(self.game(seats=1)); s.resolve_visiting_cat('accept'); key=s.core.visiting_cat['rules']['cat_id']
        s.set_shifts([key]); s.step(); s.start(s.core.queue[0],key)
        s=self.reload(s); s.step('direct'); s.finish(); self.replay(s)

    def test_pending_other_events_player_activity_and_game_over_block_actions(self):
        s=self.offered(self.game(coexist=True))
        self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s.resolve_intake_request('decline'); s.resolve_regular_introduction('decline')
        s.resolve_visiting_cat('interact'); s.day_off()
        s.play_with_player('cat-mugi'); self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s.player_command(finish=True); s.resolve_visiting_cat('interact')
        s.day_off(); s.step(); self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s.finish(); self.close(s); self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s.next_day(); s.core.management['game_over']=dict(reason='funds',day=s.core.day)
        self.rejected(s,lambda:s.resolve_visiting_cat('interact'))

    def test_pending_relationship_persistence_blocks_visiting_actions(self):
        s=self.offered(self.game()); s.step(); s.start(s.core.queue[0],s.available_cats()[0].id,'seat-1'); s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.finish()
        self.assertTrue(s.pending); self.rejected(s,lambda:s.resolve_visiting_cat('interact'))
        s=self.reload(s); s.persist(); self.replay(s)

    def test_reserved_ids_and_external_profile_conflict(self):
        s=self.game(); key=next(iter(reserved_ids(s.core))); row=rules()['candidate']
        self.rejected(s,lambda:s.core.open_recruitment({key:row}))
        self.rejected(s,lambda:s.core.initialize_pet_shop({key:row}))
        from cat_cafe_sim.core.cafe_intake_request import rules as intake_rules
        selected=intake_rules(); selected['cat_id']=key
        self.rejected(s,lambda:s.core.initialize_intake_request(selected))
        from cat_cafe_sim.core.cafe_regular_introduction import rules as regular_rules
        selected=regular_rules(); selected['cat_id']=key
        self.rejected(s,lambda:s.core.initialize_regular_introduction(selected))
        s=self.ready(s); s.store.register_cat(key,'別の猫',s.interaction_config.personality)
        before=s.core.snapshot()
        with self.assertRaises(RelationshipConflict):s.resolve_visiting_cat('accept')
        self.assertEqual(s.core.snapshot(),before)

    def test_bad_settings_progress_dates_goal_profile_and_dependencies_rejected(self):
        for mutate in (lambda d:d.update(interactions_required=True),lambda d:d.update(interactions_required=0),
                       lambda d:d.update(cat_id=''),lambda d:d['candidate'].update(cost=-1)):
            data=rules(); mutate(data)
            with self.assertRaises(ValueError):rules(data)
        s=self.offered(self.game()); s.resolve_visiting_cat('interact'); source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['visiting_cat'].update(status='ready'),
            lambda d:d['state']['visiting_cat'].update(presented_day=1),
            lambda d:d['state']['visiting_cat']['actions'].append(dict(day=2,choice='interact')),
            lambda d:d['state']['visiting_cat']['actions'][0].update(day=3),
            lambda d:d['state']['visiting_cat']['actions'][0].update(choice='accept'),
            lambda d:d['state']['visiting_cat']['rules'].update(cat_id='cat-mugi'),
            lambda d:d['state']['goal']['history'][0].update(resolved_day=None),
            lambda d:d['state'].pop('health'),lambda d:d['state'].pop('goal')):
            bad=copy.deepcopy(source); mutate(bad); bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        for _ in range(2):s.day_off(); s.resolve_visiting_cat('interact')
        s.resolve_visiting_cat('accept'); self.replay(s); key=s.core.visiting_cat['rules']['cat_id']
        source=checkpoint(s.core,set()); bad=copy.deepcopy(source); bad['state']['visiting_cat'].update(accepted_day=2)
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)
        bad=copy.deepcopy(source); bad['state']['cat_features'][key]=['white']; bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)
        bad=copy.deepcopy(s.checkpoint_baseline); bad['cats'][key]['name']='変更'
        with self.assertRaises(RelationshipConflict):validate_progress(s.core,bad,bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class VisitingCatGuiTests(unittest.TestCase):
    setUp=VisitingCatTests.setUp
    game=VisitingCatTests.game
    close=VisitingCatTests.close
    offered=VisitingCatTests.offered
    ready=VisitingCatTests.ready

    def test_cancel_daily_buttons_optional_notice_ready_and_accept(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.offered(self.game()); app=CafeInteractionWindow(root,s)
        self.assertIn('店先',app.notice.get()); self.assertFalse(app.run_button.instate(['disabled']))
        app.visiting_cat_button.invoke(); w=app.visiting_cat_window
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False):w.interact_button.invoke()
        self.assertEqual(before,s.core.snapshot())
        with patch('tkinter.messagebox.askyesno',return_value=True):w.interact_button.invoke()
        self.assertIn('1/3',w.title.get()); self.assertTrue(w.interact_button.instate(['disabled']))
        self.assertTrue(w.accept_button.instate(['disabled'])); w.close_button.invoke()
        for _ in range(2):s.day_off(); s.resolve_visiting_cat('interact')
        app.refresh(); app.visiting_cat_button.invoke(); w=app.visiting_cat_window
        self.assertFalse(w.accept_button.instate(['disabled']))
        with patch('tkinter.messagebox.askyesno',return_value=True):w.accept_button.invoke()
        self.assertIn('迎えました',w.notice.get()); self.assertEqual(s.core.visiting_cat['status'],'accepted')
        self.assertTrue(w.accept_button.instate(['disabled'])); w.window.destroy()

    def test_full_housing_expansion_minimum_layout_and_legacy_button(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_visiting_cat_gui import CafeVisitingCatWindow
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s=self.ready(self.game(full=True)); w=CafeVisitingCatWindow(root,s,lambda:None)
        w.window.geometry('560x420'); root.update()
        self.assertTrue(w.accept_button.instate(['disabled'])); self.assertIn('満員',w.notice.get())
        self.assertFalse(w.housing_button.instate(['disabled'])); w.housing_button.invoke()
        with patch('tkinter.messagebox.askyesno',return_value=True):w.housing_window.purchase_button.invoke()
        w.housing_window.close(); self.assertFalse(w.accept_button.instate(['disabled']))
        for button in (w.interact_button,w.skip_button,w.accept_button,w.housing_button,w.close_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),w.window.winfo_rootx()+w.window.winfo_width())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
        w.window.destroy(); app=CafeInteractionWindow(root,self.game(legacy=True))
        self.assertTrue(app.visiting_cat_button.instate(['disabled']))
