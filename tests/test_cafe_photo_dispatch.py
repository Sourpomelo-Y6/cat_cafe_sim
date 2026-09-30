"""接客好き向け撮影スタジオと、専用の追加撮影イベント。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

import test_cafe_exercise_dispatch as fixtures
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_activities import destinations, dispatch_reason, reward
from cat_cafe_sim.core.cafe_dispatch_unlocks import PHOTO_ID, photo_destination, reason, rules
from cat_cafe_sim.core.cafe_dispatch_encounters import for_destination, pending
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.cafe_dispatch_results import result_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class PhotoDispatchTests(unittest.TestCase):
    setUp = fixtures.ExerciseDispatchTests.setUp
    reload_replay = fixtures.ExerciseDispatchTests.reload_replay
    rejected = fixtures.ExerciseDispatchTests.rejected

    def game(self, mode='free', threshold=100, legacy=False, no_unlocks=False, growth_threshold=1000):
        selected = starting_conditions(mode)
        for key in ('store_events', 'intake_request', 'regular_introduction', 'customer_trust', 'customer_discontent'):
            selected.pop(key)
        selected['management'].update(starting_funds=10000, stress_per_service_tick=0)
        selected['growth']['threshold'] = growth_threshold
        selected['dispatch_unlocks'][PHOTO_ID]['popularity'] = threshold
        if legacy:
            selected['dispatch_unlocks'].pop(PHOTO_ID)
        if no_unlocks:
            selected.pop('dispatch_unlocks')
        return create_game(Path(self.temp.name)/'games', selected)

    def unlock(self, s):
        s.dispatch('cat-sora'); event_id=f'dispatch-{s.core.day}-cat-sora'
        s.day_off(); s.resolve_activity(event_id)
        return s

    def depart(self):
        s=self.unlock(self.game())
        s.dispatch('cat-mike', photo_destination(s.core))
        return s, 'dispatch-2-cat-mike'

    def test_default_all_modes_unlock_and_exclusive_event_definition(self):
        for mode in ('free', 'popularity', 'bond', 'patron'):
            s=self.game(mode=mode, threshold=120)
            row=photo_destination(s.core)
            self.assertEqual((row['name'],row['days'],row['reward'],row['max_fatigue'],row['required_trait']),
                             ('猫の撮影スタジオ',2,350,40,'hospitality'))
            self.assertIn(row,destinations(s.core))
            self.assertEqual(destinations(s.core)[:3],destinations())
            self.rejected(s,lambda:s.dispatch('cat-mike',row),'未解放')
            self.reload_replay(s)
        event=for_destination(row)
        self.assertEqual(event['id'],'extra_photo_session')
        self.assertEqual([(r['id'],r['reward'],r['fatigue'],r['stress']) for r in event['choices']],
                         [('accept',100,15,15),('decline',0,5,5)])
        self.assertIsNone(for_destination(destinations()[0]))
        self.assertEqual(for_destination(destinations()[1])['id'],'extra_work')
        self.assertEqual(for_destination(destinations()[2])['id'],'rest_stop')
        self.assertEqual(for_destination(s.core.dispatch_unlocks['rules']['cat_exercise_class']['destination'])['id'],'exercise_program')
        self.assertIsNone(for_destination(s.core.dispatch_trouble['destination']))

    def test_popularity_and_received_reward_both_needed_and_unlock_persists(self):
        s=self.unlock(self.game(threshold=101))
        self.assertIn('100/101',reason(s.core,PHOTO_ID))
        self.assertIn('1/1',reason(s.core,PHOTO_ID))
        s=self.game(); s.dispatch('cat-sora'); s.day_off()
        self.assertNotIn(PHOTO_ID,s.core.dispatch_unlocks['unlocked'])
        s.resolve_activity('dispatch-1-cat-sora')
        self.assertEqual(s.core.dispatch_unlocks['unlocked'][PHOTO_ID],dict(day=2,popularity=100,returns=1))
        before=s.core.snapshot();s.resolve_activity('dispatch-1-cat-sora')
        self.assertEqual(s.core.snapshot(),before)
        lowered=copy.deepcopy(s.core);lowered.management['popularity']=1
        self.assertEqual(reason(lowered,PHOTO_ID),'')
        self.reload_replay(s)
        s=self.game(threshold=120)
        for _ in range(10):
            while not s.core.closed:s.automatic_step()
            s.next_day()
            if s.core.management['popularity']>=120:break
        self.assertGreaterEqual(s.core.management['popularity'],120)
        self.assertNotIn(PHOTO_ID,s.core.dispatch_unlocks['unlocked'])
        self.unlock(s);self.assertEqual(reason(s.core,PHOTO_ID),'')
        self.reload_replay(s)

    def test_trait_id_fatigue_health_surplus_pending_and_frozen_destination(self):
        s=self.unlock(self.game());row=photo_destination(s.core)
        self.rejected(s,lambda:s.dispatch('cat-kohaku',row),'接客好き')
        core=copy.deepcopy(s.core);core.traits['cat-kohaku']['name']='接客好き'
        self.assertIn('接客好き',dispatch_reason(core,'cat-kohaku',row))
        core.cats['cat-mike'].fatigue=40
        self.assertEqual(dispatch_reason(core,'cat-mike',row),'')
        core.cats['cat-mike'].fatigue=40.01
        self.assertIn('疲労40以下',dispatch_reason(core,'cat-mike',row))
        core.cats['cat-mike'].fatigue=0;core.cats['cat-mike'].health_status='sick'
        self.assertIn('健康',dispatch_reason(core,'cat-mike',row))
        core.cats['cat-mike'].health_status='healthy'
        for key in ('cat-kohaku','cat-tama','cat-sora'):core.cats[key].stamina=0
        self.assertIn('席数を超える',dispatch_reason(core,'cat-mike',row))
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            self.rejected(s,lambda:s.dispatch('cat-mike',row),'未保存')
        self.rejected(s,lambda:s.dispatch('cat-mike',dict(row,reward=999)),'開始時の設定')
        s.play_with_player('cat-mike');self.rejected(s,lambda:s.dispatch('cat-mike',row))

    def test_accept_decline_business_rest_return_finance_growth_and_replay(self):
        for choice in ('accept','decline'):
            for rest in (False,True):
                s,event_id=self.depart();s=self.reload_replay(s)
                for field in ('trouble','introduction','item_reward'):
                    self.assertNotIn(field,s.core.activities['events'][event_id])
                self.rejected(s,lambda:s.dispatch('cat-mike',photo_destination(s.core)))
                if rest:s.day_off()
                else:
                    while not s.core.closed:s.automatic_step()
                self.assertTrue(pending(s.core.activities['events'][event_id]))
                self.assertEqual(s.core.activities['events'][event_id]['remaining'],1)
                for action in (s.day_off,s.next_day,s.automatic_step,lambda:s.resolve_activity(event_id)):
                    self.rejected(s,action)
                s=self.reload_replay(s);funds=s.core.funds;fatigue=s.core.cats['cat-mike'].fatigue
                stress=s.core.management['stress']['cat-mike']
                s.resolve_dispatch_choice(event_id,choice)
                expected=450 if choice=='accept' else 350
                self.assertEqual(s.core.funds,funds)
                self.assertEqual(s.core.cats['cat-mike'].fatigue,fatigue+(15 if choice=='accept' else 5))
                self.assertEqual(s.core.management['stress']['cat-mike'],stress+(15 if choice=='accept' else 5))
                self.assertEqual(reward(s.core,s.core.activities['events'][event_id]),expected)
                before=s.core.snapshot();s.resolve_dispatch_choice(event_id,choice)
                self.assertEqual(s.core.snapshot(),before)
                self.rejected(s,lambda:s.resolve_dispatch_choice(event_id,'decline' if choice=='accept' else 'accept'))
                s=self.reload_replay(s)
                if s.core.closed:s.next_day()
                s.day_off();funds=s.core.funds;s.resolve_activity(event_id)
                self.assertEqual(s.core.funds,funds+expected)
                self.assertEqual(s.core.summary()['dispatch_income'],expected)
                self.assertEqual(s.core.growth['cats']['cat-mike']['dispatch'],1)
                before=s.core.snapshot();s.resolve_activity(event_id);self.assertEqual(s.core.snapshot(),before)
                self.assertEqual(dict(result_rows(s.core,s.core.activities['events'][event_id]))['イベント増減'],'+100' if choice=='accept' else '+0')
                s=self.reload_replay(s);s.day_off()
                self.assertEqual(s.core.day_results[-1]['summary']['dispatch_income'],expected)
                self.reload_replay(s)

    def test_growth_reward_and_stress_cap_and_other_waiting_return(self):
        from cat_cafe_sim.core.cafe_growth import pending as growth_pending
        s=self.unlock(self.game(growth_threshold=1))
        for key in growth_pending(s.core):s.resolve_growth(key,'dispatch')
        s.dispatch('cat-mike',photo_destination(s.core));event_id='dispatch-2-cat-mike'
        s.dispatch('cat-sora');other='dispatch-2-cat-sora';s.day_off()
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            self.rejected(s,lambda:s.resolve_dispatch_choice(event_id,'accept'),'保存を再試行')
        capped=copy.deepcopy(s.core);capped.management['stress']['cat-mike']=95
        capped.cats['cat-mike'].fatigue=95
        capped.resolve_dispatch_choice(event_id,'accept')
        self.assertEqual(capped.management['stress']['cat-mike'],100)
        self.assertEqual(capped.cats['cat-mike'].fatigue,100)
        s.resolve_dispatch_choice(event_id,'accept');self.rejected(s,s.day_off)
        s.resolve_activity(other);s.day_off();funds=s.core.funds;s.resolve_activity(event_id)
        self.assertAlmostEqual(s.core.funds,funds+485)
        self.assertEqual(s.core.management['stress']['cat-mike'],15)
        self.reload_replay(s)

    def test_old_games_and_departed_records_stay_unchanged(self):
        for no_unlocks in (False,True):
            s=self.game(legacy=True,no_unlocks=no_unlocks)
            self.assertIsNone(photo_destination(s.core))
            self.assertNotIn(PHOTO_ID,[r['id'] for r in destinations(s.core)])
            self.rejected(s,lambda:s.dispatch('cat-mike',rules()[PHOTO_ID]['destination']),'設定がありません')
            s.dispatch('cat-sora');original=copy.deepcopy(s.core.activities['events']['dispatch-1-cat-sora'])
            s=self.reload_replay(s)
            self.assertEqual(s.core.activities['events']['dispatch-1-cat-sora'],original)
        # An older start operation with no encounter is replayed without adding one.
        s=self.unlock(self.game());s.core.dispatch('cat-mike',photo_destination(s.core))
        event_id='dispatch-2-cat-mike';s=self.reload_replay(s);s.day_off();s.day_off()
        self.assertNotIn('encounter',s.core.activities['events'][event_id])
        funds=s.core.funds;s.resolve_activity(event_id);self.assertEqual(s.core.funds,funds+350)
        self.reload_replay(s)

    def test_saved_settings_and_save_retry_do_not_repeat_stress_or_payment(self):
        s,event_id=self.depart();original=copy.deepcopy(s.core.activities['events'][event_id])
        with patch('cat_cafe_sim.core.cafe_dispatch_encounters.for_destination',side_effect=AssertionError('changed')):
            s=self.reload_replay(s);s.day_off();s.resolve_dispatch_choice(event_id,'accept')
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
            s=self.reload_replay(s);s.resolve_dispatch_choice(event_id,'accept')
            self.assertEqual(s.core.management['stress']['cat-mike'],15)
            s.day_off();funds=s.core.funds;s.resolve_activity(event_id)
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
            with patch('cat_cafe_sim.core.cafe_dispatch_unlocks.rules',side_effect=lambda data:rules(data)):
                s=self.reload_replay(s)
            s.resolve_activity(event_id)
            self.assertEqual(s.core.funds,funds+450)
            event=s.core.activities['events'][event_id]
            self.assertEqual(event['destination'],original['destination'])
            self.assertEqual(event['encounter']['rules'],original['encounter']['rules'])
            self.reload_replay(s)

    def test_invalid_settings_destinations_and_event_effects_rejected(self):
        for mutate in (lambda d:d[PHOTO_ID].pop('destination'),
                       lambda d:d[PHOTO_ID]['destination'].update(required_trait='hardy'),
                       lambda d:d[PHOTO_ID]['destination'].update(id='cat_exercise_class'),
                       lambda d:d[PHOTO_ID].update(returns=True)):
            bad=rules();mutate(bad)
            with self.assertRaises(ValueError):rules(bad)
        s,event_id=self.depart();s.day_off();s.resolve_dispatch_choice(event_id,'accept')
        source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['dispatch_unlocks']['rules'].pop(PHOTO_ID),
                       lambda d:d['state'].pop('dispatch_unlocks'),
                       lambda d:d['state']['activities']['events'][event_id]['destination'].update(reward=999),
                       lambda d:d['state']['activities']['events'][event_id]['encounter'].update(choice='bad'),
                       lambda d:d['state']['activities']['events'][event_id]['encounter'].update(occurred_day=1),
                       lambda d:d['state']['activities']['events'][event_id]['encounter']['changes'].update(stress_after=0)):
            bad=copy.deepcopy(source);mutate(bad)
            bad['digest']=digest({key:value for key,value in bad.items() if key!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires desktop')
class PhotoDispatchGuiTests(unittest.TestCase):
    setUp=PhotoDispatchTests.setUp
    game=PhotoDispatchTests.game
    unlock=PhotoDispatchTests.unlock

    def test_destination_confirmation_choice_stress_and_return_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game();app=CafeInteractionWindow(root,s)
        app.activity_button.invoke();activity=app.activity_window
        index=next(i for i,row in enumerate(activity.destinations) if row['id']==PHOTO_ID)
        activity.destination_choice.current(index);activity.select_destination()
        self.assertIn('未解放',activity.destination_info.get())
        self.unlock(s);app.refresh();activity.refresh()
        self.assertTrue(any('派遣先を解放：猫の撮影スタジオ' in str(app.history.item(key)['values']) for key in app.history.get_children()))
        activity.window.geometry('500x400');root.update()
        self.assertIn('接客好き',activity.destination_info.get())
        activity.cats.selection_set('cat-kohaku');activity.buttons()
        self.assertTrue(activity.send_button.instate(['disabled']))
        activity.cats.selection_set('cat-mike');activity.buttons()
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:activity.send_button.invoke()
        self.assertIn('追加の撮影',confirm.call_args.args[1])
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):activity.send_button.invoke()
        s.day_off();app.refresh();activity.refresh();event_id='dispatch-2-cat-mike'
        activity.events.selection_set(event_id);activity.buttons();activity.receive_button.invoke()
        child=activity.choice_window;child.window.geometry('560x360');root.update()
        self.assertIn('ストレス +15',child.buttons['accept']['text'])
        self.assertIn('疲労 +15',child.buttons['accept']['text'])
        child.close();self.assertTrue(pending(s.core.activities['events'][event_id]))
        activity.receive_button.invoke();child=activity.choice_window;child.buttons['accept'].invoke();root.update()
        self.assertIn('ストレス 0 → 15',child.notice.get())
        self.assertIn('帰還報酬：450',child.notice.get())
        self.assertTrue(child.buttons['accept'].instate(['disabled']))
        self.assertLessEqual(child.buttons['decline'].winfo_rooty()+child.buttons['decline'].winfo_height(),child.window.winfo_rooty()+child.window.winfo_height())
        child.close();s.day_off();activity.refresh();activity.events.selection_set(event_id);activity.buttons()
        activity.receive_button.invoke();activity.result_button.invoke();root.update()
        self.assertIn('資金報酬合計：450',activity.result_text.get('1.0','end'))
