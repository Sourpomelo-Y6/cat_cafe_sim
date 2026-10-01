"""人気第2段階の解放、確率来店、長毛触れ合いと保存互換。"""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_longhair_customer import CUSTOMER_ID,rules,schedule,unlocked_day,evaluate,draw
from cat_cafe_sim.core.cafe_checkpoint import outcome_result,checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game,load_game
from cat_cafe_sim.cafe_customers import directory


class LonghairCustomerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.sequence=0

    def game(self,probability=1,legacy=False,mode='popularity',seats=2):
        self.sequence+=1;s=starting_conditions(mode)
        for key in ('store_events','intake_request','regular_introduction','visiting_cat','reservation'):s.pop(key)
        s['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=10,target=200)])
        s['longhair_customer']['probability']=probability;s['seat_count']=seats
        if legacy:s.pop('longhair_customer')
        return create_game(Path(self.temp.name)/str(self.sequence),s)

    def close(self,s):
        while not s.core.closed:s.automatic_step()

    def unlock(self,s):
        self.assertIsNone(unlocked_day(s.core));self.close(s);self.assertEqual(s.core.goal['status'],'cleared')
        self.assertIsNone(unlocked_day(s.core));self.assertEqual(schedule(s.core,s.core.day+1),{})
        s.advance_goal();s.next_day();self.close(s);self.assertEqual(s.core.goal['status'],'cleared')
        day=s.core.day;self.assertEqual(unlocked_day(s.core),day if s.core.longhair_customer is not None else None);self.assertEqual(schedule(s.core,day),{})
        s.advance_goal();s.next_day();return s

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(s.core.snapshot(),loaded.core.snapshot())
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        return loaded

    def prepare(self,cat_id='cat-sora',seats=2):
        s=self.unlock(self.game(seats=seats));s.step();s.start(CUSTOMER_ID,cat_id,'seat-1');return s

    def contact(self,s,count):
        s.step('switch','brush')
        for _ in range(count):s.step('direct')
        s.finish();return outcome_result(list(s.core.outcomes.values())[-1])

    def test_second_stage_only_and_deterministic_probability(self):
        s=self.unlock(self.game(probability=.3));before=s.core.snapshot()
        values=[bool(schedule(s.core,d)) for d in range(s.core.day,s.core.day+100)]
        self.assertIn(True,values);self.assertIn(False,values)
        self.assertEqual(values,[draw(s.core.seed,d)<.3 for d in range(s.core.day,s.core.day+100)])
        directory(s);self.assertEqual(s.core.snapshot(),before);s=self.reload(s)
        self.assertEqual(values,[bool(schedule(s.core,d)) for d in range(s.core.day,s.core.day+100)])
        self.assertEqual(s.core.longhair_customer['probability'],.3)

    def test_match_contact_count_and_no_equipment_required(self):
        for seats in (1,2):
            s=self.prepare(seats=seats);value=self.contact(s,3);row=evaluate(s.core,value)
            self.assertTrue(row['success']);self.assertEqual(row['bonus'],120)
            self.assertTrue(row['matched']);self.assertEqual(row['contact_count'],3)
            self.assertGreaterEqual(s.core.visits[CUSTOMER_ID].bill,120)
            self.assertTrue(any(e['kind']=='longhair_customer_result' for e in s.core.events))
            self.reload(s)
        for cat_id,count in (('cat-mike',3),('cat-sora',2)):
            s=self.prepare(cat_id);value=self.contact(s,count)
            self.assertFalse(evaluate(s.core,value)['success']);self.assertEqual(evaluate(s.core,value)['bonus'],0)
            self.reload(s)

    def test_automatic_contact_rewards_and_popularity(self):
        s=self.unlock(self.game());before=s.core.management['popularity'];s.step();s.start(CUSTOMER_ID,'cat-sora','seat-1');self.close(s)
        values=[outcome_result(v) for v in s.core.outcomes.values() if outcome_result(v)['customer_id']==CUSTOMER_ID]
        self.assertEqual(len(values),1);self.assertTrue(evaluate(s.core,values[0])['success'])
        self.assertEqual(s.core.customer_preferences['customers'][CUSTOMER_ID],'long_hair')
        self.assertGreaterEqual(s.core.management['popularity'],before+2);self.reload(s)

    def test_day_off_has_no_visit_and_other_modes_or_old_saves_unchanged(self):
        s=self.unlock(self.game());s.day_off();self.assertNotIn(CUSTOMER_ID,s.core.day_results[-1]['customer_visits']);self.reload(s)
        old=self.unlock(self.game(legacy=True));self.assertEqual(schedule(old.core,old.core.day),{})
        self.assertNotIn('longhair_customer',old.core.snapshot());self.reload(old)
        for mode in ('free','bond','patron'):
            s=self.game(mode=mode);self.assertIsNone(s.core.longhair_customer);self.reload(s)

    def test_pending_interaction_save_resume_and_fixed_config(self):
        s=self.prepare();s.step('switch','brush');s.step('direct');s=self.reload(s)
        with patch('cat_cafe_sim.core.cafe_longhair_customer.rules',side_effect=lambda data:copy.deepcopy(data)):
            s.step('direct');s.step('direct');s.finish();s=self.reload(s)
        value=outcome_result(list(s.core.outcomes.values())[-1]);self.assertTrue(evaluate(s.core,value)['success'])
        before=s.core.snapshot()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        s=self.reload(s);self.assertEqual(s.core.snapshot(),before)

    def test_invalid_config_and_corrupted_reward_rejected(self):
        for field,value in (('probability',True),('probability',0),('probability',1.1),('probability',float('nan')),('contact_count',True),('bonus',-1)):
            with self.assertRaises(ValueError):rules(dict(rules(),**{field:value}))
        s=self.prepare();self.contact(s,3);source=checkpoint(s.core,set())
        bad=copy.deepcopy(source);bad['state']['longhair_customer']['bonus']=999
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class LonghairCustomerWindowTests(unittest.TestCase):
    setUp=LonghairCustomerTests.setUp
    game=LonghairCustomerTests.game
    close=LonghairCustomerTests.close
    unlock=LonghairCustomerTests.unlock

    def test_directory_unlock_probability_and_result(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        from cat_cafe_sim.cafe_customers_gui import CafeCustomersWindow
        root=tk.Tk();self.addCleanup(root.destroy);s=self.game();app=CafeInteractionWindow(root,s)
        row=next(r for r in directory(s) if r['customer_id']==CUSTOMER_ID)
        self.assertIn('人気第2段階',row['status']);self.unlock(s);app.refresh();self.close(s);app.refresh()
        self.assertTrue(any('長毛好き客' in str(app.history.item(k)['values']) for k in app.history.get_children()))
        w=CafeCustomersWindow(root,s);root.update()
        self.assertIn(CUSTOMER_ID,w.customers.get_children())
