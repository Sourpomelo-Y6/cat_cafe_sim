import copy
import unittest
from pathlib import Path
from unittest.mock import patch
import test_cafe_cat_details as fixtures
from test_unity_dispatch_choices import api
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import state_view, cat_records_view


class UnityCatRecordsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CatDetailsTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.s=self.fixture.session;self.root=Path(self.fixture.temp.name)

    def test_empty_legacy_and_read_only(self):
        before=copy.deepcopy(self.s.core.snapshot());raw=self.s.store.path.read_bytes()
        rows=state_view(self.s)['cats']
        for row in rows:
            self.assertIn('加入経路・加入日の記録はありません',row['records']['events'])
            self.assertIn('関係記録はありません',row['records']['relationships'])
            self.assertIn('日次実績はありません',row['records']['history'])
        self.assertEqual(before,self.s.core.snapshot());self.assertEqual(raw,self.s.store.path.read_bytes())

    def test_http_join_dispatch_item_and_save_reload(self):
        s=self.s;s.enable_management();s.open_recruitment()
        key=next(k for k,v in s.core.recruitment['candidates'].items() if v.get('trait',{}).get('id')=='outgoing')
        s.recruit_cat(key);s.dispatch(key);s.day_off();s.resolve_activity(f'dispatch-1-{key}');s.use_item(f'dispatch-1-{key}',key)
        before=copy.deepcopy(s.core.snapshot());raw=s.store.path.read_bytes()
        with api(s,self.root/'saves') as (read,post):
            record=next(c for c in read()['cats'] if c['cat_id']==key)['records']
            self.assertIn('加入経路：保護猫の受け入れ',record['events']);self.assertIn('加入日：1日目',record['events'])
            self.assertIn('派遣出発',record['events']);self.assertIn('帰還報酬の受取',record['events']);self.assertIn('ケア用品の使用',record['events'])
            self.assertIn('営業区分：休業',record['history'])
            other=next(c for c in read()['cats'] if c['cat_id']==self.fixture.ids[0])['records'];self.assertNotIn('派遣出発',other['events'])
            self.assertEqual(before,s.core.snapshot());self.assertEqual(raw,self.fixture.store.path.read_bytes())
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200)
            self.assertEqual(record,next(c for c in read()['cats'] if c['cat_id']==key)['records'])

    def test_pending_saved_relationship_and_daily_summary(self):
        s=self.s;s.automatic_step();s.automatic_step();key=next(iter(s.active_interactions.values())).cat_id
        with patch.object(s.store,'apply',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):s.automatic_step()
        record=cat_records_view(s,key);self.assertIn('未保存の交流成果',record['relationships']);self.assertIn('親しみ：0',record['relationships']);self.assertIn('未交流',record['relationships'])
        s.persist();record=cat_records_view(s,key);self.assertNotIn('未保存の交流成果',record['relationships']);self.assertIn('交流済み',record['relationships'])
        self.fixture.close_day();data=cat_details(s,key);record=cat_records_view(s,key)
        self.assertIn(f"接客件数：{data['history'][0][3]}",record['history']);self.assertIn(f"親しみ増減合計：{data['history'][0][-1]}",record['history'])
        s.core.day_results=[{'day':1,'cats':{key:{}}}];s.core.closed=False
        self.assertIn('接客件数：記録なし',cat_records_view(s,key)['history'])

    def test_intake_and_adopted_records(self):
        s=create_game(self.root/'new')
        for _ in range(3):s.day_off()
        s.resolve_intake_request('accept');key=s.core.intake_request['rules']['cat_id']
        self.assertIn('加入日：4日目',cat_records_view(s,key)['events'])
        s.core.adoption={'enabled':False,'events':{'fixture':{'id':'fixture','cat_id':key,'customer_id':'guest-1','day':4,'status':'resolved','choice':'accept','resolved_day':4,'guest_affinity':85,'player_affinity':0,'threshold':80}}}
        s.core.activities={'cats':{k:'cafe' for k in s.core.cats},'day_locations':{k:'cafe' for k in s.core.cats},'events':{}}
        s.core.activities['cats'][key]='adopted'
        before=copy.deepcopy(s.core.snapshot());record=next(c for c in state_view(s)['cats'] if c['cat_id']==key)['records']
        self.assertIn('譲渡先：佐藤さん',record['events']);self.assertIn('譲渡成立日：4日目',record['events']);self.assertIn('譲渡成立',record['events']);self.assertEqual(before,s.core.snapshot())

    def test_legacy_growth_missing_date_is_not_invented(self):
        s=create_game(self.root/'legacy-growth')
        for _ in range(3):s.day_off()
        s.resolve_intake_request('accept');key=s.core.intake_request['rules']['cat_id']
        growth=s.core.growth['cats'][key];growth.update(specialization='service',selected_day=None)
        before=copy.deepcopy(s.core.snapshot());record=next(c for c in state_view(s)['cats'] if c['cat_id']==key)['records']
        self.assertIn('日付の記録なし',record['events']);self.assertLess(record['events'].index('4日目'),record['events'].index('日付の記録なし'));self.assertEqual(before,s.core.snapshot())
