import copy
import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import outcome_result,checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_reservation import CUSTOMER_ID,evaluate,rules,waiting
from cat_cafe_sim.core.cafe_weekdays import schedule
from cat_cafe_sim.storage.cafe_saves import save_game,load_game


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def game(self):
        selected=starting_conditions();selected.pop('intake_request')
        selected['goal'].update(target=105,stages=[dict(days=10,target=110),dict(days=10,target=115)])
        return create_game(Path(self.temp.name)/'games',selected)

    def unlock(self,s):
        while not s.core.closed:s.automatic_step()
        s.advance_goal();s.next_day()
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.goal['status'],'cleared')
        s.advance_goal();s.next_day()
        self.assertIsNotNone(waiting(s.core));return s

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def test_accept_arrives_next_day_blocks_day_off_and_rewards_success(self):
        s=self.unlock(self.game());request=waiting(s.core);funds=s.core.funds
        s.resolve_reservation('accept');self.assertEqual(s.core.funds,funds)
        self.assertNotIn(CUSTOMER_ID,schedule(s.core));self.assertIn(CUSTOMER_ID,schedule(s.core,s.core.day+1))
        while not s.core.closed:s.automatic_step()
        if s.core.goal['status']!='active':s.continue_goal()
        s.next_day()
        with self.assertRaises(ValueError):s.day_off()
        s.step();self.assertIn(CUSTOMER_ID,s.core.queue)
        s.start(CUSTOMER_ID,'cat-kohaku')
        while s.active_interactions:s.automatic_step()
        result=next(outcome_result(value) for value in s.core.outcomes.values() if outcome_result(value)['customer_id']==CUSTOMER_ID)
        rating=evaluate(s.core,result);self.assertTrue(rating['success'])
        self.assertEqual(s.core.reservation['request']['result'],'success')
        visit=s.core.visits[CUSTOMER_ID]
        self.assertGreaterEqual(visit.bill,rating['bonus'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_decline_has_no_cost_or_visit(self):
        s=self.unlock(self.game());before=(s.core.funds,s.core.management['popularity'])
        s.resolve_reservation('decline')
        self.assertEqual((s.core.funds,s.core.management['popularity']),before)
        self.assertNotIn(CUSTOMER_ID,schedule(s.core,s.core.day+1));self.assertIsNone(waiting(s.core))
        self.reload(s)

    def test_invalid_rules(self):
        base=rules()
        for change in (dict(feature='white'),dict(open_up_count=0),dict(arrival_tick=-1),dict(bonus=0),dict(popularity_bonus=float('inf'))):
            with self.assertRaises(ValueError):rules(dict(base,**change))

    def test_legacy_and_corrupt_request(self):
        selected=starting_conditions();selected.pop('intake_request');selected.pop('reservation')
        old=create_game(Path(self.temp.name)/'old',selected);self.assertIsNone(old.core.reservation)
        self.reload(old)
        s=self.unlock(self.game());s.resolve_reservation('accept');source=checkpoint(s.core,set())
        bad=copy.deepcopy(source);bad['state']['reservation']['request']['visit_day']+=1
        bad['digest']=digest({key:value for key,value in bad.items() if key!='digest'})
        with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
