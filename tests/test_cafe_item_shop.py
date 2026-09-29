import copy
import unittest
from unittest.mock import patch
from tests import test_cafe_items as item_tests
from cat_cafe_sim.core.cafe_items import inventory
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,restore,digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction


class ItemShopTests(unittest.TestCase):
    setUp=item_tests.ItemTests.setUp
    session=item_tests.ItemTests.session
    received=item_tests.ItemTests.received
    dispatch=item_tests.ItemTests.dispatch
    reload=item_tests.ItemTests.reload
    rejected=item_tests.ItemTests.rejected
    def test_purchase_use_save_replay_and_finance(self):
        for seats in (1,2):
            s=self.session(seats);key=next(iter(s.core.cats))
            source,key=self.received(s)
            before=s.core.funds;s.purchase_item()
            self.assertEqual(s.core.funds,before-100)
            self.assertEqual(len(inventory(s.core)),2)
            self.assertEqual(s.core.summary()['item_expenses'],100)
            s=self.reload(s);s.use_item('item-purchase-1',key)
            self.assertEqual(len(inventory(s.core)),1)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.reload(s)

    def test_purchase_restrictions_and_zero_funds_ending(self):
        s=self.session();s.purchase_item()
        s.step();self.rejected(s,s.purchase_item)
        poor=self.session();poor.core.funds=99;self.rejected(poor,poor.purchase_item)
        end=self.session();end.core.funds=100;end.purchase_item()
        self.assertEqual(end.core.management['game_over']['reason'],'funds')
        self.rejected(end,end.purchase_item)

    def test_corrupt_purchase_records_rejected_and_effect_frozen(self):
        s=self.session();s.purchase_item()
        with patch('cat_cafe_sim.core.cafe_item_shop.rules',side_effect=lambda data=None: data if data is not None else self.fail('reload catalog')):
            s=self.reload(s)
        data=checkpoint(s.core,set())
        for mutation in (lambda row:row.update(cost=-1),lambda row:row.update(day=0),lambda row:row.update(source='invalid')):
            bad=copy.deepcopy(data);mutation(bad['state']['item_purchases'][0])
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)

    def test_purchase_in_daily_finance(self):
        from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
        from pathlib import Path
        selected=starting_conditions('free');selected.pop('intake_request')
        selected['store_events']['probability']=0
        s=create_game(Path(self.temp.name)/'games',selected)
        before=s.core.funds;s.purchase_item();s.day_off()
        summary=s.core.day_results[-1]['summary']
        self.assertEqual(summary['item_expenses'],100)
        self.assertEqual(summary['opening_funds'],before)
        self.assertEqual(summary['total_expenses'],100+summary['operating_cost'])
        self.reload(s)
