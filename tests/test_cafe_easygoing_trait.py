"""マイペースの管理効果と６回目の紹介・旧候補の固定。"""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import test_cafe_traits as fixtures
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_shift_forecast import shift_forecast
from cat_cafe_sim.core.cafe_traits import definitions, trait, description
from cat_cafe_sim.core.cafe_recruitment import catalog, candidates
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore


class EasygoingTraitTests(unittest.TestCase):
    setUp=fixtures.TraitTests.setUp
    session=fixtures.TraitTests.session
    close=fixtures.TraitTests.close
    reload=fixtures.TraitTests.reload

    def replay(self,s):
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def candidate_game(self):
        selected=starting_conditions('free')
        for key in ('intake_request','regular_introduction','store_events','growth'):selected.pop(key)
        selected['management']['starting_funds']=10000
        s=create_game(Path(self.temp.name)/'games',selected);s.open_recruitment()
        initial=copy.deepcopy(s.core.traits);original=copy.deepcopy(s.core.recruitment['candidates'])
        for _ in range(5):
            for _ in range(3):s.day_off()
            s.open_recruitment()
        self.assertEqual(s.core.day,16);self.assertEqual(s.core.traits,initial)
        self.assertEqual({k:s.core.recruitment['candidates'][k] for k in original},original)
        key=next(k for k,r in s.core.recruitment['candidates'].items() if r.get('trait',{}).get('id')=='easygoing')
        return s,key

    def test_catalog_sixth_batch_rotation_and_description(self):
        rows=catalog();self.assertEqual(len(rows),18)
        self.assertEqual([r['name'] for r in rows[15:]],['シオン','ルナ','チャイ'])
        self.assertEqual([r['trait']['id'] for r in rows[15:]],['easygoing','outgoing','hardworking'])
        self.assertEqual([r['name'] for r in candidates(set(),5).values()],['シオン（紹介6）','ルナ（紹介6）','チャイ（紹介6）'])
        self.assertEqual([r['name'] for r in candidates(set(),6).values()],['ハル（紹介7）','リン（紹介7）','ユキ（紹介7）'])
        self.assertEqual(dict(description(definitions()['easygoing'])),{'特性':'マイペース','接客ストレス':'通常の0.75倍','休養時の疲労回復':'通常の0.75倍'})

    def test_fractional_stress_fatigue_forecast_and_day_off(self):
        s=self.session({'a':'easygoing'});self.close(s)
        self.assertEqual(s.core.management['stress']['a'],.75);self.assertEqual(s.core.cats['a'].fatigue,1)
        s=self.reload(s);s.next_day();before=s.core.snapshot();forecast=shift_forecast(s.core,'a')
        self.assertEqual(forecast['work_stress'],1.5);self.assertEqual(forecast['work']['fatigue'],2)
        self.assertEqual(forecast['rest_stress'],0);self.assertEqual(s.core.snapshot(),before)
        self.replay(s)
        s=self.session({'a':'easygoing'},fatigue=32);self.close(s);s.next_day()
        self.assertEqual(shift_forecast(s.core,'a')['rest']['fatigue'],17)
        s.day_off();self.assertEqual(s.core.cats['a'].fatigue,17);self.assertEqual(s.core.cats['b'].fatigue,12)
        s=self.reload(s);self.replay(s);s.day_off();s.day_off();self.assertEqual(s.core.cats['a'].fatigue,0)
        self.reload(s);self.replay(s)

    def test_equipment_fixed_bonus_business_rest_and_therapy(self):
        s=self.session({'a':'easygoing'},fatigue=32);s.purchase_rest_space();self.close(s);s.next_day()
        self.assertEqual(shift_forecast(s.core,'a')['rest']['fatigue'],7)
        s.set_shifts(['b','c']);self.close(s);self.assertEqual(s.core.cats['a'].fatigue,7)
        self.reload(s);self.replay(s)
        s=self.session({'a':'easygoing'},fatigue=32);self.close(s);s.next_day()
        s.core.cats['a'].health_status='sick';s.core.cats['a'].recovery_days_remaining=2;s.core.initial_health['a']=dict(status='sick',remaining=2)
        forecast=shift_forecast(s.core,'a');self.assertIsNone(forecast['work']);self.assertEqual(forecast['recovery_after'],1)
        s.core.day_off();self.assertEqual(s.core.cats['a'].fatigue,17);self.assertEqual(s.core.cats['a'].recovery_days_remaining,1)

    def test_dispatch_no_rest_bonus_reward_unchanged_and_no_management(self):
        for management in (True,False):
            s=self.session({'a':'easygoing'},fatigue=32,management=management);self.close(s);s.next_day()
            s.dispatch('a');s.day_off();self.assertEqual(s.core.cats['a'].fatigue,32)
            stress=copy.deepcopy(s.core.management);funds=s.core.funds;s.resolve_activity('dispatch-2-a')
            self.assertEqual(s.core.funds,funds+100);self.assertEqual(s.core.management,stress)
            self.reload(s);self.replay(s)

    def test_candidate_join_saved_rules_failed_write_retry_and_invalid_trait(self):
        s,key=self.candidate_game();row=copy.deepcopy(s.core.recruitment['candidates'][key]);funds=s.core.funds
        s=self.reload(s)
        with patch.object(s.store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.recruit_cat(key)
        self.assertNotIn(key,s.core.cats);self.assertEqual(s.core.funds,funds)
        with patch('cat_cafe_sim.core.cafe_traits.definitions',side_effect=AssertionError('changed')):
            s.recruit_cat(key);self.assertEqual(trait(s.core,key),row['trait'])
            self.assertEqual(dict(cat_details(s,key)['basic'])['特性'],'マイペース')
            self.assertEqual(s.core.funds,funds-200)
            with self.assertRaises(ValueError):s.recruit_cat(key)
            self.reload(s);self.replay(s)
        source=checkpoint(s.core,set());bad=copy.deepcopy(source)
        bad['state']['traits'][key]['service_stress']=1
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)

    def test_old_five_batch_save_keeps_repeated_candidates_and_initial_traits(self):
        s=self.session();old_rows=catalog()[:15]
        with patch('cat_cafe_sim.core.cafe_recruitment.catalog',return_value=old_rows):
            s.open_recruitment()
            for _ in range(5):
                for _ in range(3):s.day_off()
                s.open_recruitment()
        original=copy.deepcopy(s.core.recruitment['candidates']);self.assertFalse(any(r.get('trait',{}).get('id')=='easygoing' for r in original.values()))
        s=self.reload(s);s.open_recruitment();self.assertEqual(s.core.recruitment['candidates'],original)
        self.assertIsNone(s.core.traits)
        # 旧巡回で既に６回目を提示済みなら、再生成せず次の巡回の６回目まで待つ。
        for _ in range(6):
            for _ in range(3):s.day_off()
            s.open_recruitment()
        self.assertEqual({k:s.core.recruitment['candidates'][k] for k in original},original)
        key=next(k for k,r in s.core.recruitment['candidates'].items() if r.get('trait',{}).get('id')=='easygoing')
        s.recruit_cat(key);self.assertIsNone(trait(s.core,'a'));self.assertEqual(trait(s.core,key)['id'],'easygoing')
        self.reload(s);self.replay(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires display')
class EasygoingTraitGuiTests(unittest.TestCase):
    setUp=fixtures.TraitTests.setUp
    candidate_game=EasygoingTraitTests.candidate_game

    def test_filters_effects_confirmation_join_and_history(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_recruitment_gui import CafeRecruitmentWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s,key=self.candidate_game();w=CafeRecruitmentWindow(root,s,lambda:None)
        w.window.geometry('500x440');w.filters['trait'].set('マイペース');w.refresh();root.update()
        self.assertEqual(w.cats.get_children(),(key,));self.assertEqual(w.cats.selection(),(key,))
        values=dict(tuple(w.details.item(k)['values']) for k in w.details.get_children())
        self.assertEqual(values['接客ストレス'],'通常の0.75倍');self.assertEqual(values['休養時の疲労回復'],'通常の0.75倍')
        with patch('tkinter.messagebox.askyesno',return_value=False):w.receive_button.invoke()
        self.assertNotIn(key,s.core.cats)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.receive_button.invoke()
        self.assertEqual(dict(cat_details(s,key)['basic'])['特性'],'マイペース');self.assertEqual(w.cats.get_children(),())
        w.show_accepted_button.invoke();self.assertEqual(w.cats.get_children(),(key,))
        self.assertLessEqual(w.close_button.winfo_rooty()+w.close_button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
