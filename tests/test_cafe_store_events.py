import copy
import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_items import inventory
from cat_cafe_sim.core.cafe_store_events import LABELS,modify_schedule,row,rules
from cat_cafe_sim.core.cafe_weekdays import schedule
from cat_cafe_sim.storage.cafe_saves import load_game,save_game


class StoreEventTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def game(self,legacy=False):
        selected=starting_conditions('free');selected.pop('intake_request')
        if legacy:selected.pop('store_events')
        else:selected['store_events']=dict(rules(),probability=1)
        return create_game(Path(self.temp.name)/('old' if legacy else 'games'),selected)

    def reload(self,s):
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot());return loaded

    def test_deterministic_days_rain_trouble_supplies_save_and_replay(self):
        s=self.game();self.assertEqual(row(s.core)['type'],'rain')
        self.assertNotIn('guest-6',schedule(s.core));s.day_off()
        self.assertEqual(row(s.core)['type'],'trouble');s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'],110)
        self.assertEqual(s.core.day_results[-1]['summary']['store_event'],LABELS['trouble'])
        s.day_off();self.assertEqual(row(s.core)['type'],'supplies')
        self.assertIn('store-event-4',inventory(s.core))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot());self.reload(s)

    def test_festival_adds_saved_extra_customer(self):
        s=self.game();s.core.store_events['days'][0]['type']='festival'
        planned=modify_schedule(s.core,{'guest-1':0},1)
        self.assertEqual(planned['event-guest-1'],3)

    def test_legacy_invalid_and_corrupt_draw(self):
        old=self.game(True);self.assertIsNone(old.core.store_events);old.day_off();self.reload(old)
        base=rules()
        for changed in (dict(probability=-1),dict(festival_customer_tick=-1),dict(trouble_cost=0),
                        dict(supply=dict(base['supply'],stress_relief=0))):
            with self.assertRaises(ValueError):rules(dict(base,**changed))
        s=self.game();s.day_off();source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['store_events']['days'][0].update(draw=0.5),
                       lambda d:d['state']['store_events']['days'].pop(),
                       lambda d:d['state']['store_events']['days'][1].update(type='festival')):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
