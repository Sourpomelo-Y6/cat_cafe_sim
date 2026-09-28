import copy
import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,outcome_result,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_vip_customer import CUSTOMER_ID,evaluate,rules,unlocked_day
from cat_cafe_sim.core.cafe_weekdays import schedule
from cat_cafe_sim.storage.cafe_saves import load_game,save_game


class VipCustomerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def game(self,legacy=False):
        selected=starting_conditions();selected.pop('intake_request')
        selected['goal'].update(target=105,cap=100000,stages=[dict(days=10,target=110),dict(days=10,target=115)])
        if legacy:selected.pop('vip_customer')
        return create_game(Path(self.temp.name)/('old' if legacy else 'games'),selected)

    def complete_stage(self,s):
        while not s.core.closed:s.automatic_step()

    def unlock(self,s):
        self.complete_stage(s);s.advance_goal();s.next_day()
        self.complete_stage(s);s.advance_goal();s.next_day()
        s.resolve_reservation('decline')
        self.complete_stage(s)
        self.assertEqual(s.core.goal['status'],'cleared')
        self.assertEqual(unlocked_day(s.core),s.core.day)
        return s

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def test_final_stage_unlock_tomorrow_directory_save_and_replay(self):
        s=self.game();row=next(row for row in directory(s) if row['customer_id']==CUSTOMER_ID)
        self.assertIn('未解放',row['status']);self.assertEqual(row['preference'],'calico')
        s=self.unlock(s);self.assertNotIn(CUSTOMER_ID,schedule(s.core))
        self.assertIn(CUSTOMER_ID,schedule(s.core,s.core.day+1))
        event=next(event for event in s.core.events if event['kind']=='vip_customer_unlocked')
        self.assertEqual(event['first_day'],s.core.day+1)
        s.continue_goal();s.next_day();s=self.reload(s)
        self.assertIn(CUSTOMER_ID,schedule(s.core))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_composite_success_adds_fee_and_popularity(self):
        s=self.unlock(self.game());s.continue_goal();s.next_day();s.step()
        s.start(CUSTOMER_ID,'cat-mike')
        while s.active_interactions:s.automatic_step()
        result=next(outcome_result(value) for value in s.core.outcomes.values()
                    if outcome_result(value)['customer_id']==CUSTOMER_ID)
        value=evaluate(s.core,result)
        self.assertTrue(value['matched'])
        self.assertGreaterEqual(result['connect_count'],1)
        self.assertGreaterEqual(result['open_up_count'],1)
        self.assertGreaterEqual(result['simultaneous_count'],1)
        self.assertTrue(value['success']);self.assertGreaterEqual(s.core.visits[CUSTOMER_ID].bill,400)
        while not s.core.closed:s.automatic_step()
        self.assertGreaterEqual(s.core.goal['days'][-1]['gain'],10)
        self.reload(s)

    def test_wrong_cat_fails_and_legacy_and_invalid_data(self):
        s=self.unlock(self.game());s.continue_goal();s.next_day();s.step();s.start(CUSTOMER_ID,'cat-sora');s.finish()
        result=next(outcome_result(value) for value in s.core.outcomes.values()
                    if outcome_result(value)['customer_id']==CUSTOMER_ID)
        self.assertFalse(evaluate(s.core,result)['success'])
        old=self.game(legacy=True);self.assertIsNone(old.core.vip_customer);self.reload(old)
        base=rules()
        for changed in (dict(feature='white'),dict(connect_count=0),dict(open_up_count=True),
                        dict(simultaneous_count=0),dict(bonus=0),dict(popularity_bonus=float('inf'))):
            with self.assertRaises(ValueError):rules(dict(base,**changed))
        source=checkpoint(s.core,set());bad=copy.deepcopy(source);bad['state']['vip_customer']['feature']='white'
        bad['digest']=digest({key:value for key,value in bad.items() if key!='digest'})
        with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
