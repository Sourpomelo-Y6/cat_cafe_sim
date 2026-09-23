import copy
import unittest
from unittest.mock import patch
import test_cafe_goal as fixtures
from cat_cafe_sim.core.cafe_goal import rules, current_start, current_rules, next_rules, pending
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game
from cat_cafe_sim.cafe_goal_gui import progress


class GoalStagesTests(unittest.TestCase):
    setUp = fixtures.CafeGoalTests.setUp
    session = fixtures.CafeGoalTests.session
    close = fixtures.CafeGoalTests.close
    reload = fixtures.CafeGoalTests.reload
    rejected = fixtures.CafeGoalTests.rejected

    def start(self, seats=2):
        s = self.session(seats, stress_per_service_tick=0)
        s.enable_goal(dict(rules(), target=105, days=2, stages=[dict(target=110, days=2), dict(target=115, days=2)]))
        return s

    def test_three_stages_closed_transition_history_and_roundtrip(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                s = self.start(seats)
                for stage in range(3):
                    self.close(s)
                    self.assertTrue(pending(s.core))
                    self.assertEqual(s.core.goal['status'], 'cleared')
                    self.assertEqual(current_rules(s.core.goal)['target'], 105+stage*5)
                    self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
                    s = self.reload(s)
                    if stage < 2:
                        s.advance_goal()
                        self.assertEqual(current_start(s.core.goal), s.core.day+1)
                        self.assertEqual(s.core.summary()['goal_status'], 'cleared')
                        self.rejected(s, s.advance_goal)
                        s = self.reload(s)
                        s.next_day()
                self.assertIsNone(next_rules(s.core.goal))
                self.rejected(s, s.advance_goal)
                s.continue_goal()
                self.assertEqual(len(s.core.goal['history']), 2)
                s.next_day(); s.day_off()
                self.reload(s)

    def test_free_operation_delays_next_deadline_and_second_stage_expires(self):
        s = self.start(); self.close(s)
        s.continue_goal(); s.next_day(); s.day_off(); s.day_off()
        self.assertEqual(s.core.day, 4)
        self.assertEqual(s.core.goal['status'], 'cleared')
        s.advance_goal()
        self.assertEqual(current_start(s.core.goal), 4)
        self.assertIn('5日目まで', progress(s.core))
        s.day_off(); s = self.reload(s)
        s.day_off()
        self.assertEqual(s.core.goal['status'], 'expired')
        self.assertEqual(s.core.goal['resolved_day'], 5)
        self.rejected(s, s.advance_goal)
        self.rejected(s, s.day_off)
        s.continue_goal(); s.day_off()
        self.assertEqual(len(s.core.goal['history']), 1)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_next_stage_from_day_off_result_and_failed_save_retry(self):
        s = self.start()
        # Popularity already exceeds the first target, but settlement is at day end.
        # Generate that popularity through normal service, then postpone next stage.
        self.close(s); s.continue_goal(); s.next_day(); self.close(s)
        s.next_day(); s.advance_goal()
        s.day_off()
        self.assertEqual(s.core.goal['status'], 'cleared')
        self.assertEqual(s.core.day, 4)
        s.advance_goal()
        self.assertEqual(current_start(s.core.goal), 4)
        before = s.core.snapshot()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s, self.path)
        self.assertEqual(s.core.snapshot(), before)
        s = self.reload(s)
        self.rejected(s, s.advance_goal)

    def test_legacy_stays_single_stage_and_bad_history_is_rejected(self):
        legacy = self.session(); legacy.enable_goal(dict(rules(), target=105))
        self.close(legacy); legacy = self.reload(legacy)
        self.assertNotIn('history', legacy.core.goal)
        self.rejected(legacy, legacy.advance_goal)
        s = self.start(); self.close(s); s.advance_goal()
        data = checkpoint(s.core, set())
        for mutate in (
            lambda d: d['history'][0].update(status='expired'),
            lambda d: d['history'][0].update(resolved_day=2),
            lambda d: d.update(stage_started_day=1),
            lambda d: d['rules']['stages'][0].update(target=100),
            lambda d: d['history'].clear(),
        ):
            bad = copy.deepcopy(data); mutate(bad['state']['goal'])
            bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)

    def test_return_must_be_confirmed_before_next_challenge(self):
        s = self.start(); s.dispatch('c'); self.close(s)
        self.rejected(s, s.advance_goal)
        s.resolve_activity('dispatch-1-c'); s.advance_goal()
        self.reload(s)

    def test_intake_request_on_same_preparation_day_does_not_deadlock(self):
        from cat_cafe_sim.core.cafe_intake_request import rules as intake_rules
        s = self.start()
        s.core.initialize_intake_request(dict(intake_rules(), day=4))
        self.close(s); s.continue_goal(); s.next_day()
        self.close(s); s.next_day(); s.advance_goal(); s.day_off()
        self.assertTrue(pending(s.core))
        s.advance_goal()
        s.resolve_intake_request('decline')
        self.reload(s)
