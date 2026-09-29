import copy
import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_items import inventory
from cat_cafe_sim.core.cafe_store_events import SUPPORT_FIELDS,disabled_seats,modify_schedule,row,rules,waiting
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

    def reach_trouble(self,s):
        s.day_off();s.resolve_store_event('decline');s.day_off();s.day_off()
        self.assertEqual(row(s.core)['type'],'trouble');return s

    def test_deterministic_days_rain_support_supplies_and_trouble(self):
        s=self.game();self.assertEqual(row(s.core)['type'],'rain')
        self.assertNotIn('guest-6',schedule(s.core));s.day_off()
        self.assertEqual(row(s.core)['type'],'support');self.assertIsNotNone(waiting(s.core))
        before=s.core.management['popularity'];s.resolve_store_event('full');s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['store_event_expenses'],100)
        self.assertEqual(s.core.day_results[-1]['summary']['net_cash_flow'],-160)
        self.assertEqual(s.core.management['popularity'],before+5)
        self.assertEqual(s.core.day_results[-1]['summary']['store_event'],'保護団体からの支援依頼（支援）')
        self.assertEqual(row(s.core)['type'],'supplies')
        self.assertIn('store-event-3',inventory(s.core));s.day_off()
        self.assertEqual(row(s.core)['type'],'trouble');s.resolve_store_event('repair');s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'],110)
        self.assertEqual(s.core.day_results[-1]['summary']['store_event'],'設備トラブル（修理）')
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot());self.reload(s)

    def test_festival_adds_saved_extra_customer(self):
        s=self.game();s.core.store_events['days'][0]['type']='festival'
        planned=modify_schedule(s.core,{'guest-1':0},1)
        self.assertEqual(planned['event-guest-1'],3)

    def test_trouble_patch_disables_last_seat_and_close_advances_day(self):
        s=self.reach_trouble(self.game());self.assertIsNotNone(waiting(s.core))
        with self.assertRaisesRegex(ValueError,'店舗イベント'):s.automatic_step()
        s.resolve_store_event('patch')
        self.assertEqual(disabled_seats(s.core),{'seat-2'})
        self.assertEqual(s.free_seats,['seat-1'])
        self.assertEqual(self.reload(s).free_seats,['seat-1'])

        closed=self.reach_trouble(self.game());self.assertIsNotNone(waiting(closed.core))
        closed.day_off()
        self.assertEqual(closed.core.day,5)
        self.assertEqual(closed.core.day_results[-1]['day_type'],'day_off')
        self.assertEqual(closed.core.day_results[-1]['summary']['operating_cost'],60)
        self.assertEqual(verify_cafe_interaction(closed.core.log()).snapshot(),closed.core.snapshot())

    def test_previous_automatic_trouble_rule_remains_compatible(self):
        selected=starting_conditions('free');selected.pop('intake_request')
        old=dict(rules(),probability=1)
        for key in SUPPORT_FIELDS:old.pop(key)
        old.pop('trouble_seat_loss')
        selected['store_events']=old
        s=create_game(Path(self.temp.name)/'previous',selected)
        s.day_off();self.assertEqual(row(s.core)['type'],'trouble')
        self.assertIsNone(waiting(s.core));s.day_off()
        self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'],110)
        self.reload(s)

    def test_support_small_and_decline_apply_the_selected_amount_once(self):
        for choice,cost,gain in (('small',50,2),('decline',0,0)):
            s=self.game();s.day_off();funds=s.core.funds;popularity=s.core.management['popularity']
            s.resolve_store_event(choice)
            self.assertEqual(s.core.funds,funds-cost)
            self.reload(s);s.day_off()
            self.assertEqual(s.core.management['popularity'],popularity+gain)
            self.assertEqual(s.core.day_results[-1]['summary']['store_event_expenses'],cost)

    def test_legacy_invalid_and_corrupt_draw(self):
        old=self.game(True);self.assertIsNone(old.core.store_events);old.day_off();self.reload(old)
        base=rules()
        for changed in (dict(probability=-1),dict(festival_customer_tick=-1),dict(trouble_cost=0),
                        dict(trouble_seat_loss=0),
                        dict(support_full_cost=0),dict(support_small_popularity=0),
                        dict(supply=dict(base['supply'],stress_relief=0))):
            with self.assertRaises(ValueError):rules(dict(base,**changed))
        s=self.game();s.day_off();source=checkpoint(s.core,set())
        for mutate in (lambda d:d['state']['store_events']['days'][0].update(draw=0.5),
                       lambda d:d['state']['store_events']['days'].pop(),
                       lambda d:d['state']['store_events']['days'][1].update(type='festival'),
                       lambda d:d['state']['store_events']['days'][1].update(cost=999)):
            bad=copy.deepcopy(source);mutate(bad);bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)


if __name__=='__main__':unittest.main()
