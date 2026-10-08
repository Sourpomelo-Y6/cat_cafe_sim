import copy
import unittest
from pathlib import Path
import test_cafe_pet_shop as fixtures
from test_unity_dispatch_choices import api
from cat_cafe_sim.unity_state_server import state_view


class UnityPetShopTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PetShopTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.fixture.temp.name)

    def test_read_only_fixed_candidates_and_legacy(self):
        s=self.fixture.game();before=copy.deepcopy(s.core.snapshot());files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
        shop=state_view(s)['pet_shop'];self.assertEqual(shop,state_view(s)['pet_shop']);self.assertEqual(before,s.core.snapshot());self.assertEqual(files,{p:p.read_bytes() for p in files})
        self.assertEqual([r['name'] for r in shop['rows']],['チロ','レオ','ナナ']);self.assertEqual([r['cost'] for r in shop['rows']],[400,450,500]);self.assertTrue(all(r['can_purchase'] for r in shop['rows']))
        for row in shop['rows']:
            for label in ('個性','特徴','特性','好み','強さ','飼育スペース'):self.assertIn(label,row['details'])
            self.assertNotIn(row['cat_id'],s.store._read()['cats'])
        self.assertIsNone(state_view(self.fixture.game(legacy=True))['pet_shop'])

    def test_http_purchase_retry_roster_history_accounting_and_save(self):
        s=self.fixture.game();files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
        with api(s,self.root/'saves') as (read,post):
            initial=read();key=initial['pet_shop']['rows'][0]['cat_id'];code,result,command=post('purchase_cat',cat_id=key);self.assertEqual(code,200)
            state=result['state'];self.assertEqual(state['funds'],2600);self.assertEqual(len(state['cats']),6)
            cat=next(c for c in state['cats'] if c['cat_id']==key);self.assertFalse(cat['working']);self.assertEqual(cat['stamina'],cat['max_stamina']);self.assertEqual(cat['health_status'],'healthy')
            self.assertIn('加入経路：ペットショップ',cat['records']['events']);self.assertIn('加入日：1日目',cat['records']['events']);self.assertEqual(s.core.summary()['pet_shop_expenses'],400)
            self.assertTrue(state['pet_shop']['rows'][0]['accepted']);self.assertFalse(state['pet_shop']['rows'][0]['can_purchase']);self.assertTrue(all(not r['can_purchase'] for r in state['pet_shop']['rows'][1:]))
            self.assertEqual(post('purchase_cat',command)[0],200);self.assertEqual(read(),state);before=copy.deepcopy(s.core.snapshot());self.assertEqual(post('purchase_cat',cat_id=key)[0],422);self.assertEqual(before,s.core.snapshot())
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200);restored=read();self.assertEqual(restored['pet_shop'],state['pet_shop']);self.assertEqual(restored['cats'],state['cats'])
            self.assertEqual(post('purchase_cat',command)[0],200);self.assertEqual(read()['funds'],2600)
        self.assertEqual(files,{p:p.read_bytes() for p in files})

    def test_budget_preparation_required_event_and_invalid_commands(self):
        s=self.fixture.game(funds=400);row=state_view(s)['pet_shop']['rows'][0];self.assertFalse(row['can_purchase']);self.assertIn('資金',row['reason'])
        with api(s,self.root/'blocked') as (read,post):
            before=copy.deepcopy(s.core.snapshot())
            for fields,expected in [({},400),({'cat_id':3},400),({'cat_id':'unknown'},422),({'cat_id':'shop-1'},422),({'cat_id':'shop-1','working_cats':['cat-mike']},422)]:
                self.assertEqual(post('purchase_cat',**fields)[0],expected);self.assertEqual(before,s.core.snapshot())
        s=self.fixture.game();s.automatic_step();self.assertTrue(all(not r['can_purchase'] for r in state_view(s)['pet_shop']['rows']))
        s=self.fixture.game(intake=True)
        for _ in range(3):s.day_off()
        shop=state_view(s)['pet_shop'];self.assertTrue(all(not r['can_purchase'] for r in shop['rows']));self.assertTrue(any('受け入れ' in r['reason'] for r in shop['rows']))
