import copy
import unittest
from dataclasses import replace

import test_cafe_patron as fixtures
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_customers import directory, cat_rows, preference, customer_name, customer_label
from cat_cafe_sim.core.cafe_preferences import rules, preference_for
from cat_cafe_sim.core.config import Config


class CustomerDirectoryTests(unittest.TestCase):
    setUp = fixtures.PatronTests.setUp
    reload = fixtures.PatronTests.reload

    def session(self):
        return CafeInteractionSession(store=self.store, cafe_config=replace(Config.load(),
            opening_ticks=4, arrival_ticks=(0, 0, 2), queue_capacity=1))

    def test_schedule_preference_readonly_and_actual_arrivals(self):
        s = self.session()
        cats = {key: ['white'] for key in s.core.cats}
        s.core.initialize_preferences(cats, rules())
        before = copy.deepcopy(s.core.log())
        stored = self.store.path.read_bytes()
        rows = directory(s)
        self.assertEqual([r['arrival_tick'] for r in rows], [0, 0, 2])
        self.assertEqual([r['visits'] for r in rows], [0, 0, 0])
        self.assertTrue(all(r['status']=='来店予定' for r in rows))
        for row in rows:
            self.assertEqual(row['preference'], preference_for(s.core.seed, row['customer_id'], rules()['pool']))
            for cat in cat_rows(s, row['customer_id']):
                self.assertEqual(cat['matches'], row['preference']=='white')
        self.assertEqual(s.core.log(), before)
        self.assertEqual(self.store.path.read_bytes(), stored)
        self.assertEqual(s.core.customer_preferences['customers'], {})
        s = self.reload(s)
        self.assertEqual(directory(s), rows)
        s.step()
        arrived = directory(s)
        self.assertEqual([r['visits'] for r in arrived], [1, 1, 0])
        self.assertEqual(arrived[1]['status'], '退店済み')
        for row in arrived[:2]:
            self.assertEqual(row['preference'], s.core.customer_preferences['customers'][row['customer_id']])
        self.assertEqual(arrived[0]['name'], rows[0]['name'])

    def test_counts_include_unserved_visits_not_days_off_and_do_not_double_count(self):
        s = self.session()
        s.enable_management()
        while not s.core.closed:
            s.step()
        self.assertEqual([r['visits'] for r in directory(s)], [1, 1, 1])
        s.next_day()
        self.assertEqual([r['visits'] for r in directory(s)], [1, 1, 1])
        s.day_off()
        self.assertEqual([r['visits'] for r in directory(s)], [1, 1, 1])
        s.step()
        expected = directory(s)
        self.assertEqual([r['visits'] for r in expected], [2, 2, 1])
        s = self.reload(s)
        self.assertEqual(directory(s), expected)

    def test_existing_affinity_and_unknown_customer_without_invented_visits(self):
        s = self.session()
        key = next(iter(s.core.cats))
        interaction = self.store.begin(s.interaction_config, key, 'old-customer')
        interaction.step('direct')
        interaction.finish()
        self.store.apply(interaction)
        s = self.session()
        rows = {r['customer_id']: r for r in directory(s)}
        self.assertEqual(rows['old-customer']['visits'], 0)
        self.assertIsNone(rows['old-customer']['arrival_tick'])
        self.assertEqual(rows['old-customer']['status'], '本日の予定なし')
        self.assertIsNone(preference(s.core, 'old-customer'))
        self.assertEqual(next(row for row in cat_rows(s,'old-customer') if row['cat_id']==key)['affinity'], interaction.result()['affinity_after'])
        s = self.reload(s)
        self.assertEqual({r['customer_id']:r for r in directory(s)}, rows)

    def test_names_ids_and_missing_preferences(self):
        s = self.session()
        self.assertEqual(customer_name('guest-1'), '佐藤さん')
        self.assertIn('guest-1', customer_label('guest-1'))
        self.assertEqual(customer_name('guest-21'), 'お客さん21')
        self.assertEqual(customer_name('custom'), 'custom')
        self.assertTrue(all(row['preference_text']=='未設定' for row in directory(s)))
        self.assertTrue(all(row['match_text']=='好み未設定' for row in cat_rows(s,'guest-1')))
        self.assertIsNone(s.core.customer_preferences)
