"""受け入れ済み候補の非表示・末尾表示、選択と旧保存の回帰。"""
import os
import unittest
from unittest.mock import patch
import test_cafe_pet_shop as fixtures


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class RecruitmentVisibilityTests(unittest.TestCase):
    setUp=fixtures.PetShopTests.setUp
    game=fixtures.PetShopTests.game
    reload=fixtures.PetShopTests.reload

    def window(self,s,pet_shop=False):
        import tkinter as tk
        from cat_cafe_sim.cafe_recruitment_gui import CafeRecruitmentWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        window=CafeRecruitmentWindow(root,s,lambda:None,pet_shop=pet_shop)
        return root,window

    def test_receive_hides_selection_and_toggle_shows_at_bottom(self):
        s=self.game();s.open_recruitment();keys=list(s.core.recruitment['candidates'])
        root,w=self.window(s);w.window.geometry('500x440');root.update()
        with patch('tkinter.messagebox.askyesno',return_value=True):w.receive_button.invoke()
        self.assertNotIn(keys[0],w.cats.get_children());self.assertEqual(w.cats.selection(),(keys[1],))
        before=s.core.snapshot();stored=s.store._read()
        w.show_accepted_button.invoke();root.update()
        self.assertEqual(w.cats.get_children(),tuple(keys[1:]+keys[:1]))
        self.assertEqual(w.cats.selection(),(keys[1],));self.assertEqual(w.cats.item(keys[0],'tags'),('accepted',))
        self.assertIn('済み',str(w.cats.item(keys[0],'values')))
        self.assertEqual(str(w.cats.tag_configure('accepted','foreground')),'#666666')
        w.cats.selection_set(keys[0]);w.selection_changed();self.assertTrue(w.receive_button.instate(['disabled']))
        self.assertIn('加入時の値',w.notice.get());w.show_accepted_button.invoke();root.update()
        self.assertEqual(w.cats.selection(),(keys[1],));self.assertEqual(s.core.snapshot(),before);self.assertEqual(s.store._read(),stored)
        self.assertTrue(w.show_accepted_button.winfo_ismapped())
        self.assertLessEqual(w.close_button.winfo_rooty()+w.close_button.winfo_height(),w.window.winfo_rooty()+w.window.winfo_height())

    def test_all_accepted_empty_list_details_and_reopen(self):
        s=self.game();s.purchase_housing();s.open_recruitment();keys=list(s.core.recruitment['candidates'])
        for key in keys:s.recruit_cat(key)
        root,w=self.window(s);self.assertEqual(w.cats.get_children(),())
        self.assertEqual(w.details.get_children(),());self.assertTrue(w.receive_button.instate(['disabled']))
        self.assertIn('候補はありません',w.notice.get());before=s.core.snapshot()
        w.show_accepted_button.invoke();self.assertEqual(w.cats.get_children(),tuple(keys));w.show_accepted_button.invoke()
        self.assertEqual(w.cats.get_children(),());self.assertEqual(w.details.get_children(),())
        self.assertEqual(s.core.snapshot(),before);w.window.destroy()
        s=self.reload(s);root,w=self.window(s);self.assertFalse(w.show_accepted.get());self.assertEqual(w.cats.get_children(),())

    def test_existing_save_preserves_candidates_dates_and_history(self):
        s=self.game();s.open_recruitment();keys=list(s.core.recruitment['candidates']);s.recruit_cat(keys[1]);s=self.reload(s)
        before=s.core.snapshot();root,w=self.window(s)
        self.assertEqual(w.cats.get_children(),(keys[0],keys[2]))
        w.show_accepted_button.invoke();self.assertEqual(w.cats.get_children(),(keys[0],keys[2],keys[1]))
        w.cats.selection_set(keys[1]);w.selection_changed();w.refresh();self.assertEqual(w.cats.selection(),(keys[1],))
        self.assertIn('1日目',str(w.cats.item(keys[1],'values')));self.assertEqual(s.core.snapshot(),before)

    def test_pet_shop_keeps_existing_display(self):
        s=self.game();key=next(iter(s.core.pet_shop['candidates']));s.purchase_cat(key)
        root,w=self.window(s,pet_shop=True)
        self.assertFalse(hasattr(w,'show_accepted_button'));self.assertEqual(w.cats.get_children()[0],key)
        self.assertFalse(w.cats.item(key,'tags'));self.assertTrue(w.receive_button.instate(['disabled']))
