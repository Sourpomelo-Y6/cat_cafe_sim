import io
import tempfile
import signal
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_autoplay import AutoPlayer, main
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore
from cat_cafe_sim.core.cafe_goal import rules
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class AutoPlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def session(self, name='game', *, days=3, target=105, funds=1000, stages=True, cat_ids=None):
        root = Path(self.temp.name)/name
        root.mkdir()
        store = RelationshipStore(root/'relationships.json')
        for key in ('a', 'b', 'c'):
            store.register_cat(key, key, Personality())
        session = CafeInteractionSession(store=store, seat_count=2, cat_ids=cat_ids,
            cafe_config=replace(Config.load(), opening_ticks=2, arrival_ticks=(0,), initial_funds=0),
            interaction_config=replace(RelationshipConfig(), ticks=1))
        session.enable_management(dict(management_rules(), starting_funds=funds, stress_per_service_tick=0))
        selected = dict(rules(), target=target, days=days)
        if stages:
            selected['stages'] = [dict(target=target+5, days=days), dict(target=target+10, days=days)]
        session.enable_goal(selected)
        save_game(session, root/'cafe.json')
        return session

    def test_three_stages_and_replay(self):
        s = self.session()
        lines = []
        result = AutoPlayer(s, emit=lines.append).run()
        self.assertEqual(result.reason, 'completed')
        self.assertEqual(result.days, 3)
        self.assertEqual(len(s.core.goal['history']), 2)
        self.assertTrue(any('次の人気段階' in line for line in lines))
        self.assertTrue(any('日目の結果' in line for line in lines))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_expiry_and_day_limit_are_distinct(self):
        for limit, reason in ((1, 'day_limit'), (5, 'expired')):
            s = self.session(str(limit), days=2, target=200, stages=False)
            result = AutoPlayer(s, max_days=limit).run()
            self.assertEqual(result.reason, reason)
            self.assertEqual(result.days, min(limit, 2))

    def test_game_over_after_real_operating_cost(self):
        s = self.session(funds=1, target=200, stages=False)
        from cat_cafe_sim.core.cafe_operating_cost import rules as cost_rules
        s.core.initialize_operating_cost(dict(cost_rules(), base_cost=100000))
        result = AutoPlayer(s).run()
        self.assertEqual(result.reason, 'game_over')
        self.assertTrue(s.core.management['game_over'])

    def test_cancel_operation_limit_and_incompatible_game(self):
        s = self.session()
        player = AutoPlayer(s, max_operations=1)
        self.assertTrue(player.step())
        before = s.core.snapshot()
        self.assertFalse(player.step())
        self.assertEqual(player.result.reason, 'operation_limit')
        self.assertEqual(s.core.snapshot(), before)
        player = AutoPlayer(s)
        player.cancel()
        self.assertFalse(player.step())
        self.assertEqual(player.result.reason, 'cancelled')
        self.assertEqual(s.core.snapshot(), before)
        other = CafeInteractionSession(store=s.store)
        before = other.core.snapshot()
        self.assertEqual(AutoPlayer(other).run().reason, 'blocked')
        self.assertEqual(other.core.snapshot(), before)

    def test_save_reload_after_every_operation_matches_decisions(self):
        self.compare_reloads('basic')

    def compare_reloads(self, mode):
        direct = self.session('direct')
        resumed = self.session('resumed')
        logs_a, logs_b = [], []
        a = AutoPlayer(direct, emit=logs_a.append, detailed=True, mode=mode)
        b = AutoPlayer(resumed, emit=logs_b.append, detailed=True, mode=mode)
        while True:
            # 交流IDのUUIDだけ固定し、判断・会計・交流結果の一致を比較する。
            ids = [f'interaction-{a.operations}-{i}' for i in range(10)]
            with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                progressed = a.step()
            with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                self.assertEqual(b.step(), progressed)
            if not progressed:
                break
            path = b.session.checkpoint_path
            save_game(b.session, path)
            b.session = load_game(path)[0]
            self.assertEqual(a.session.core.snapshot(), b.session.core.snapshot())
        self.assertEqual(a.result, b.result)
        self.assertEqual(logs_a, logs_b)

    def test_new_game_growth_answers_and_snapshot_roundtrip(self):
        selected = starting_conditions()
        selected['goal'] = dict(rules(), target=101, days=4,
                               stages=[dict(target=102, days=4), dict(target=103, days=4)])
        selected['growth'] = dict(selected['growth'], threshold=1, mastery_threshold=1,
                                  type_mastery_threshold=1)
        s = create_game(Path(self.temp.name)/'normal', selected)
        result = AutoPlayer(s).run()
        self.assertEqual(result.reason, 'completed')
        self.assertTrue(any(row['specialization']=='service' for row in s.core.growth['cats'].values()))
        self.assertEqual(restore(checkpoint(s.core, set())).snapshot(), s.core.snapshot())

    def test_cli_log_and_resume(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--directory', self.temp.name, '--days', '1']), 0)
        paths = list(Path(self.temp.name).glob('*/cafe.json'))
        self.assertEqual(len(paths), 1)
        text = paths[0].with_name('autoplay.log').read_text(encoding='utf-8')
        self.assertIn('指定日数に到達', text)
        self.assertIn('疲労', text)
        with redirect_stdout(output):
            self.assertEqual(main(['--resume', str(paths[0]), '--days', '1']), 0)
        loaded = load_game(paths[0])[0]
        self.assertEqual(len(loaded.core.goal['days']), 2)

    def test_invalid_limits(self):
        s = self.session()
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                AutoPlayer(s, max_days=value)

    def test_cli_interrupt_finishes_operation_and_saves(self):
        s = self.session()
        original = signal.getsignal(signal.SIGINT)
        real_save = save_game

        def interrupt_after_operation(*args, **kwargs):
            result = real_save(*args, **kwargs)
            signal.raise_signal(signal.SIGINT)
            return result

        with redirect_stdout(io.StringIO()), patch(
                'cat_cafe_sim.storage.cafe_saves.save_game', side_effect=interrupt_after_operation):
            self.assertEqual(main(['--resume', str(s.checkpoint_path)]), 0)
        self.assertEqual(signal.getsignal(signal.SIGINT), original)
        loaded = load_game(s.checkpoint_path)[0]
        self.assertEqual(loaded.core.tick, 1)
        text = s.checkpoint_path.with_name('autoplay.log').read_text(encoding='utf-8')
        self.assertIn('中断', text)

    def test_fatigue_rest_and_day_off_count_as_days(self):
        from cat_cafe_sim.core.cafe_shifts import ShiftRules
        with patch('cat_cafe_sim.core.cafe_shifts.ShiftRules.load', return_value=ShiftRules(fatigue_per_service_tick=60)):
            s = self.session(target=250, days=10, stages=False, cat_ids=['a'])
        lines = []
        result = AutoPlayer(s, max_days=4, emit=lines.append).run()
        self.assertEqual(result.reason, 'day_limit')
        self.assertEqual(result.days, 4)
        self.assertTrue(any('全員休養のため休業' in line for line in lines))
        self.assertTrue(any(row.get('day_type')=='day_off' for row in s.core.day_results))
        save_game(s, s.checkpoint_path)
        self.assertEqual(load_game(s.checkpoint_path)[0].core.snapshot(), s.core.snapshot())
