import copy
import unittest
from pathlib import Path
import test_cafe_cat_details as fixtures
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.core.cafe_traits import definitions
from cat_cafe_sim.core.cafe_activities import destinations
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CatEventsTests(unittest.TestCase):
    setUp = fixtures.CatDetailsTests.setUp

    def roundtrip(self, s, key):
        path = Path(self.temp.name)/'events.json'
        save_game(s, path)
        before, raw, relations = s.core.log(), path.read_bytes(), s.store.path.read_bytes()
        rows = cat_details(s, key)['events']
        restored, _ = load_game(path)
        self.assertEqual(cat_details(restored, key)['events'], rows)
        self.assertEqual(s.core.log(), before)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(s.store.path.read_bytes(), relations)
        return rows

    def test_recruitment_dispatch_items_filter_and_readonly_resume(self):
        s = self.session
        s.enable_management(); s.open_recruitment()
        key = next(k for k,v in s.core.recruitment['candidates'].items() if v.get('trait',{}).get('id')=='outgoing')
        s.recruit_cat(key); s.dispatch(key)
        rows = cat_events(s.core, key)
        self.assertEqual([r[1] for r in rows], ['加入', '派遣出発'])
        s.day_off()
        self.assertIn('報酬受取待ち', str(cat_events(s.core,key)))
        s.resolve_activity(f'dispatch-1-{key}')
        s.use_item(f'dispatch-1-{key}', key)
        rows = self.roundtrip(s,key)
        self.assertIn('ケア用品 ×1', str(rows))
        self.assertIn('ストレス 10 → 0', str(rows))
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))
        self.assertEqual(cat_events(s.core,self.ids[0]), [])

    def test_intake_join_and_old_empty_history(self):
        self.assertEqual(cat_details(self.session,self.ids[0])['events'], [])
        s = create_game(Path(self.temp.name)/'games')
        for _ in range(3):
            s.day_off()
        s.resolve_intake_request('accept')
        key = s.core.intake_request['rules']['cat_id']
        rows = self.roundtrip(s,key)
        self.assertEqual(rows, [(4,'加入','保護猫の受け入れ依頼','初期費用 200')])
        self.assertEqual(dict(cat_details(s,key)['basic'])['加入日'], '4日目')

    def test_dispatch_choices_pending_and_resolved_report_actual_effects(self):
        s = self.session; key=self.ids[0]
        s.enable_management();s.core.initialize_traits({key:definitions()['hospitality']})
        s.dispatch(key,destinations()[1]);s.day_off()
        self.assertIn('回答待ち', str(self.roundtrip(s,key)))
        event_id=f'dispatch-1-{key}'
        s.resolve_dispatch_choice(event_id,'accept')
        rows=self.roundtrip(s,key)
        self.assertIn('帰還報酬の増減 +100',str(rows))
        self.assertIn('疲労 0 → 10',str(rows))
        self.assertNotIn('帰還報酬の受取',str(rows))
        s.day_off();s.resolve_activity(event_id)
        self.assertIn('資金報酬合計：360',str(self.roundtrip(s,key)))

    def test_missing_adoption_statuses_and_unrecorded_values_are_not_invented(self):
        core=self.session.core;key=self.ids[0];other=self.ids[1]
        # Display fixtures cover statuses independently of simulation thresholds.
        core.management=dict(rules=dict(missing_days=2),events={
            'm':dict(cat_id=key,departed_day=1,status='missing',resolved_day=None,kitten=True,cost=0)})
        self.assertEqual(cat_events(core,key),[(1,'家出','店外','行方不明')])
        core.management['events']['m']['status']='waiting'
        self.assertIn((3,'家出猫の帰還','お店','帰還・費用の確認待ち'),cat_events(core,key))
        core.management['events']['m'].update(status='resolved',resolved_day=4,cost=200)
        core.adoption=dict(events={'a':dict(cat_id=key,customer_id='guest-1',day=5,status='waiting',choice=None,resolved_day=None)})
        self.assertIn('回答待ち',str(cat_events(core,key)))
        core.adoption['events']['a'].update(status='resolved',choice='decline',resolved_day=5)
        self.assertIn('見送り',str(cat_events(core,key)))
        core.adoption['events']['a'].update(choice='accept')
        before=copy.deepcopy((core.management,core.adoption))
        rows=cat_events(core,key)
        self.assertIn('譲渡成立',str(rows))
        self.assertIn((5, '譲渡への回答', '佐藤さん', '譲渡成立'), rows)
        self.assertIn('子猫の引き渡し費用 200',str(rows))
        self.assertNotIn('人気',str(rows))
        self.assertEqual(cat_events(core,other),[])
        self.assertEqual((core.management,core.adoption),before)
