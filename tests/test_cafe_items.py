import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.cafe_items import inventory, definition
from cat_cafe_sim.core.cafe_traits import definitions
from cat_cafe_sim.core.cafe_activities import destinations
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ItemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relations.json')
        add_playtest_cats(self.store)
        self.path = Path(self.temp.name)/'cafe.json'

    def session(self, seats=2, management=True):
        s = CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=3, arrival_ticks=()))
        key = next(iter(s.core.cats))
        s.core.initialize_traits({key: definitions()['outgoing']})
        if management:
            s.enable_management()
        return s

    def reload(self, s):
        save_game(s, self.path)
        restored, _ = load_game(self.path)
        self.assertEqual(restored.core.snapshot(), s.core.snapshot())
        return restored

    def dispatch(self, s):
        key = next(iter(s.core.cats))
        s.dispatch(key)
        return f'dispatch-{s.core.day}-{key}', key

    def received(self, s):
        source, key = self.dispatch(s)
        s.day_off()
        s.resolve_activity(source)
        return source, key

    def rejected(self, s, action):
        before = s.core.log()
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(before, s.core.log())

    def test_departure_return_use_save_and_replay_in_both_seat_modes(self):
        for seats in (1, 2):
            with self.subTest(seats=seats):
                s = self.session(seats)
                source, key = self.dispatch(s)
                self.assertEqual(inventory(s.core), {})
                s = self.reload(s)
                while not s.core.closed:
                    s.automatic_step()
                s = self.reload(s)
                self.assertEqual(inventory(s.core), {})
                s.resolve_activity(source)
                s.resolve_activity(source)
                self.assertEqual(len(inventory(s.core)), 1)
                self.assertEqual(s.core.funds, 1125)  # 外出好きの資金報酬は従来どおり。
                self.rejected(s, lambda: s.use_item(source, key))  # 閉店中は使わない。
                s.next_day()
                funds, fatigue = s.core.funds, s.core.cats[key].fatigue
                self.assertEqual(s.core.management['stress'][key], 10)
                s.use_item(source, key)
                self.assertEqual(s.core.management['stress'][key], 0)
                self.assertEqual((s.core.funds, s.core.cats[key].fatigue), (funds, fatigue))
                self.assertEqual(inventory(s.core), {})
                self.rejected(s, lambda: s.use_item(source, key))
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                self.reload(s)

    def test_frozen_effect_lower_bound_and_save_failure_retry(self):
        s = self.session()
        row = dict(id='care_supplies', name='ケア用品', stress_relief=20)
        with patch('cat_cafe_sim.core.cafe_items.for_destination', return_value=row):
            source, key = self.received(s)
        with patch('cat_cafe_sim.core.cafe_items.for_destination', side_effect=AssertionError('reroll')):
            s = self.reload(s)
            s.use_item(source, key)
            self.assertEqual(s.core.management['stress'][key], 0)
            before = s.core.snapshot()
            with patch.object(RelationshipStore, '_write', side_effect=OSError('full')):
                with self.assertRaises(OSError):
                    save_game(s, self.path)
            self.assertEqual(s.core.snapshot(), before)
            s = self.reload(s)
            self.assertEqual(len(s.core.item_uses), 1)
            self.assertEqual(inventory(s.core), {})

    def test_zero_stress_absent_cat_pending_events_and_no_management_block_use(self):
        s = self.session()
        source, key = self.received(s)
        other = list(s.core.cats)[1]
        self.rejected(s, lambda: s.use_item(source, other))  # ストレス0。
        s.dispatch(key)
        self.rejected(s, lambda: s.use_item(source, key))  # 派遣中。
        s.day_off()
        self.rejected(s, lambda: s.use_item(source, other))  # 帰還確認待ち。
        self.assertEqual(len(inventory(s.core)), 1)
        s.resolve_activity(f'dispatch-2-{key}')
        self.assertEqual(len(inventory(s.core)), 2)
        s.use_item(source, key)
        self.assertEqual(len(inventory(s.core)), 1)
        self.reload(s)
        old = self.session(management=False)
        other_source, other_key = self.received(old)
        self.rejected(old, lambda: old.use_item(other_source, other_key))
        self.assertEqual(len(inventory(old.core)), 1)

    def test_old_trip_has_no_reward_and_other_destinations_remain_cash_only(self):
        s = self.session()
        key = next(iter(s.core.cats))
        s.core.dispatch(key)  # 旧ログ相当：任意の報酬設定なし。
        s = self.reload(s)
        s.day_off(); s.resolve_activity(f'dispatch-1-{key}')
        self.assertEqual(inventory(s.core), {})
        self.assertNotIn('item_uses', s.core.snapshot())
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        s.dispatch(key, destinations()[2])
        event = s.core.activities['events'][f'dispatch-2-{key}']
        self.assertNotIn('item_reward', event)

    def test_invalid_uses_and_item_definitions_rejected(self):
        s = self.session()
        source, key = self.received(s)
        s.use_item(source, key)
        data = checkpoint(s.core, set())
        for mutate in (
            lambda d: d['item_uses'].append(copy.deepcopy(d['item_uses'][0])),
            lambda d: d['item_uses'][0].update(day=0),
            lambda d: d['item_uses'][0].update(source='unknown'),
            lambda d: d['item_uses'][0].update(after=1),
            lambda d: d['item_uses'][0].update(before=0),
            lambda d: d['activities']['events'][source]['item_reward'].update(stress_relief=-1),
        ):
            bad = copy.deepcopy(data)
            mutate(bad['state'])
            bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        for relief in (True, 0, -1, float('nan'), 101):
            with self.assertRaises(ValueError):
                definition(dict(id='care_supplies', name='ケア用品', stress_relief=relief))
