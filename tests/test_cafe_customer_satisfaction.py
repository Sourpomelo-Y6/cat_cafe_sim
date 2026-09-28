import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_customers import cat_rows, directory
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, outcome_result, restore
from cat_cafe_sim.core.cafe_customer_discontent import row as discontent_row
from cat_cafe_sim.core.cafe_customer_loyalty import row as loyalty_row
from cat_cafe_sim.core.cafe_customer_satisfaction import evaluate, latest, rules
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class CustomerSatisfactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def create(self, satisfaction=None, legacy=False):
        selected = starting_conditions('free'); selected.pop('intake_request')
        if legacy:
            selected.pop('customer_satisfaction')
        elif satisfaction is not None:
            selected['customer_satisfaction'] = satisfaction
        return create_game(Path(self.temp.name)/'games', selected)

    def reload(self, session):
        save_game(session, session.checkpoint_path)
        loaded, _ = load_game(session.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
        return loaded

    def test_satisfied_service_adds_bonus_loyalty_popularity_and_directory_result(self):
        selected = dict(rules(), satisfied_bonus=20)
        s = self.create(selected)
        while not s.core.closed: s.automatic_step()
        outcomes = [outcome_result(value) for value in s.core.outcomes.values()]
        result = outcomes[0]
        rating = evaluate(s.core, result)
        self.assertEqual(rating['level'], 'satisfied')
        self.assertEqual(rating['bonus'], 20)
        visit = s.core.visits[result['customer_id']]
        self.assertEqual(visit.bill, visit.seated_ticks*s.core.config.time_price + result['bonus_funds'] + 20)
        self.assertGreater(loyalty_row(s.core, result['customer_id'])['score'], 0)
        self.assertEqual(discontent_row(s.core, result['customer_id'])['score'], 0)
        self.assertEqual(s.core.day_result()['summary']['customer_satisfaction']['satisfied'], len(outcomes))
        listing = next(row for row in directory(s) if row['customer_id'] == result['customer_id'])
        self.assertEqual(listing['satisfaction']['level'], 'satisfied')
        self.assertTrue(any(event['kind']=='customer_satisfaction_result' for event in s.core.events))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_normal_and_dissatisfied_results_have_distinct_follow_up(self):
        s = self.create()
        s.step()
        rows = cat_rows(s, 'guest-1')
        matched = next(row['cat_id'] for row in rows if row['matches'])
        s.start('guest-1', matched); s.finish()
        self.assertEqual(latest(s.core, 'guest-1')['level'], 'normal')
        self.assertEqual(loyalty_row(s.core, 'guest-1')['score'], 0)
        s = self.create()
        s.step()
        mismatched = next(row['cat_id'] for row in cat_rows(s, 'guest-1') if not row['matches'])
        s.start('guest-1', mismatched); s.finish()
        self.assertEqual(latest(s.core, 'guest-1')['level'], 'dissatisfied')
        self.assertEqual(discontent_row(s.core, 'guest-1')['score'], rules()['dissatisfied_discontent_gain'])
        self.assertTrue(any(event['kind']=='customer_discontent_changed'
                            and event['reason']=='dissatisfied_service' for event in s.core.events))
        self.reload(s)

    def test_legacy_uses_old_qualification_and_corrupt_summary_is_rejected(self):
        old = self.create(legacy=True)
        while not old.core.closed: old.automatic_step()
        self.assertIsNone(old.core.customer_satisfaction)
        self.assertNotIn('customer_satisfaction', old.core.day_result()['summary'])
        self.reload(old)
        s = self.create()
        while not s.core.closed: s.automatic_step()
        s.next_day()
        source = checkpoint(s.core, set())
        bad = copy.deepcopy(source)
        bad['state']['day_results'][0]['summary']['customer_satisfaction']['satisfied'] += 1
        bad['digest'] = digest({key:value for key,value in bad.items() if key!='digest'})
        with self.assertRaises(ValueError): restore(bad)
        bad = copy.deepcopy(source)
        bad['state']['customer_satisfaction']['satisfied_bonus'] += 1
        bad['digest'] = digest({key:value for key,value in bad.items() if key!='digest'})
        with self.assertRaises(ValueError): restore(bad)
        with patch('cat_cafe_sim.core.cafe_customer_satisfaction.rules',
                   side_effect=lambda value=None: rules(value) if value is not None else self.fail('設定の再読込')):
            self.reload(s)

    def test_invalid_rules(self):
        base = rules()
        for change in (dict(satisfied_score=0), dict(dissatisfied_score=3),
                       dict(gauge_target=101), dict(satisfied_bonus=-1),
                       dict(dissatisfied_discontent_gain=float('inf'))):
            with self.assertRaises(ValueError): rules(dict(base, **change))


if __name__ == '__main__':
    unittest.main()
