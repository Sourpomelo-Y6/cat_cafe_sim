import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore,verify_cafe_interaction
from cat_cafe_sim.core.cafe_waiting_area import max_wait_ticks,queue_capacity,reason,rules
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.storage.cafe_saves import load_game,save_game


class WaitingAreaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def game(self,legacy=False):
        selected=starting_conditions();selected.pop('intake_request');selected['goal']['target']=105
        if legacy:selected.pop('waiting_area')
        return create_game(Path(self.temp.name)/('old' if legacy else 'games'),selected)

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def unlock(self,s):
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.goal['status'],'cleared');s.continue_goal();s.next_day();return s

    def test_unlock_purchase_cost_daily_cost_save_and_replay(self):
        s=self.game();self.assertIn('第1段階',reason(s.core));s=self.unlock(s)
        before=s.core.funds;s.purchase_waiting_area();self.assertEqual(s.core.funds,before-800)
        self.assertEqual(queue_capacity(s.core),s.core.config.queue_capacity+1)
        self.assertEqual(max_wait_ticks(s.core),s.core.config.max_wait_ticks+2)
        self.assertIn('強化済み',reason(s.core));self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s.day_off();summary=s.core.day_results[-1]['summary']
        self.assertEqual(summary['waiting_area_expenses'],800)
        self.assertEqual(summary['operating_cost'],70)
        self.assertEqual(summary['total_expenses'],870)
        self.reload(s)

    def test_capacity_and_wait_deadline_change_arrival_behavior(self):
        config=replace(Config.load(),opening_ticks=5,arrival_ticks=(0,0),queue_capacity=1,max_wait_ticks=2)
        base=CafeInteractionCore(config,compact=True);base.step()
        self.assertEqual(base.visits['guest-2'].departure_reason,'queue_full')
        upgraded=CafeInteractionCore(config,compact=True);upgraded.waiting_area=dict(rules=rules(),purchase=dict(day=1,cost=800))
        upgraded.step();self.assertEqual(upgraded.queue,['guest-1','guest-2'])
        upgraded.step();self.assertTrue(all(v.departure_reason is None for v in upgraded.visits.values()))
        upgraded.step();upgraded.step()
        self.assertTrue(all(v.departure_reason=='wait_timeout' for v in upgraded.visits.values()))

    def test_legacy_invalid_and_corrupt_data(self):
        old=self.game(True);self.assertIsNone(old.core.waiting_area);self.reload(old)
        base=rules()
        for changed in (dict(cost=0),dict(queue_bonus=0),dict(wait_bonus=True),dict(daily_cost=float('inf'))):
            with self.assertRaises(ValueError):rules(dict(base,**changed))
        s=self.unlock(self.game());s.purchase_waiting_area();s.day_off();source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['waiting_area']['purchase'].update(cost=1),
                       lambda d:d['state']['waiting_area']['purchase'].update(day=0),
                       lambda d:d['state']['day_results'][-1]['summary'].update(waiting_area_expenses=1)):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
