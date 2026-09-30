import copy
import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_expansion import FIFTH_CUSTOMER_ID,extra_schedule,five_seat_purchase,reason,rules
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game,save_game


class FiveSeatExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        selected=starting_conditions();selected.pop('intake_request')
        selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=10,target=115)])
        self.session=create_game(Path(self.temp.name)/'games',selected)

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def rejected(self,s,action):
        before=s.core.log()
        with self.assertRaises(ValueError):action()
        self.assertEqual(before,s.core.log())

    def unlock_and_buy(self):
        s=self.session;s.expand_seats()
        while not s.core.closed:s.automatic_step()
        s.advance_goal();s.next_day();s.expand_seats()
        self.rejected(s,s.expand_seats)
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.goal['status'],'cleared')
        self.rejected(s,s.expand_seats)
        s.advance_goal();s.next_day();s.resolve_reservation('decline')
        before=s.core.funds;s.expand_seats();self.assertEqual(s.core.funds,before-1000)
        return s

    def test_unlock_purchase_next_day_customer_save_replay_and_day_off(self):
        s=self.unlock_and_buy();self.assertEqual(len(s.core.seats),5)
        self.assertEqual(s.core.summary()['seat_count'],5)
        self.assertEqual(s.core.summary()['expansion_expenses'],1000)
        self.assertNotIn(FIFTH_CUSTOMER_ID,extra_schedule(s.core,s.core.day))
        self.assertIn(FIFTH_CUSTOMER_ID,extra_schedule(s.core,s.core.day+1))
        row=next(row for row in directory(s) if row['customer_id']==FIFTH_CUSTOMER_ID)
        self.assertIsNone(row['arrival_tick']);self.assertEqual(row['tomorrow_tick'],6)
        s=self.reload(s);self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.day_off();self.assertEqual(s.core.day_results[-1]['customer_visits'],[])
        if s.core.goal['status']!='active':s.continue_goal()
        s.step();self.assertNotIn(FIFTH_CUSTOMER_ID,s.core.visits)
        while s.core.tick<=6:s.step()
        self.assertIn(FIFTH_CUSTOMER_ID,s.core.visits);self.reload(s)

    def test_fifth_seat_is_available_immediately_and_sixth_requires_final_stage(self):
        s=self.unlock_and_buy()
        self.assertIn('seat-5',s.free_seats);self.assertIsNotNone(five_seat_purchase(s.core))
        self.rejected(s,s.expand_seats)
        self.assertIn('最終段階',reason(s.core,rules()))
        old=rules();old.pop('six_seat_cost');old.pop('seven_seat_cost')
        self.assertIn('現在追加できる席はありません',reason(s.core,old))

    def test_corrupt_record_and_old_rules(self):
        self.assertNotIn('five_seat_cost',rules(dict(cost=500,four_seat_cost=1000)))
        s=self.unlock_and_buy();source=checkpoint(s.core,set())
        for mutate in (
            lambda d:d['state']['expansion']['purchases'][2].update(seats=6),
            lambda d:d['state']['expansion']['purchases'][2].update(day=0),
            lambda d:d.update(seat_count=4),lambda d:d['state']['seats'].pop('seat-5'),
            lambda d:d['state']['goal']['history'].pop(),
        ):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
