"""撮影スタジオの歓迎条件、旧設定と紹介・追加撮影の併用。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_cafe_photo_introduction as fixtures
from cat_cafe_sim.cafe_new_game import starting_conditions, create_game
from cat_cafe_sim.core.cafe_dispatch_unlocks import photo_destination
from cat_cafe_sim.core.cafe_dispatch_match import terms
from cat_cafe_sim.core.cafe_growth import pending as growth_pending
from cat_cafe_sim.core.cafe_activities import reward, dispatch_reason
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.cafe_dispatch_results import result_rows


class PhotoDispatchMatchTests(unittest.TestCase):
    setUp=fixtures.PhotoIntroductionTests.setUp
    unlock=fixtures.PhotoIntroductionTests.unlock
    depart=fixtures.PhotoIntroductionTests.depart
    receive=fixtures.PhotoIntroductionTests.receive
    reload_replay=fixtures.PhotoIntroductionTests.reload_replay

    def game(self,white=False,service=False,legacy=False,mode='free'):
        selected=starting_conditions(mode)
        for key in ('store_events','intake_request','regular_introduction','customer_trust','customer_discontent'):
            selected.pop(key)
        selected['management'].update(starting_funds=10000,stress_per_service_tick=0)
        selected['features']['cat-mike']=['white','short_hair'] if white else ['calico','short_hair']
        selected['growth']['threshold']=1
        selected['dispatch_unlocks']['cat_photo_studio']['popularity']=100
        if legacy:selected['dispatch_unlocks']['cat_photo_studio']['destination'].pop('welcome')
        s=self.unlock(create_game(Path(self.temp.name)/'games',selected))
        for key in growth_pending(s.core):s.resolve_growth(key,'service' if key=='cat-mike' and service else 'dispatch')
        return s

    def test_all_modes_default_and_four_independent_matches(self):
        for mode in ('free','popularity','bond','patron'):
            selected=starting_conditions(mode)['dispatch_unlocks']['cat_photo_studio']['destination']['welcome']
            self.assertEqual(selected,dict(feature='white',specialization='service',reward_bonus=20,satisfaction_bonus=0))
        for white in (False,True):
            for service in (False,True):
                s=self.game(white,service);destination=photo_destination(s.core)
                matched=terms(s.core,'cat-mike',destination)
                self.assertEqual(matched,dict(feature_matched=white,specialization_matched=service,reward_bonus=20*(white+service),satisfaction_bonus=0))
                self.assertEqual(dispatch_reason(s.core,'cat-mike',destination),'')
                event_id=self.depart(s);event=s.core.activities['events'][event_id]
                self.assertEqual(event['welcome_match'],matched)
                self.reload_replay(s)

    def test_both_choices_growth_bonus_intro_finance_and_duplicate_return(self):
        for service in (False,True):
            for choice in ('accept','decline'):
                s=self.game(white=True,service=service);event_id=self.depart(s)
                s=self.reload_replay(s);self.receive(s,event_id,choice)
                event=s.core.activities['events'][event_id]
                expected=350*(1 if service else 1.1)+20*(1+service)+(100 if choice=='accept' else 0)
                self.assertAlmostEqual(reward(s.core,event),expected)
                self.assertAlmostEqual(s.core.summary()['dispatch_income'],expected)
                rows=dict(result_rows(s.core,event));self.assertEqual(rows['歓迎ボーナス'],f'+{20*(1+service)}')
                self.assertEqual(rows['イベント増減'],'+100' if choice=='accept' else '+0')
                self.assertIn('ルカ',rows['紹介された猫'])
                before=s.core.snapshot();s.resolve_activity(event_id);self.assertEqual(s.core.snapshot(),before)
                funds=s.core.funds;s.resolve_dispatch_introduction(event_id,'accept')
                self.assertEqual(s.core.funds,funds-250);self.assertEqual(s.core.summary()['recruitment_expenses'],250)
                self.reload_replay(s)

    def test_old_saved_destination_and_departure_keep_original_terms(self):
        s=self.game(white=True,service=True,legacy=True);destination=photo_destination(s.core)
        self.assertNotIn('welcome',destination);event_id=self.depart(s)
        s=self.reload_replay(s);self.receive(s,event_id,'accept')
        event=s.core.activities['events'][event_id]
        self.assertNotIn('welcome_match',event);self.assertEqual(reward(s.core,event),450)
        s.resolve_dispatch_introduction(event_id,'decline');self.reload_replay(s)
        s=self.game(white=True,service=True);event_id=self.depart(s)
        original=copy.deepcopy(s.core.activities['events'][event_id])
        with patch('cat_cafe_sim.core.cafe_dispatch_unlocks.Path',side_effect=AssertionError('new config')):
            s=self.reload_replay(s)
        self.assertEqual(s.core.activities['events'][event_id],original)

    def test_save_retry_and_corrupt_match_are_rejected(self):
        from cat_cafe_sim.storage.cafe_saves import save_game
        s=self.game(white=True,service=True);event_id=self.depart(s);self.receive(s,event_id,'accept')
        source=checkpoint(s.core,set())
        for changes in (dict(reward_bonus=0),dict(feature_matched=False),dict(specialization_matched=False),dict(satisfaction_bonus=20)):
            bad=copy.deepcopy(source);bad['state']['activities']['events'][event_id]['welcome_match'].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        s=self.reload_replay(s);before=s.core.snapshot();s.resolve_activity(event_id)
        self.assertEqual(s.core.snapshot(),before);self.assertEqual(s.core.summary()['dispatch_income'],490)
        s.resolve_dispatch_introduction(event_id,'decline');self.reload_replay(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class PhotoDispatchMatchGuiTests(unittest.TestCase):
    setUp=PhotoDispatchMatchTests.setUp
    game=PhotoDispatchMatchTests.game
    unlock=PhotoDispatchMatchTests.unlock
    depart=PhotoDispatchMatchTests.depart
    receive=PhotoDispatchMatchTests.receive

    def test_candidate_confirmation_and_return_breakdown(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game(white=True,service=True);app=CafeInteractionWindow(root,s)
        app.activity_button.invoke();activity=app.activity_window
        index=next(i for i,row in enumerate(activity.destinations) if row['id']=='cat_photo_studio')
        activity.destination_choice.current(index);activity.select_destination()
        activity.cats.selection_set('cat-mike');activity.buttons();root.update()
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:activity.send_button.invoke()
        prompt=confirm.call_args.args[1]
        self.assertIn('白猫 一致',prompt);self.assertIn('得意分野 接客 一致',prompt);self.assertIn('追加報酬 40',prompt);self.assertIn('報酬見込み 390',prompt)
        self.assertIn('報酬見込み 390',activity.selection_info.get())
        self.assertIn('追加報酬 40',str(activity.cats.item('cat-mike','values')))
        event_id=self.depart(s);self.receive(s,event_id,'accept');s.resolve_dispatch_introduction(event_id,'decline')
        activity.refresh();activity.events.selection_set(event_id);activity.buttons();activity.result_button.invoke();root.update()
        text=activity.result_text.get('1.0','end')
        self.assertIn('歓迎ボーナス：+40',text);self.assertIn('イベント増減：+100',text);self.assertIn('資金報酬合計：490',text)
