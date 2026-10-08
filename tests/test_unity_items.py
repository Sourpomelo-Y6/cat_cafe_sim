import copy
import unittest
from pathlib import Path
from tests import test_cafe_items as fixture
from test_unity_dispatch_choices import api
from cat_cafe_sim.core.cafe_item_shop import catalog
from cat_cafe_sim.unity_state_server import state_view

class UnityItemTests(unittest.TestCase):
    setUp = fixture.ItemTests.setUp
    session = fixture.ItemTests.session
    dispatch = fixture.ItemTests.dispatch
    received = fixture.ItemTests.received

    def test_purchase_sell_retry_and_save_resume(self):
        s = self.session()
        with api(s, Path(self.temp.name)/'saves') as (read, post):
            reference = copy.deepcopy(s); reference.purchase_item(catalog()[0])
            self.assertEqual(post('purchase_item', choice='care_supplies', cost=0)[0], 400)
            code, result, command = post('purchase_item', choice='care_supplies')
            self.assertEqual(code, 200, result)
            self.assertEqual(s.core.snapshot(), reference.core.snapshot())
            self.assertEqual(post('purchase_item', command)[:2], (code, result))
            saved = post('save_game')[1]['save_id']
            self.assertEqual(post('purchase_item', choice='care_supplies')[0], 200)
            self.assertEqual(read()['items']['owned'][0]['count'], 2)
            held = read()['items']['owned'][0]
            reference = copy.deepcopy(s); reference.sell_item(held['choice'])
            self.assertEqual(post('sell_item', choice=held['choice'], price=99999)[0], 400)
            code, result, command = post('sell_item', choice=held['choice'])
            self.assertEqual(code, 200, result)
            self.assertEqual(s.core.snapshot(), reference.core.snapshot())
            self.assertEqual(s.core.funds, held['funds_after'])
            self.assertEqual(post('sell_item', command)[:2], (code, result))
            self.assertEqual(read()['items']['owned'][0]['count'], 1)
            self.assertEqual(post('sell_item', choice=held['choice'])[0], 422)
            self.assertEqual(post('load_game', save_id=saved)[0], 200)
            self.assertEqual(read()['items']['count'], 1)
            loaded = s.core.snapshot()
            self.assertEqual(post('sell_item', command)[:2], (code, result))
            self.assertEqual(s.core.snapshot(), loaded)
            before = read()['items']
            self.assertEqual(post('purchase_item', choice='brushing_set')[0], 422)
            self.assertEqual(post('purchase_item')[0], 400)
            self.assertEqual(read()['items'], before)

    def test_reward_use_zero_effect_retry_and_resume(self):
        s = self.session(); source, cat = self.received(s)
        other = next(k for k in s.core.cats if k != cat)
        before = s.core.snapshot(); row = state_view(s)['items']
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual([r['choice'] for r in row['shop']], [r['item']['id'] for r in catalog()])
        self.assertNotIn('brushing_set', [r['choice'] for r in row['shop']])
        self.assertEqual(row['count'], 1)
        self.assertTrue(next(t for t in row['owned'][0]['targets'] if t['cat_id']==cat)['can_select'])
        with api(s, Path(self.temp.name)/'saves') as (read, post):
            self.assertEqual(post('use_item', choice=source, cat_id=other)[0], 422)
            self.assertEqual(post('use_item', choice=source)[0], 400)
            self.assertEqual(s.core.snapshot(), before)
            saved = post('save_game')[1]['save_id']
            reference = copy.deepcopy(s); reference.use_item(source, cat)
            code, result, command = post('use_item', choice=source, cat_id=cat)
            self.assertEqual(code, 200, result)
            self.assertEqual(s.core.snapshot(), reference.core.snapshot())
            self.assertEqual(post('use_item', command)[:2], (code, result))
            self.assertEqual(read()['items']['count'], 0)
            self.assertEqual(post('sell_item', choice=source)[0], 422)
            consumed = post('save_game')[1]['save_id']
            self.assertEqual(post('load_game', save_id=saved)[0], 200)
            self.assertEqual(read()['items']['count'], 1)
            self.assertEqual(post('load_game', save_id=consumed)[0], 200)
            self.assertEqual(read()['items']['count'], 0)
            self.assertTrue(read()['items']['history'])

    def test_phase_and_zero_funds_end_restrictions(self):
        s = self.session(); s.purchase_item(); s.step()
        with api(s, Path(self.temp.name)/'saves') as (read, post):
            row = read()['items']
            self.assertTrue(all(not r['can_select'] for r in row['shop']))
            self.assertFalse(row['owned'][0]['can_sell'])
            before = s.core.snapshot()
            self.assertEqual(post('purchase_item', choice='care_supplies')[0], 422)
            self.assertEqual(post('sell_item', choice=row['owned'][0]['choice'])[0], 422)
            self.assertEqual(s.core.snapshot(), before)
        end = self.session(); end.core.funds = catalog()[0]['cost']
        with api(end, Path(self.temp.name)/'ending') as (read, post):
            self.assertTrue(read()['items']['shop'][0]['ends_game'])
            self.assertEqual(post('purchase_item', choice='care_supplies')[0], 200)
            self.assertEqual(end.core.funds, 0)
            self.assertIsNotNone(read()['game_over'])
            self.assertEqual(post('purchase_item', choice='care_supplies')[0], 422)
    def test_fatigue_and_combined_items_match_python(self):
        for rule in catalog()[1:]:
            with self.subTest(item=rule['item']['id']):
                s = self.session()
                s.purchase_item(rule)
                cat = next(iter(s.core.cats))
                s.core.cats[cat].fatigue = 5
                s.core.management['stress'][cat] = 4
                with api(s, Path(self.temp.name)/rule['item']['id']) as (read, post):
                    held = read()['items']['owned'][0]
                    target = next(t for t in held['targets'] if t['cat_id']==cat)
                    self.assertTrue(target['can_select'])
                    self.assertIn('5 → 0', target['changes'])
                    reference = copy.deepcopy(s); reference.use_item(held['choice'],cat)
                    self.assertEqual(post('use_item', choice=held['choice'],cat_id=cat)[0],200)
                    self.assertEqual(s.core.snapshot(),reference.core.snapshot())
                    self.assertEqual(read()['items']['count'],0)
