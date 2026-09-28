import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_customer_loyalty import rules, row, extra_weekday
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_weekdays import schedule, DAYS
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CustomerLoyaltyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def create(self, mode='free', loyalty=None, legacy=False):
        selected = starting_conditions(mode)
        selected.pop('intake_request')
        if legacy:
            selected.pop('customer_loyalty')
            selected.pop('customer_discontent')
        elif loyalty is not None:
            selected['customer_loyalty'] = loyalty
        if mode == 'popularity':
            selected['goal']['target'] = 105
        return create_game(Path(self.temp.name)/'games', selected)

    def reload(self, session):
        save_game(session, session.checkpoint_path)
        loaded, _ = load_game(session.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
        return loaded

    def test_positive_service_makes_regular_and_adds_weekly_visit(self):
        s = self.create(loyalty=dict(gain=25, threshold=25))
        while not s.core.closed:
            s.automatic_step()
        regular = row(s.core, 'guest-1')
        self.assertEqual(regular, dict(score=25, regular_day=1))
        self.assertEqual(extra_weekday(s.core, 'guest-1'), 1)  # 通常は来ない火曜日
        self.assertIn('guest-1', schedule(s.core, 2))
        event = next(e for e in s.core.events if e['kind'] == 'customer_loyalty_gained' and e['customer_id'] == 'guest-1')
        self.assertTrue(event['became_regular'])
        s = self.reload(s)
        s.next_day(); s.step()
        self.assertIn('guest-1', s.core.visits)
        self.assertFalse(s.core.visits['guest-1'].first_visit)
        listing = next(r for r in directory(s) if r['customer_id'] == 'guest-1')
        self.assertIn('常連', listing['weekdays'])
        self.assertEqual(listing['loyalty'], 25)
        self.assertEqual(listing['regular_day'], 1)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_no_affinity_gain_no_loyalty_and_day_off_does_not_visit(self):
        s = self.create(loyalty=dict(gain=25, threshold=25))
        s.step(); s.start('guest-1', 'cat-sora'); s.finish()
        self.assertIsNone(row(s.core, 'guest-1')['regular_day'])
        self.assertEqual(row(s.core, 'guest-1')['score'], 0)
        self.assertFalse(any(e['kind'] == 'customer_loyalty_gained' for e in s.core.events))
        while not s.core.closed: s.step()
        s.next_day(); s.day_off()
        self.assertEqual(s.core.day_results[-1]['customer_visits'], [])
        self.reload(s)

    def test_default_progress_and_all_customer_types_use_same_state(self):
        s = self.create('popularity', loyalty=dict(gain=25, threshold=25))
        while not s.core.closed: s.automatic_step()
        self.assertEqual(s.core.goal['status'], 'cleared')
        s.continue_goal(); s.next_day(); s.expand_seats(); s.expand_seats()
        s.step()
        from cat_cafe_sim.core.cafe_advanced_customers import CUSTOMER_ID
        self.assertIn(CUSTOMER_ID, s.core.queue)
        s.start(CUSTOMER_ID, 'cat-mike')
        while s.active_interactions: s.automatic_step()
        self.assertEqual(row(s.core, CUSTOMER_ID)['regular_day'], 2)
        while not s.core.closed: s.automatic_step()
        s.next_day(); s.step()
        from cat_cafe_sim.core.cafe_expansion import EXTRA_CUSTOMER_ID
        self.assertIn(EXTRA_CUSTOMER_ID, s.core.queue)
        s.start(EXTRA_CUSTOMER_ID, 'cat-mugi')
        while s.active_interactions: s.automatic_step()
        self.assertEqual(row(s.core, EXTRA_CUSTOMER_ID)['regular_day'], 3)
        self.assertIn(DAYS[extra_weekday(s.core, CUSTOMER_ID)], range_text(s, CUSTOMER_ID))
        self.reload(s)

    def test_legacy_and_corrupt_state(self):
        old = self.create(legacy=True)
        while not old.core.closed: old.automatic_step()
        self.assertIsNone(old.core.customer_loyalty)
        self.assertNotIn('customer_loyalty', self.reload(old).core.snapshot())
        s = self.create(loyalty=dict(gain=25, threshold=25))
        while not s.core.closed: s.automatic_step()
        source = checkpoint(s.core, set())
        for mutate in (
            lambda d: d['state']['customer_loyalty']['customers']['guest-1'].update(score=0),
            lambda d: d['state']['customer_loyalty']['customers']['guest-1'].update(regular_day=2),
            lambda d: d['state']['customer_loyalty']['rules'].update(gain=20),
            lambda d: d['state'].pop('customer_loyalty'),
        ):
            bad = copy.deepcopy(source); mutate(bad)
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            if 'customer_loyalty' not in bad['state']:
                loaded = restore(bad)
                self.assertIsNone(loaded.customer_loyalty)
            else:
                with self.assertRaises(ValueError): restore(bad)
        with patch('cat_cafe_sim.core.cafe_customer_loyalty.rules', side_effect=lambda value=None: rules(value) if value is not None else self.fail('設定の再読込')):
            self.reload(s)

    def test_invalid_rules(self):
        for value in (dict(gain=0, threshold=100), dict(gain=True, threshold=100),
                      dict(gain=101, threshold=100), dict(gain=25, threshold=float('inf'))):
            with self.assertRaises(ValueError): rules(value)


def range_text(session, customer_id):
    return next(r for r in directory(session) if r['customer_id'] == customer_id)['weekdays']
