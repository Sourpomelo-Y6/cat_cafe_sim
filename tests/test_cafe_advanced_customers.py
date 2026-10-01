import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_customers import directory, cat_rows
from cat_cafe_sim.core.cafe_advanced_customers import CUSTOMER_ID, evaluate, unlocked_day, rules
from cat_cafe_sim.core.cafe_weekdays import schedule
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest, outcome_result
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class AdvancedCustomerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def create(self, mode='popularity', seats=2, legacy=False):
        selected = starting_conditions(mode)
        selected.pop('intake_request')
        selected['seat_count'] = seats
        selected['goal']['target'] = 105
        # 客層の解放・未達を調べる短期ゲーム。標準期限には依存しない。
        selected['goal']['days'] = 10
        if legacy:
            selected.pop('advanced_customers')
        return create_game(Path(self.temp.name) / 'games', selected)

    def unlock(self, s, advance=False):
        while not s.core.closed:
            s.automatic_step()
        self.assertEqual(s.core.goal['status'], 'cleared')
        self.assertEqual(unlocked_day(s.core), 1)
        (s.advance_goal if advance else s.continue_goal)()
        s.next_day()

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(s.core.snapshot(), loaded.core.snapshot())
        return loaded

    def serve(self, s, cat, finish=False):
        s.step()
        s.start(CUSTOMER_ID, cat)
        s = self.reload(s)
        if finish:
            s.finish()
        else:
            while s.active_interactions:
                active = next(iter(s.active_interactions.values()))
                s.step(*s.policy.choose(active.observation(), active.valid_actions()))
        result = outcome_result(list(s.core.outcomes.values())[-1])
        return s, result

    def test_unlock_tomorrow_history_preview_day_off_and_replay(self):
        s = self.create()
        before = s.core.snapshot()
        row = next(r for r in directory(s) if r['customer_id'] == CUSTOMER_ID)
        self.assertIn('未解放', row['status'])
        self.assertIsNone(row['arrival_tick'])
        self.assertEqual(row['preference'], 'white')
        self.assertTrue(next(r for r in cat_rows(s, CUSTOMER_ID) if r['cat_id'] == 'cat-sora')['matches'])
        self.assertEqual(s.core.snapshot(), before)
        while not s.core.closed:
            s.automatic_step()
        self.assertNotIn(CUSTOMER_ID, s.core.visits)
        self.assertNotIn(CUSTOMER_ID, schedule(s.core))
        self.assertIn(CUSTOMER_ID, schedule(s.core, 2))
        s = self.reload(s)
        s.advance_goal(); s.next_day(); s.day_off()
        self.assertEqual(unlocked_day(s.core), 1)
        self.assertEqual(s.core.day_results[-1]['customer_visits'], [])
        self.assertIn(CUSTOMER_ID, schedule(s.core))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)
        # 解放は現在人気ではなく達成履歴に従う（判定だけの検証）。
        lowered = copy.deepcopy(s.core)
        lowered.management['popularity'] = 50
        self.assertIn(CUSTOMER_ID, schedule(lowered))

    def test_success_with_recruited_white_cat_single_and_multi_seat(self):
        for seats in (1, 2):
            s = self.create(seats=seats); self.unlock(s)
            s.open_recruitment(); cat = next(iter(s.core.recruitment['candidates']))
            s.recruit_cat(cat); s.set_shifts([cat])
            s, result = self.serve(s, cat)
            self.assertTrue(evaluate(s.core, result)['success'])
            visit = s.core.visits[CUSTOMER_ID]
            from cat_cafe_sim.core.cafe_customer_satisfaction import evaluate as satisfaction
            satisfaction_bonus = satisfaction(s.core, result, evaluate(s.core, result))['bonus']
            self.assertEqual(visit.bill, visit.seated_ticks*s.core.config.time_price + result['bonus_funds'] + 100 + satisfaction_bonus)
            event = next(e for e in s.core.events if e['kind'] == 'advanced_customer_result')
            self.assertIn('達成', event['text'])
            self.assertIn('追加料金 100', event['text'])
            funds = s.core.funds
            s.finish(); self.assertEqual(s.core.funds, funds)
            with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
                with self.assertRaises(OSError):
                    save_game(s, s.checkpoint_path)
            s = self.reload(s)
            bad = checkpoint(s.core, set())
            bad['state']['advanced_customers']['bonus'] += 1
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
            while not s.core.closed:
                s.step()
            s.next_day()
            self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_automatic_assignment_uses_required_white_cat(self):
        s=self.create();self.unlock(s);s.automatic_step();s.automatic_step()
        assignment=next(e for e in s.core.events
                        if e['kind']=='automatic_assignment' and e['customer_id']==CUSTOMER_ID)
        self.assertEqual(assignment['cat_id'],'cat-sora')
        self.assertTrue(assignment['matched'])

    def test_unmet_conditions_and_unserved_no_extra_charge(self):
        for cat, finish in (('cat-mike', False), ('cat-sora', True)):
            s = self.create(); self.unlock(s)
            s, result = self.serve(s, cat, finish)
            evaluation = evaluate(s.core, result)
            self.assertFalse(evaluation['success'])
            if cat == 'cat-mike':
                self.assertGreaterEqual(result['connect_count'], 1)
                self.assertFalse(evaluation['matched'])
            else:
                self.assertTrue(evaluation['matched'])
                self.assertEqual(result['connect_count'], 0)
            visit = s.core.visits[CUSTOMER_ID]
            from cat_cafe_sim.core.cafe_customer_satisfaction import evaluate as satisfaction
            satisfaction_bonus = satisfaction(s.core, result, evaluation)['bonus']
            self.assertEqual(visit.bill, visit.seated_ticks*s.core.config.time_price + result['bonus_funds'] + satisfaction_bonus)
            self.reload(s)
        s = self.create(); self.unlock(s)
        while not s.core.closed:
            s.step()
        self.assertEqual(s.core.visits[CUSTOMER_ID].bill, 0)
        self.assertFalse(any(e['kind'] == 'advanced_customer_result' for e in s.core.events))
        self.reload(s)

    def test_other_modes_legacy_and_expiry_do_not_unlock(self):
        for mode in ('patron', 'bond', 'free'):
            s = self.create(mode)
            self.assertIsNone(s.core.advanced_customers)
            self.assertNotIn(CUSTOMER_ID, schedule(s.core, 100))
            self.reload(s)
        s = self.create(legacy=True)
        while not s.core.closed:
            s.automatic_step()
        self.assertEqual(s.core.goal['status'], 'cleared')
        self.assertNotIn('advanced_customers', self.reload(s).core.snapshot())
        self.assertNotIn(CUSTOMER_ID, schedule(s.core, 2))
        s = self.create()
        for _ in range(s.core.goal['rules']['days']):
            s.day_off()
        self.assertEqual(s.core.goal['status'], 'expired')
        self.assertIsNone(unlocked_day(s.core))
        self.reload(s)

    def test_invalid_rules_and_corrupt_unlock_history(self):
        for change in (dict(feature='black'), dict(connect_count=0), dict(connect_count=True),
                       dict(bonus=-1), dict(bonus=float('nan'))):
            with self.assertRaises(ValueError):
                rules(dict(rules(), **change))
        s = self.create(); self.unlock(s); s.step()
        source = checkpoint(s.core, set())
        for change in ('missing', 'early', 'preference'):
            bad = copy.deepcopy(source)
            if change == 'missing':
                del bad['state']['advanced_customers']
            elif change == 'early':
                bad['state']['goal']['resolved_day'] = 2
            else:
                bad['state']['customer_preferences']['customers'][CUSTOMER_ID] = 'black'
            bad['digest'] = digest({k:v for k,v in bad.items() if k != 'digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        with patch('cat_cafe_sim.core.cafe_advanced_customers.rules', side_effect=lambda value=None: rules(value) if value is not None else self.fail('設定の再読込')):
            self.reload(s)
