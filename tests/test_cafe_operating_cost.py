import copy
import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_operating_cost import charged,estimate,rules
from cat_cafe_sim.storage.cafe_saves import load_game,save_game


class OperatingCostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def game(self,legacy=False,management=None):
        selected=starting_conditions('free');selected.pop('intake_request')
        if legacy:selected.pop('operating_cost')
        if management is not None:selected['management']=management
        return create_game(Path(self.temp.name)/('old' if legacy else 'games'),selected)

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def test_business_day_and_day_off_charge_once_save_and_replay(self):
        s=self.game();self.assertEqual(estimate(s.core),60);before=s.core.funds
        while not s.core.closed:s.automatic_step()
        revenue=s.core.summary()['revenue']
        self.assertEqual(s.core.funds,before+revenue-60)
        self.assertEqual(s.core.summary()['operating_cost'],60)
        self.assertEqual(charged(s.core),60)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s=self.reload(s);s.next_day();before=s.core.funds;s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'],60)
        self.assertEqual(s.core.funds,before-60);self.assertEqual(charged(s.core),120)
        self.reload(s)

    def test_seat_count_changes_cost_and_funds_game_over(self):
        s=self.game();s.expand_seats();self.assertEqual(estimate(s.core),70)
        s.day_off();self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'],70)
        management=starting_conditions('free')['management'];management['starting_funds']=60
        poor=self.game(management=management);poor.day_off()
        self.assertEqual(poor.core.funds,0)
        self.assertEqual(poor.core.management['game_over'],dict(reason='funds',day=1))
        self.assertEqual(poor.core.day,1);self.reload(poor)

    def test_legacy_invalid_rules_and_corrupt_charge(self):
        old=self.game(legacy=True);old.day_off();self.assertIsNone(old.core.operating_cost)
        self.assertNotIn('operating_cost',old.core.day_results[-1]['summary']);self.reload(old)
        base=rules()
        for changed in (dict(base_cost=-1),dict(per_seat_cost=float('inf')),
                        dict(base_cost=0,per_seat_cost=0),dict(base_cost=True)):
            with self.assertRaises(ValueError):rules(dict(base,**changed))
        s=self.game();s.day_off();source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['operating_cost']['charges'][0].update(total=1),
                       lambda d:d['state']['operating_cost']['charges'].clear(),
                       lambda d:d['state'].pop('management')):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
