"""働き者の疲労・ストレスと、追加紹介枠・保存互換の回帰。"""
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
from cat_cafe_sim.core.cafe_recruitment import candidates, catalog
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction


class HardworkingTraitTests(unittest.TestCase):
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
        original=copy.deepcopy(s.core.recruitment['candidates']);initial=copy.deepcopy(s.core.traits)
        for _ in range(4):
            for _ in range(3):s.day_off()
            s.open_recruitment()
        self.assertEqual(s.core.day,13)
        self.assertEqual({key:s.core.recruitment['candidates'][key] for key in original},original)
        self.assertEqual(s.core.traits,initial)
        key=next(key for key,row in s.core.recruitment['candidates'].items() if row.get('trait',{}).get('id')=='hardworking')
        return s,key

    def test_catalog_new_batch_and_original_assignments(self):
        rows=catalog();self.assertEqual(len(rows),15)
        self.assertEqual([r['name'] for r in rows[-3:]],['ナギ','ミント','レオ'])
        self.assertEqual([r['trait']['id'] for r in rows[-3:]],['hardworking','relaxed','hospitality'])
        self.assertEqual([r['trait']['id'] for r in rows[:3]],['hospitality','outgoing','relaxed'])
        self.assertEqual([r['name'] for r in rows if r['trait']['id']=='hardy'],['ソラ','フク'])
        self.assertEqual(rows[-3]['features'],['black','short_hair']);self.assertEqual(rows[-3]['cost'],200)
        self.assertEqual(dict(description(definitions()['hardworking'])),{'特性':'働き者','接客ストレス':'通常の1.25倍','接客疲労':'通常の0.75倍'})

    def test_fractional_effects_rest_forecast_equipment_and_replay(self):
        s=self.session({'a':'hardworking'});self.close(s)
        self.assertEqual(s.core.cats['a'].fatigue,.75);self.assertEqual(s.core.cats['b'].fatigue,1)
        self.assertEqual(s.core.management['stress']['a'],1.25)
        s=self.reload(s);self.replay(s)
        s=self.session({'a':'hardworking'},fatigue=32);self.close(s);s.next_day()
        before=s.core.snapshot();forecast=shift_forecast(s.core,'a')
        self.assertEqual(forecast['work']['fatigue'],48);self.assertEqual(forecast['rest']['fatigue'],4)
        self.assertEqual(s.core.snapshot(),before)
        s.day_off();self.assertEqual(s.core.cats['a'].fatigue,4);self.assertEqual(s.core.cats['b'].fatigue,12)
        self.reload(s);self.replay(s)
        s=self.session({'a':'hardworking'},fatigue=32);s.purchase_rest_space();self.close(s);s.next_day()
        self.assertEqual(shift_forecast(s.core,'a')['rest']['fatigue'],0)
        s.day_off();self.assertEqual(s.core.cats['a'].fatigue,0);self.replay(s)

    def test_dispatch_no_bonus_or_return_stress_and_no_absent_rest(self):
        s=self.session({'a':'hardworking'},fatigue=32);self.close(s);s.next_day();s.dispatch('a');s.day_off()
        self.assertEqual(s.core.cats['a'].fatigue,24)
        funds=s.core.funds;stress=s.core.management['stress']['a'];s.resolve_activity('dispatch-2-a')
        self.assertEqual(s.core.funds,funds+100);self.assertEqual(s.core.management['stress']['a'],stress)
        self.reload(s);self.replay(s)

    def test_new_candidate_join_saved_effects_retry_and_replay(self):
        s,key=self.candidate_game();row=copy.deepcopy(s.core.recruitment['candidates'][key]);funds=s.core.funds
        s=self.reload(s)
        with patch.object(s.store,'_write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):s.recruit_cat(key)
        self.assertNotIn(key,s.core.cats);self.assertEqual(s.core.funds,funds)
        with patch('cat_cafe_sim.core.cafe_traits.definitions',side_effect=AssertionError('settings changed')):
            s.recruit_cat(key);self.assertEqual(trait(s.core,key),row['trait'])
            self.assertEqual(dict(cat_details(s,key)['basic'])['特性'],'働き者');self.assertEqual(s.core.funds,funds-200)
            with self.assertRaises(ValueError):s.recruit_cat(key)
            self.reload(s);self.replay(s)

    def test_old_four_batch_save_keeps_presented_cats_and_adds_new_batch(self):
        s=self.session();rows=catalog()[:12]
        with patch('cat_cafe_sim.core.cafe_recruitment.catalog',return_value=rows):
            s.open_recruitment()
            for _ in range(3):
                for _ in range(3):s.day_off()
                s.open_recruitment()
        old=copy.deepcopy(s.core.recruitment['candidates']);s=self.reload(s)
        for _ in range(3):s.day_off()
        s.open_recruitment()
        self.assertEqual({k:s.core.recruitment['candidates'][k] for k in old},old)
        self.assertIsNone(s.core.traits)
        key=next(k for k,r in s.core.recruitment['candidates'].items() if r.get('trait',{}).get('id')=='hardworking')
        s.recruit_cat(key);self.assertIsNone(trait(s.core,'a'));self.assertEqual(trait(s.core,key)['id'],'hardworking')
        self.reload(s);self.replay(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class HardworkingTraitWindowTests(unittest.TestCase):
    setUp=fixtures.TraitTests.setUp
    candidate_game=HardworkingTraitTests.candidate_game

    def test_filter_candidate_effects_confirmation_and_join(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_recruitment_gui import CafeRecruitmentWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s,key=self.candidate_game();w=CafeRecruitmentWindow(root,s,lambda:None)
        w.window.geometry('500x440');w.filters['trait'].set('働き者');w.refresh();root.update()
        self.assertEqual(w.cats.get_children(),(key,));self.assertEqual(w.cats.selection(),(key,))
        values=dict(tuple(w.details.item(k)['values']) for k in w.details.get_children())
        self.assertEqual(values['接客疲労'],'通常の0.75倍');self.assertEqual(values['接客ストレス'],'通常の1.25倍')
        with patch('tkinter.messagebox.askyesno',return_value=False):w.receive_button.invoke()
        self.assertNotIn(key,s.core.cats)
        with patch('tkinter.messagebox.askyesno',return_value=True):w.receive_button.invoke()
        self.assertEqual(dict(cat_details(s,key)['basic'])['特性'],'働き者');self.assertEqual(w.cats.get_children(),())
        w.show_accepted_button.invoke();self.assertEqual(w.cats.get_children(),(key,))
        self.assertLessEqual(w.close_button.winfo_rooty()+w.close_button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())
