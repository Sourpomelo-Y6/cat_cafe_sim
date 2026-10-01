"""人気第２段階で解放するマイペース向け美術館派遣。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import test_cafe_product_trial_dispatch as fixtures
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_traits import definitions
from cat_cafe_sim.core.cafe_dispatch_unlocks import MUSEUM_ID, museum_destination, reason, rules
from cat_cafe_sim.core.cafe_dispatch_encounters import pending
from cat_cafe_sim.core.cafe_activities import destinations, dispatch_reason, reward
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class MuseumDispatchTests(unittest.TestCase):
    setUp=fixtures.ProductTrialDispatchTests.setUp
    reload_replay=fixtures.ProductTrialDispatchTests.reload_replay
    rejected=fixtures.ProductTrialDispatchTests.rejected

    def game(self,mode='popularity',legacy=False,native=False):
        selected=starting_conditions(mode)
        for key in ('intake_request','regular_introduction','store_events','customer_trust','customer_discontent','reservation'):selected.pop(key)
        selected['management'].update(starting_funds=10000,stress_per_service_tick=0,kitten_probability=0)
        if not native:selected['traits']['cat-mugi']=definitions()['easygoing']
        selected['growth']['threshold']=1000
        selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=30,target=300)])
        if legacy:selected['dispatch_unlocks'].pop(MUSEUM_ID)
        from cat_cafe_sim.core.cafe_health import HealthRules
        with patch.object(HealthRules,'load',return_value=HealthRules(max_probability=0)):
            return create_game(Path(self.temp.name)/'games',selected)

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def unlock(self,s):
        if s.core.objective!='popularity':
            from cat_cafe_sim.core.cafe_popularity_challenge import rules as challenge_rules
            selected=challenge_rules(s.core);selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=30,target=300)])
            s.start_popularity_challenge(selected)
        self.close(s);self.assertNotIn(MUSEUM_ID,s.core.dispatch_unlocks['unlocked']);s.advance_goal();s.next_day()
        self.close(s);self.assertIn(MUSEUM_ID,s.core.dispatch_unlocks['unlocked']);s.advance_goal();s.next_day()
        from cat_cafe_sim.core.cafe_reservation import waiting
        if waiting(s.core):s.resolve_reservation('decline')
        return s

    def depart(self):
        s=self.unlock(self.game());s.dispatch('cat-mugi',museum_destination(s.core))
        return s,'dispatch-3-cat-mugi'

    def test_all_modes_stage_two_without_return_requirement_and_unlock_persists(self):
        for mode in ('popularity','free','bond','patron'):
            with self.subTest(mode=mode):
                s=self.game(mode);row=museum_destination(s.core)
                self.assertIn(row,destinations(s.core));self.assertIn('第2段階',reason(s.core,MUSEUM_ID))
                self.rejected(s,lambda:s.dispatch('cat-mugi',row),'未解放')
                s=self.unlock(s);self.assertEqual(s.core.dispatch_unlocks['unlocked'][MUSEUM_ID]['returns'],0)
                self.assertEqual(reason(s.core,MUSEUM_ID),'');self.reload_replay(s)
                lowered=copy.deepcopy(s.core);lowered.management['popularity']=1
                self.assertEqual(reason(lowered,MUSEUM_ID),'')
                s.day_off();self.reload_replay(s)
        # 高い人気だけでは第２段階達成にならない。
        s=self.game('free');s.core.management['popularity']=250
        self.assertIn('第2段階',reason(s.core,MUSEUM_ID))

    def test_participation_trait_health_fatigue_surplus_and_comparison(self):
        s=self.unlock(self.game());row=museum_destination(s.core)
        self.assertEqual((row['days'],row['reward'],row['max_fatigue'],row['required_trait']),(2,350,40,'easygoing'))
        self.rejected(s,lambda:s.dispatch('cat-kohaku',row),'マイペース')
        core=copy.deepcopy(s.core);core.cats['cat-mugi'].fatigue=40
        self.assertEqual(dispatch_reason(core,'cat-mugi',row),'')
        core.cats['cat-mugi'].fatigue=40.01;self.assertIn('疲労40以下',dispatch_reason(core,'cat-mugi',row))
        core.cats['cat-mugi'].fatigue=0;core.cats['cat-mugi'].health_status='sick'
        self.assertIn('健康',dispatch_reason(core,'cat-mugi',row))
        core.cats['cat-mugi'].health_status='healthy'
        for key in ('cat-kohaku','cat-tama','cat-sora'):core.cats[key].stamina=0
        self.assertIn('席数を超える',dispatch_reason(core,'cat-mugi',row))
        before=s.core.snapshot();preview=next(r for r in comparison_rows(s,'cat-mugi') if r['destination']['id']==MUSEUM_ID)
        self.assertIn('来館者',preview['detail']);self.assertIn('報酬 450',preview['options'][0])
        self.assertIn('ストレス +10',preview['options'][0]);self.assertEqual(s.core.snapshot(),before)
        self.rejected(s,lambda:s.dispatch('cat-mugi',dict(row,reward=999)),'開始時の設定')

    def test_choices_business_rest_return_finance_and_replay(self):
        for choice in ('accept','decline'):
            for rest in (True,False):
                with self.subTest(choice=choice,rest=rest):
                    s,key=self.depart();s=self.reload_replay(s);event=s.core.activities['events'][key]
                    self.assertEqual(event['encounter']['rules']['id'],'museum_visitor_request')
                    for field in ('introduction','trouble'):self.assertNotIn(field,event)
                    if rest:s.day_off()
                    else:self.close(s)
                    self.assertTrue(pending(s.core.activities['events'][key]))
                    for action in (s.day_off,s.next_day,lambda:s.resolve_activity(key)):self.rejected(s,action)
                    s=self.reload_replay(s);funds=s.core.funds;fatigue=s.core.cats['cat-mugi'].fatigue
                    stress=s.core.management['stress']['cat-mugi'];s.resolve_dispatch_choice(key,choice)
                    delta=10 if choice=='accept' else 0;amount=450 if choice=='accept' else 350
                    self.assertEqual(s.core.funds,funds);self.assertEqual(s.core.cats['cat-mugi'].fatigue,fatigue+delta)
                    self.assertEqual(s.core.management['stress']['cat-mugi'],stress+delta)
                    self.assertEqual(reward(s.core,s.core.activities['events'][key]),amount)
                    before=s.core.snapshot();s.resolve_dispatch_choice(key,choice);self.assertEqual(s.core.snapshot(),before)
                    self.rejected(s,lambda:s.resolve_dispatch_choice(key,'decline' if choice=='accept' else 'accept'))
                    s=self.reload_replay(s)
                    if s.core.closed:s.next_day()
                    s.day_off();funds=s.core.funds;s.resolve_activity(key);self.assertEqual(s.core.funds,funds+amount)
                    self.assertEqual(s.core.summary()['dispatch_income'],amount)
                    before=s.core.snapshot();s.resolve_activity(key);self.assertEqual(s.core.snapshot(),before)
                    self.reload_replay(s)

    def test_old_game_saved_settings_retry_and_caps(self):
        old=self.game(legacy=True);self.assertIsNone(museum_destination(old.core))
        self.assertNotIn(MUSEUM_ID,[r['id'] for r in destinations(old.core)])
        self.rejected(old,lambda:old.dispatch('cat-mugi',rules()[MUSEUM_ID]['destination']),'設定がありません')
        self.reload_replay(old)
        s,key=self.depart();original=copy.deepcopy(s.core.activities['events'][key])
        with patch('cat_cafe_sim.core.cafe_dispatch_encounters.for_destination',side_effect=AssertionError('changed')):
            s=self.reload_replay(s);s.day_off()
            capped=copy.deepcopy(s.core);capped.cats['cat-mugi'].fatigue=95;capped.management['stress']['cat-mugi']=95
            capped.resolve_dispatch_choice(key,'accept');self.assertEqual(capped.cats['cat-mugi'].fatigue,100)
            self.assertEqual(capped.management['stress']['cat-mugi'],100)
            s.resolve_dispatch_choice(key,'accept')
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
                with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
            s=self.reload_replay(s);before=s.core.snapshot();s.resolve_dispatch_choice(key,'accept');self.assertEqual(s.core.snapshot(),before)
            s.day_off();s.resolve_activity(key);self.reload_replay(s)
            self.assertEqual(s.core.activities['events'][key]['destination'],original['destination'])

    def test_actual_sixth_rescue_candidate_can_depart(self):
        s=self.unlock(self.game(native=True));s.open_recruitment()
        for _ in range(5):
            for _ in range(3):s.day_off()
            s.open_recruitment()
        key=next(k for k,r in s.core.recruitment['candidates'].items() if r.get('trait',{}).get('id')=='easygoing')
        s.recruit_cat(key);s.dispatch(key,museum_destination(s.core))
        event=s.core.activities['events'][f'dispatch-{s.core.day}-{key}']
        self.assertEqual(event['destination']['id'],MUSEUM_ID)
        self.assertEqual(event['encounter']['rules']['id'],'museum_visitor_request')
        self.reload_replay(s)

    def test_corrupt_stage_unlock_and_departure_rejected(self):
        for value in (True,1,3):
            bad=rules();bad[MUSEUM_ID]['stage']=value
            with self.assertRaises(ValueError):rules(bad)
        s,key=self.depart();source=checkpoint(s.core,set())
        for mutate in (lambda d:d['dispatch_unlocks']['unlocked'][MUSEUM_ID].update(day=1),
                       lambda d:d['dispatch_unlocks']['unlocked'].pop(MUSEUM_ID),
                       lambda d:d['dispatch_unlocks']['rules'].pop(MUSEUM_ID),
                       lambda d:d['activities']['events'][key]['destination'].update(reward=999)):
            bad=copy.deepcopy(source);mutate(bad['state']);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires display')
class MuseumDispatchGuiTests(unittest.TestCase):
    setUp=MuseumDispatchTests.setUp
    game=MuseumDispatchTests.game
    close=MuseumDispatchTests.close
    unlock=MuseumDispatchTests.unlock

    def test_locked_preview_confirmation_choice_return_and_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game();app=CafeInteractionWindow(root,s);app.activity_button.invoke();w=app.activity_window
        w.destination_choice.current(next(i for i,r in enumerate(w.destinations) if r['id']==MUSEUM_ID));w.select_destination()
        self.assertIn('第2段階',w.destination_info.get())
        self.unlock(s);app.refresh();w.refresh();w.cats.selection_set('cat-mugi');w.buttons()
        before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.send_button.invoke()
        self.assertIn('来館者',ask.call_args.args[1]);self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.send_button.invoke()
        s.day_off();w.refresh();w.events.selection_set('dispatch-3-cat-mugi');w.buttons();w.receive_button.invoke()
        child=w.choice_window;child.window.geometry('560x360');root.update()
        self.assertIn('疲労 +10',child.buttons['accept']['text']);self.assertIn('ストレス +10',child.buttons['accept']['text'])
        child.buttons['accept'].invoke();root.update();self.assertIn('帰還報酬：450',child.notice.get())
        self.assertLessEqual(child.buttons['decline'].winfo_rooty()+child.buttons['decline'].winfo_height(),child.window.winfo_rooty()+child.window.winfo_height())
        child.close();s.day_off();w.refresh();w.events.selection_set('dispatch-3-cat-mugi');w.buttons();w.receive_button.invoke();w.result_button.invoke()
        self.assertIn('資金報酬合計：450',w.result_text.get('1.0','end'))
