import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_customers import directory
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_expansion import EXTRA_CUSTOMER_ID, extra_schedule, reason, rules
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class FourSeatExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        selected = starting_conditions()
        selected.pop('intake_request')
        selected['store_events']['probability']=0
        selected['goal']['target'] = 105
        self.session = create_game(Path(self.temp.name)/'games', selected)

    def reload(self, session):
        save_game(session, session.checkpoint_path)
        loaded, _ = load_game(session.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
        return loaded

    def rejected(self, session, action):
        before = session.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(session.core.log(), before)

    def unlock_and_buy(self):
        s = self.session
        s.expand_seats()
        self.rejected(s, s.expand_seats)
        while not s.core.closed:
            s.automatic_step()
        self.assertEqual(s.core.goal['status'], 'cleared')
        self.rejected(s, s.expand_seats)
        s.continue_goal(); s.next_day()
        before = s.core.funds
        s.expand_seats()
        self.assertEqual(s.core.funds, before-1000)
        return s

    def test_unlock_purchase_next_day_customer_save_replay_and_day_off(self):
        s = self.unlock_and_buy()
        self.assertEqual(len(s.core.seats), 4)
        self.assertEqual(s.core.summary()['seat_count'], 4)
        self.assertEqual(s.core.summary()['expansion_expenses'], 1000)
        self.assertNotIn(EXTRA_CUSTOMER_ID, extra_schedule(s.core, s.core.day))
        row = next(row for row in directory(s) if row['customer_id'] == EXTRA_CUSTOMER_ID)
        self.assertIsNone(row['arrival_tick'])
        self.assertEqual(row['tomorrow_tick'], 0)
        before = s.core.snapshot(); directory(s); self.assertEqual(s.core.snapshot(), before)
        s = self.reload(s)
        s.day_off()
        self.assertEqual(s.core.day_results[-1]['customer_visits'], [])
        self.assertIn(EXTRA_CUSTOMER_ID, extra_schedule(s.core, s.core.day))
        s.step()
        self.assertIn(EXTRA_CUSTOMER_ID, s.core.visits)
        self.assertEqual(s.core.visits[EXTRA_CUSTOMER_ID].arrival_tick, 0)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_four_simultaneous_seats_dispatch_and_equipment(self):
        s = self.unlock_and_buy()
        # 4席目は購入当日から設備と接客に利用できる。
        item = dict(id='toys', name='おもちゃセット', cost=300, engagement=1.2, tension=1)
        s.purchase_seat_equipment('seat-4', item)
        self.assertIsNotNone(s.core.seats['seat-4'].equipment)
        s.day_off()
        while not s.core.closed and len(s.active_interactions) < 4:
            s.automatic_step()
        self.assertEqual(set(s.active_interactions), {'seat-1','seat-2','seat-3','seat-4'})
        s = self.reload(s)
        s.automatic_step()
        while not s.core.closed:
            s.automatic_step()
        s.next_day()
        keys = list(s.core.cats)
        s.dispatch(keys[0])
        self.rejected(s, lambda: s.dispatch(keys[1]))
        s.open_recruitment(); s.recruit_cat(next(iter(s.core.recruitment['candidates'])))
        s.dispatch(keys[1])
        self.rejected(s, lambda: s.dispatch(keys[2]))
        self.reload(s)

    def test_funds_boundary_failed_save_and_no_duplicate_purchase(self):
        s = self.session
        s.expand_seats()
        while not s.core.closed: s.automatic_step()
        s.continue_goal(); s.next_day()
        s.core.funds = 1000
        self.rejected(s, s.expand_seats)
        s.core.funds = 1001
        # Direct fund edits are used only for the boundary before recording the operation.
        s.core.recorded_digest = None
        s.expand_seats()
        self.assertEqual(s.core.funds, 1)
        self.rejected(s, s.expand_seats)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s, s.checkpoint_path)
        self.assertEqual(s.core.funds, 1)

    def test_corrupt_four_seat_records_rejected(self):
        s = self.unlock_and_buy()
        source = checkpoint(s.core, set())
        for mutate in (
            lambda d: d['state']['expansion']['purchases'].pop(),
            lambda d: d['state']['expansion']['purchases'][1].update(seats=5),
            lambda d: d['state']['expansion']['purchases'][1].update(day=0),
            lambda d: d['state']['expansion']['purchases'][1].update(cost=900),
            lambda d: d.update(seat_count=3),
            lambda d: d['state']['seats'].pop('seat-4'),
            lambda d: d['state']['goal'].update(status='active', resolved_day=None),
        ):
            bad = copy.deepcopy(source); mutate(bad)
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError): restore(bad)

    def test_legacy_three_seat_record_remains_readable(self):
        s = self.session; s.expand_seats()
        data = checkpoint(s.core, set())
        row = data['state']['expansion']['purchases'][0]
        data['state']['expansion'] = dict(day=row['day'], cost=row['cost'])
        data['digest'] = digest({k:v for k,v in data.items() if k != 'digest'})
        loaded = restore(data)
        self.assertEqual(len(loaded.seats), 3)
        self.assertIn('人気目標の第1段階', reason(loaded, rules()))
