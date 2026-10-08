import copy
import unittest
from pathlib import Path
from importlib import import_module
from test_unity_dispatch_choices import api
import test_cafe_customers as fixtures
import test_cafe_customer_trust as trust_fixtures
import test_cafe_customer_discontent as discontent_fixtures
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import state_view

class UnityCustomerDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CustomerDirectoryTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.fixture.temp.name)
    def test_read_only_planned_preferences_cat_matches_and_legacy(self):
        s=self.fixture.session();s.core.initialize_preferences({k:['white'] for k in s.core.cats},dict(pool=['white'],tension_multiplier=1.25))
        before=copy.deepcopy(s.core.snapshot());stored=s.store.path.read_bytes();rows=state_view(s)['customer_directory']['rows']
        self.assertEqual(before,s.core.snapshot());self.assertEqual(stored,s.store.path.read_bytes());self.assertEqual(s.core.customer_preferences['customers'],{})
        self.assertEqual([r['customer_id'] for r in rows],[r['customer_id'] for r in directory(s)])
        for row,source in zip(rows,directory(s)):
            self.assertEqual(row['visits'],source['visits']);self.assertIn(str(source['arrival_tick'])+'刻',row['today'])
            self.assertIn('未導入',row['details']);self.assertTrue(all('好みに一致' in r['details'] and '×1.25' in r['details'] for r in row['cats']))
        legacy=self.fixture.session();self.assertTrue(all('好み未設定' in c['details'] for r in state_view(legacy)['customer_directory']['rows'] for c in r['cats']))
    def test_http_save_load_live_counts_and_existing_relationships(self):
        s=self.fixture.session();cat=next(iter(s.core.cats));interaction=s.store.begin(s.interaction_config,cat,'legacy-customer');interaction.step('direct');interaction.finish();s.store.apply(interaction);s=self.fixture.session()
        stored=s.store.path.read_bytes()
        with api(s,self.root/'saves') as (read,post):
            before=s.core.snapshot();initial=read()['customer_directory'];self.assertEqual(before,s.core.snapshot())
            custom=next(r for r in initial['rows'] if r['customer_id']=='legacy-customer');self.assertEqual(custom['visits'],0);self.assertIn('予定なし',custom['today'])
            self.assertIn(f"親しみ {interaction.result()['affinity_after']:g}",next(r for r in custom['cats'] if r['cat_id']==cat)['details'])
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('start_business')[0],200);self.assertEqual(post('advance_business')[0],200)
            changed=read()['customer_directory'];self.assertNotEqual(initial,changed);self.assertGreater(changed['rows'][0]['visits'],0)
            snapshot=s.core.snapshot();self.assertEqual(read()['customer_directory'],changed);self.assertEqual(s.core.snapshot(),snapshot)
            self.assertEqual(post('load_game',save_id=saved)[0],200);self.assertEqual(read()['customer_directory'],initial)
        self.assertEqual(self.fixture.store.path.read_bytes(),stored)
    def test_special_customer_conditions_without_unrelated_latest_result(self):
        s=create_game(self.root/'specials');rows={r['customer_id']:r for r in state_view(s)['customer_directory']['rows']}
        for name in ('advanced_customers','vip_customer','quiet_customer','play_customer','contact_customer','longhair_customer'):
            module=import_module('cat_cafe_sim.core.cafe_'+name);row=rows[module.CUSTOMER_ID]
            self.assertIn(module.description(s.core),row['details']);self.assertIn('接客記録はまだありません',row['details'])
        self.assertIn('予約条件',rows['reservation-longhair']['details'])
        while not s.core.closed:s.automatic_step()
        row=next(r for r in state_view(s)['customer_directory']['rows'] if r['customer_id']=='advanced-longhair')
        self.assertIn('接客記録はまだありません',row['details'])
        self.assertIn('満足度の基準',row['details'])
    def test_discontent_suspension_recovery_and_departure_reasons(self):
        fixture=discontent_fixtures.CustomerDiscontentTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        selected=dict(discontent_fixtures.rules(),waiting_gain=100);s=fixture.session(selected);s.step()
        before=s.core.snapshot();row=next(r for r in state_view(s)['customer_directory']['rows'] if r['customer_id']=='guest-2')
        self.assertEqual(before,s.core.snapshot());self.assertIn('来店停止',row['today']);self.assertIn('来店停止',row['tomorrow']);self.assertIn('上限で退店',row['details']);self.assertIn('復帰',row['details'])
        fixture=trust_fixtures.CustomerTrustTests();fixture.setUp();self.addCleanup(fixture.doCleanups);event=fixture.warning();s=fixture.s
        row=next(r for r in state_view(s)['customer_directory']['rows'] if r['customer_id']=='guest-1');self.assertIn('回答待ち',row['details'])
        s.resolve_customer_trust(event['id'],'ignore');row=next(r for r in state_view(s)['customer_directory']['rows'] if r['customer_id']=='guest-1')
        self.assertIn('永久離脱',row['today']);self.assertIn('永久離脱',row['tomorrow']);self.assertIn('対応しなかった',row['details'])

if __name__=='__main__':unittest.main()
