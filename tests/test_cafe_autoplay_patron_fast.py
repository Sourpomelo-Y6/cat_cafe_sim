import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_autoplay import AutoPlayer
from cat_cafe_sim.cafe_autoplay_objectives import prepare as objective_prepare
from cat_cafe_sim.cafe_autoplay_patron import recruit_for_conditions, matching_wait_cat, prepare
from cat_cafe_sim.cafe_autoplay_strategy import reserve
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core import cafe_patron
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class FastPatronTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conditions = starting_conditions('patron')
        self.conditions['store_events']['probability'] = 0
        self.conditions.pop('intake_request')
        self.session = create_game(self.temp.name, self.conditions)

    @property
    def core(self):
        return self.session.core

    def player(self, mode='fast', session=None):
        return AutoPlayer(session or self.session, objective='patron', mode=mode)

    def black_cat(self):
        self.session.open_recruitment()
        key = next(key for key, row in self.core.recruitment['candidates'].items() if 'black' in row.get('features', []))
        self.session.recruit_cat(key)
        return key

    def black_request(self):
        destination = cafe_patron.destinations(self.core)[1]
        self.core.patron['rules']['members'][0]['conditions'] = [{'feature': 'black'}]
        return destination

    def test_only_fast_recruits_missing_feature_through_normal_operations(self):
        player = self.player()
        before = copy.deepcopy(self.core.snapshot())
        stored = self.session.store.path.read_bytes()
        _, action = objective_prepare(player)
        self.assertEqual(self.core.snapshot(), before)
        self.assertEqual(self.session.store.path.read_bytes(), stored)
        action()
        _, action = objective_prepare(player)
        action()
        self.assertEqual(len(self.core.cats), 6)
        self.assertTrue(any('black' in features for features in self.core.cat_features.values()))
        self.assertEqual(self.core.funds, 800)
        self.assertGreaterEqual(self.core.funds, reserve(self.core))
        self.assertTrue(any(row['choice']=='受け入れ' for row in player.decisions))
        self.assertIsNone(recruit_for_conditions(player))
        self.assertEqual(verify_cafe_interaction(self.core.log()).snapshot(), self.core.snapshot())

    def test_budget_capacity_and_unavailable_catalog_do_not_force_recruitment(self):
        self.session.open_recruitment()
        player = self.player()
        self.core.funds = reserve(self.core)+199
        self.assertIsNone(recruit_for_conditions(player))
        self.core.funds += 1
        self.assertIsNotNone(recruit_for_conditions(player))
        with patch('cat_cafe_sim.core.cafe_housing.admission_reason', return_value='満員'):
            self.assertIsNone(recruit_for_conditions(player))
        for candidate in self.core.recruitment['candidates'].values():
            candidate['features'] = ['calico']
        self.assertIsNone(recruit_for_conditions(player))
        # 掲載候補に一致がなければ、通常の派遣へ戻れる。
        self.assertIsNotNone(objective_prepare(player))

    def test_adopted_cat_does_not_cover_missing_feature(self):
        key = self.black_cat()
        with patch.object(self.core, 'activity', side_effect=lambda cat: 'adopted' if cat==key else 'cafe'):
            self.assertIsNone(recruit_for_conditions(self.player()))  # 候補の黒猫は受け入れ済みで再加入しない。
            self.assertIsNone(matching_wait_cat(self.core, self.black_request()))

    def test_unavailable_match_waits_and_rests_in_fast_but_clear_uses_low_gain(self):
        key = self.black_cat()
        destination = self.black_request()
        self.core.patron['satisfaction'] = 100
        self.core.cats[key].fatigue = 41
        before = copy.deepcopy(self.core.snapshot())
        self.assertEqual(matching_wait_cat(self.core, destination), key)
        self.assertIsNone(objective_prepare(self.player()))
        player = self.player()
        _, action = prepare(player)
        self.assertEqual(self.core.snapshot(), before)
        self.assertTrue(any(row['subject']==key and row['choice']=='休養' and '希望に一致' in row['reason'] for row in player.decisions))
        action()
        self.assertNotIn(key, self.core.working_cats)
        clear = self.player('clear')
        _, action = objective_prepare(clear)
        action()
        event = next(iter(self.core.activities['events'].values()))
        self.assertEqual(event['patron_match']['gain'], 2)
        self.assertNotEqual(event['cat_id'], key)

    def test_fatigue_and_stress_boundaries_accept_matched_cat(self):
        key = self.black_cat()
        destination = self.black_request()
        self.core.patron['satisfaction'] = 100
        self.core.cats[key].fatigue = destination['max_fatigue']
        self.core.management['stress'][key] = 60
        self.assertIsNone(matching_wait_cat(self.core, destination))
        _, action = objective_prepare(self.player())
        action()
        event = next(iter(self.core.activities['events'].values()))
        self.assertEqual(event['cat_id'], key)
        self.assertTrue(event['patron_match']['matched'])

    def test_permanent_trait_mismatch_is_not_treated_as_rest_wait(self):
        key = self.black_cat()
        destination = self.black_request()
        destination.update(required_trait='hospitality', required_trait_name='接客好き')
        self.assertNotEqual(self.core.traits[key]['id'], 'hospitality')
        self.assertIsNone(matching_wait_cat(self.core, destination))

    def test_waiting_match_does_not_block_other_member_dispatch(self):
        key = self.black_cat()
        self.black_request()
        self.core.patron['satisfaction'] = 100
        self.core.cats[key].fatigue = 41
        self.core.growth['cats']['cat-sora'].update(specialization='service', selected_day=1)
        player = self.player()
        _, action = objective_prepare(player)
        action()
        event = next(iter(self.core.activities['events'].values()))
        self.assertEqual(event['destination']['id'], 'patron_strict_visit')
        self.assertTrue(event['patron_match']['matched'])
        self.assertTrue(any(row['choice']=='派遣待ち' for row in player.decisions))

    def test_trainee_and_missing_feature_fall_back_instead_of_waiting_forever(self):
        destination = cafe_patron.destinations(self.core)[1]
        self.assertIsNone(matching_wait_cat(self.core, destination))
        self.assertIsNone(matching_wait_cat(self.core, self.black_request()))
        self.core.patron['satisfaction'] = 100
        self.core.funds = reserve(self.core)
        _, action = objective_prepare(self.player())
        action()
        event = next(iter(self.core.activities['events'].values()))
        self.assertEqual(event['patron_match']['gain'], 2)

    def test_completed_members_and_legacy_one_member_need_no_recruitment(self):
        self.core.patron['members'] = dict.fromkeys(self.core.patron['members'], 100)
        self.assertIsNone(recruit_for_conditions(self.player()))
        self.core.patron['rules'].pop('members')
        self.core.patron.pop('members')
        for mode in ('clear', 'fast'):
            self.assertIsNone(recruit_for_conditions(self.player(mode)))
            label, _ = objective_prepare(self.player(mode))
            self.assertIn('派遣', label)
        self.assertIsNone(self.core.recruitment)

    def test_no_new_dispatch_during_a_visit_and_basic_and_clear_keep_original_path(self):
        for mode in ('basic', 'clear'):
            with patch('cat_cafe_sim.cafe_autoplay_patron.recruit_for_conditions', side_effect=AssertionError('変更外')):
                decision = objective_prepare(self.player(mode))
                if mode == 'basic':
                    self.assertIsNone(decision)
                else:
                    self.assertIsNotNone(decision)
        _, action = objective_prepare(self.player('clear'))
        action()
        self.black_cat()
        self.assertIsNone(objective_prepare(self.player()))
        self.assertEqual(len(self.core.activities['events']), 1)

    def test_short_goal_cancel_save_resume_and_detailed_replay(self):
        conditions = copy.deepcopy(self.conditions)
        conditions['growth']['threshold'] = 1
        conditions['patron']['target'] = 25
        for member in conditions['patron']['members']:
            member['target'] = member['gain']
        direct = create_game(Path(self.temp.name)/'short', conditions)
        player = self.player(session=direct)
        player.step()  # 候補確認
        player.step()  # 受け入れ
        player.step()  # 派遣
        player.cancel()
        self.assertEqual(player.run().reason, 'cancelled')
        save_game(direct, direct.checkpoint_path)
        loaded, _ = load_game(direct.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), direct.core.snapshot())
        offset = len(direct.core.operations)
        baseline = direct.store.path.read_bytes()
        ids = [f'patron-resume-{i}' for i in range(1000)]
        with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
            result = self.player(session=direct).run()
        expected = copy.deepcopy(direct.core.snapshot())
        self.assertEqual(result.reason, 'completed')
        self.assertEqual(verify_cafe_interaction(direct.core.log()).snapshot(), expected)
        # 同じ保存地点から再開する前に、このテスト専用の関係ファイルも戻す。
        direct.store.path.write_bytes(baseline)
        loaded, _ = load_game(direct.checkpoint_path)
        with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
            resumed = self.player(session=loaded).run()
        self.assertEqual(resumed, result)
        self.assertEqual(loaded.core.snapshot(), expected)
        self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(), expected)
        self.assertGreater(len(loaded.core.operations), offset)
        save_game(loaded, loaded.checkpoint_path)
        restored, _ = load_game(loaded.checkpoint_path)
        self.assertEqual(restored.core.snapshot(), loaded.core.snapshot())
        self.assertEqual(len(loaded.core.cats), 6)
