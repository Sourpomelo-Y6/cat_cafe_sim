import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_autoplay_objectives import prepare as objective_prepare
from cat_cafe_sim.cafe_autoplay_patron import roles, dispatch_reason, prepare
from cat_cafe_sim.cafe_autoplay_staffing import plan
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import load_game, save_game


class PatronAutoPlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conditions = starting_conditions('patron')
        self.conditions['store_events']['probability'] = 0
        self.conditions.pop('intake_request')
        self.session = create_game(self.temp.name, self.conditions)
        self.core = self.session.core

    def train(self):
        self.core.growth['cats']['cat-sora'].update(specialization='service', selected_day=1)

    def test_roles_and_forecast_are_readonly(self):
        before = copy.deepcopy(self.core.snapshot())
        stored = self.session.store.path.read_bytes()
        self.assertEqual(roles(self.core), (['cat-sora'], []))
        player = AutoPlayer(self.session, objective='patron', mode='clear')
        label, _ = prepare(player)
        self.assertIn('有力者', label)
        self.assertEqual(self.core.snapshot(), before)
        self.assertEqual(self.session.store.path.read_bytes(), stored)
        self.assertTrue(any('接客育成' in row['reason'] for row in player.decisions))

    def test_white_trainee_stays_and_is_prioritized_within_safe_load(self):
        self.assertIn('育成', dispatch_reason(self.core, 'cat-sora'))
        self.core.cats['cat-sora'].fatigue = 10
        staffing = plan(self.session, priority=['cat-sora'])
        self.assertEqual(staffing['workers'][0], 'cat-sora')
        self.core.cats['cat-sora'].fatigue = 60
        self.assertNotIn('cat-sora', plan(self.session, priority=['cat-sora'])['workers'])

    def test_trained_cat_rests_until_strict_member_is_satisfied(self):
        self.train()
        self.assertEqual(roles(self.core), ([], ['cat-sora']))
        self.assertFalse(dispatch_reason(self.core, 'cat-sora'))
        player = AutoPlayer(self.session, objective='patron', mode='clear')
        _, action = prepare(player)
        action()
        self.assertNotIn('cat-sora', self.core.working_cats)
        self.assertTrue(any(row['subject']=='cat-sora' and '派遣役' in row['reason'] for row in player.decisions))
        self.core.patron['members']['patron_strict_visit'] = 100
        self.assertEqual(roles(self.core), ([], []))

    def test_adopted_white_cat_is_not_a_training_or_dispatch_role(self):
        self.train()
        with patch.object(self.core, 'activity', side_effect=lambda key: 'adopted' if key=='cat-sora' else 'cafe'):
            self.assertEqual(roles(self.core), ([], []))

    def test_dispatch_stress_boundary_and_old_one_member_goal(self):
        self.core.management['stress']['cat-kohaku'] = 60
        self.assertFalse(dispatch_reason(self.core, 'cat-kohaku'))
        self.core.management['stress']['cat-kohaku'] = 60.1
        self.assertIn('休養', dispatch_reason(self.core, 'cat-kohaku'))
        self.core.patron['rules'].pop('members')
        self.core.patron.pop('members')
        self.assertEqual(roles(self.core), ([], []))
        self.assertFalse(dispatch_reason(self.core, 'cat-sora'))

    def test_dispatch_selection_does_not_take_trainee(self):
        self.core.patron['satisfaction'] = 100
        player = AutoPlayer(self.session, objective='patron', mode='clear')
        _, action = objective_prepare(player)
        action()
        event = next(iter(self.core.activities['events'].values()))
        self.assertNotEqual(event['cat_id'], 'cat-sora')
        self.assertEqual(event['patron_match']['gain'], 2)

    def test_clear_and_fast_rest_when_concentration_would_exceed_limit(self):
        for mode in ['clear', 'fast']:
            for cat in self.core.cats.values():
                cat.fatigue = 60
            player = AutoPlayer(self.session, objective='patron', mode=mode)
            label, action = prepare(player)
            self.assertIn('休業', label)
            self.assertEqual(action, self.session.day_off)
            self.assertTrue(all(row['choice']!='出勤' for row in player.decisions))

    def test_basic_does_not_use_patron_training_or_prediction(self):
        player = AutoPlayer(self.session, objective='patron', mode='basic')
        with patch('cat_cafe_sim.cafe_autoplay_patron.prepare', side_effect=AssertionError('basic')):
            self.assertTrue(player.step())
        self.assertFalse(self.core.activities and self.core.activities['events'])
        self.assertTrue(all('育成' not in row['reason'] for row in player.decisions))

    def test_accepted_reservation_keeps_business_open_without_unsafe_workers(self):
        for cat in self.core.cats.values():
            cat.fatigue = 60
        player = AutoPlayer(self.session, objective='patron', mode='clear')
        with patch('cat_cafe_sim.core.cafe_reservation.day_off_reason', return_value='予約あり'):
            _, action = prepare(player)
            action()
            self.assertEqual(self.core.working_cats, set())
            _, action = prepare(player)
            self.assertEqual(action, self.session.automatic_step)

    def test_short_three_member_run_save_resume_and_replay(self):
        selected = copy.deepcopy(self.conditions)
        selected['growth']['threshold'] = 1
        selected['patron']['target'] = 25
        selected['patron']['members'][0]['target'] = 2
        selected['patron']['members'][1]['target'] = 25
        s = create_game(Path(self.temp.name)/'short', selected)
        player = AutoPlayer(s, objective='patron', mode='clear')
        self.assertTrue(player.step())
        self.assertTrue(player.step())
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        result = AutoPlayer(loaded, objective='patron', mode='clear', max_days=30).run()
        self.assertEqual(result.reason, 'completed')
        self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(), loaded.core.snapshot())
        self.assertEqual(len(loaded.core.cats), 5)
        self.assertEqual(len(loaded.core.seats), 2)
