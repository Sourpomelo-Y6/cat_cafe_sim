"""美術館の長毛・派遣得意の歓迎補正と、旧設定の固定。"""
import copy
import os
import unittest
from unittest.mock import patch
import test_cafe_museum_dispatch as fixtures
from pathlib import Path
from cat_cafe_sim.cafe_new_game import starting_conditions,create_game
from cat_cafe_sim.core.cafe_dispatch_unlocks import MUSEUM_ID, museum_destination
from cat_cafe_sim.core.cafe_dispatch_match import terms
from cat_cafe_sim.core.cafe_growth import pending
from cat_cafe_sim.core.cafe_activities import reward
from cat_cafe_sim.core.cafe_items import inventory
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
from cat_cafe_sim.cafe_dispatch_results import result_rows
from cat_cafe_sim.storage.cafe_saves import save_game


class MuseumDispatchMatchTests(unittest.TestCase):
    setUp=fixtures.MuseumDispatchTests.setUp
    unlock=fixtures.MuseumDispatchTests.unlock
    reload_replay=fixtures.MuseumDispatchTests.reload_replay

    def game(self,long=False,dispatch=False,legacy=False):
        self.dispatch_specialization=dispatch
        data=starting_conditions('popularity')
        for key in ('intake_request','regular_introduction','store_events','customer_trust','customer_discontent','reservation'):data.pop(key)
        data['management'].update(starting_funds=10000,stress_per_service_tick=0,kitten_probability=0)
        from cat_cafe_sim.core.cafe_traits import definitions
        data['traits']['cat-mugi']=definitions()['easygoing']
        data['features']['cat-mugi']=['orange_tabby','long_hair' if long else 'short_hair']
        data['growth']['threshold']=1
        data['growth']['mastery_threshold']=1000
        data['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=30,target=300)])
        if legacy:data['dispatch_unlocks'][MUSEUM_ID]['destination'].pop('welcome')
        from cat_cafe_sim.core.cafe_health import HealthRules
        with patch.object(HealthRules,'load',return_value=HealthRules(max_probability=0)):
            s=create_game(Path(self.temp.name)/'games',data)
        s.set_shifts([key for key in s.core.cats if key!='cat-mugi'])
        return self.unlock(s)

    def close(self,s):
        while True:
            for key in pending(s.core):
                s.resolve_growth(key,'dispatch' if key=='cat-mugi' and self.dispatch_specialization else 'service')
            if s.core.closed:break
            s.automatic_step()

    def depart(self,s):
        s.dispatch('cat-mugi',museum_destination(s.core));return f'dispatch-{s.core.day}-cat-mugi'

    def receive(self,s,key,choice):
        s.day_off();s.resolve_dispatch_choice(key,choice);s.day_off();s.resolve_activity(key)
        for cat_id in pending(s.core):s.resolve_growth(cat_id,'service')

    def test_all_modes_default_and_four_independent_matches_preview_and_freeze(self):
        for mode in ('popularity','free','bond','patron'):
            self.assertEqual(starting_conditions(mode)['dispatch_unlocks'][MUSEUM_ID]['destination']['welcome'],
                             dict(feature='long_hair',specialization='dispatch',reward_bonus=20,satisfaction_bonus=0))
        for long in (False,True):
            for dispatch in (False,True):
                with self.subTest(long=long,dispatch=dispatch):
                    s=self.game(long,dispatch);destination=museum_destination(s.core)
                    expected=dict(feature_matched=long,specialization_matched=dispatch,reward_bonus=20*(long+dispatch),satisfaction_bonus=0)
                    self.assertEqual(terms(s.core,'cat-mugi',destination),expected)
                    before=s.core.snapshot();row=next(r for r in comparison_rows(s,'cat-mugi') if r['destination']['id']==MUSEUM_ID)
                    self.assertIn(f'追加報酬 {20*(long+dispatch)}',row['detail']);self.assertEqual(s.core.snapshot(),before)
                    key=self.depart(s);self.assertEqual(s.core.activities['events'][key]['welcome_match'],expected)
                    self.reload_replay(s)

    def test_growth_bonus_choices_brushing_set_finance_and_duplicate_return(self):
        for dispatch in (False,True):
            for choice in ('accept','decline'):
                s=self.game(long=True,dispatch=dispatch);key=self.depart(s);s=self.reload_replay(s)
                self.receive(s,key,choice);event=s.core.activities['events'][key]
                expected=350*(1.1 if dispatch else 1)+20*(1+dispatch)+(100 if choice=='accept' else 0)
                self.assertAlmostEqual(reward(s.core,event),expected)
                # 休業中の費用とは分けて、派遣収入そのものを検証する。
                self.assertAlmostEqual(s.core.summary()['dispatch_income'],expected)
                self.assertEqual(inventory(s.core)[key]['id'],'brushing_set')
                rows=dict(result_rows(s.core,event));self.assertEqual(rows['歓迎ボーナス'],f'+{20*(1+dispatch)}')
                self.assertEqual(rows['イベント増減'],'+100' if choice=='accept' else '+0')
                before=s.core.snapshot();s.resolve_activity(key);self.assertEqual(s.core.snapshot(),before)
                self.reload_replay(s)

    def test_legacy_destination_departure_settings_and_replay_kept(self):
        s=self.game(long=True,dispatch=True,legacy=True);self.assertNotIn('welcome',museum_destination(s.core))
        key=self.depart(s);s=self.reload_replay(s);self.receive(s,key,'accept')
        self.assertNotIn('welcome_match',s.core.activities['events'][key]);self.assertAlmostEqual(reward(s.core,s.core.activities['events'][key]),485)
        self.reload_replay(s)
        s=self.game(long=True,dispatch=True);key=self.depart(s);original=copy.deepcopy(s.core.activities['events'][key])
        with patch('cat_cafe_sim.core.cafe_dispatch_unlocks.Path',side_effect=AssertionError('changed config')):
            s=self.reload_replay(s);self.receive(s,key,'accept');self.reload_replay(s)
        self.assertEqual(s.core.activities['events'][key]['welcome_match'],original['welcome_match'])
        self.assertAlmostEqual(reward(s.core,s.core.activities['events'][key]),525)

    def test_save_retry_and_corrupt_welcome_match_rejected(self):
        s=self.game(long=True,dispatch=True);key=self.depart(s);self.receive(s,key,'accept')
        source=checkpoint(s.core,set())
        for changes in (dict(reward_bonus=0),dict(feature_matched=False),dict(specialization_matched=False),dict(satisfaction_bonus=20)):
            bad=copy.deepcopy(source);bad['state']['activities']['events'][key]['welcome_match'].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        s=self.reload_replay(s);before=s.core.snapshot();s.resolve_activity(key);self.assertEqual(s.core.snapshot(),before)
        self.assertAlmostEqual(s.core.summary()['dispatch_income'],525);self.assertIn(key,inventory(s.core))
        self.reload_replay(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires display')
class MuseumDispatchMatchGuiTests(unittest.TestCase):
    setUp=MuseumDispatchMatchTests.setUp
    game=MuseumDispatchMatchTests.game
    close=MuseumDispatchMatchTests.close
    unlock=MuseumDispatchMatchTests.unlock
    depart=MuseumDispatchMatchTests.depart
    receive=MuseumDispatchMatchTests.receive

    def test_selection_confirmation_and_return_breakdown(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game(long=True,dispatch=True);app=CafeInteractionWindow(root,s);app.activity_button.invoke();w=app.activity_window
        w.destination_choice.current(next(i for i,r in enumerate(w.destinations) if r['id']==MUSEUM_ID));w.select_destination()
        w.cats.selection_set('cat-mugi');w.buttons();root.update();before=s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False) as ask:w.send_button.invoke()
        prompt=ask.call_args.args[1]
        self.assertIn('長毛 一致',prompt);self.assertIn('得意分野 派遣 一致',prompt);self.assertIn('追加報酬 40',prompt)
        self.assertIn('報酬見込み 425',prompt);self.assertEqual(s.core.snapshot(),before)
        self.assertIn('報酬見込み 425',w.selection_info.get())
        key=self.depart(s);self.receive(s,key,'accept');w.refresh();w.events.selection_set(key);w.buttons();w.result_button.invoke();root.update()
        text=w.result_text.get('1.0','end');self.assertIn('歓迎ボーナス：+40',text)
        self.assertIn('イベント増減：+100',text);self.assertIn('資金報酬合計：525',text)
        self.assertIn('ブラッシングセット ×1',text)
