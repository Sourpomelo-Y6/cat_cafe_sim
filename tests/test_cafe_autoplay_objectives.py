import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_autoplay import AutoPlayer, main
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_player import state, active
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ObjectiveAutoPlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sequence = 0

    def game(self, objective, *, easy=True):
        self.sequence += 1
        selected = starting_conditions(objective)
        if easy:
            selected['patron'].pop('members', None)
            selected['bond'] = dict(target=1, affinity=.5)
            selected['patron']['target'] = 25
            selected['store_events']['probability'] = 0
            selected.pop('intake_request')
        return create_game(Path(self.temp.name)/str(self.sequence), selected)

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def replay(self, s):
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_bond_normal_six_cats_are_recruited_and_played_with(self):
        selected = starting_conditions('bond')
        selected['bond']['affinity'] = .5
        selected['store_events']['probability'] = 0
        selected.pop('intake_request')
        s = create_game(Path(self.temp.name)/'six', selected)
        decisions = []
        result = AutoPlayer(s, objective='bond', mode='clear', on_decision=decisions.append).run()
        self.assertEqual(result.reason, 'completed')
        self.assertEqual(len(s.core.bond_goal['achieved_cats']), 6)
        self.assertEqual(len(s.core.cats), 6)
        self.assertTrue(any(r['choice']=='受け入れ' for r in decisions))
        self.assertTrue(any(r['choice']=='交流' for r in decisions))
        self.assertEqual(s.core.objective, 'bond')
        self.assertTrue(s.core.goal['tracking_only'])
        self.replay(s)

    def test_patron_returns_score_and_stops_before_result_confirmation(self):
        s = self.game('patron')
        result = AutoPlayer(s, objective='patron', mode='clear').run()
        self.assertEqual(result.reason, 'completed')
        self.assertEqual(s.core.patron['status'], 'cleared')
        self.assertFalse(s.core.patron['continued'])
        self.assertIn('patron', s.core.clear_results)
        self.assertEqual(len(s.core.cats), 5)
        self.assertEqual(len(s.core.seats), 2)
        self.replay(s)

    def test_basic_keeps_non_intervention_and_native_targets_have_no_expiry(self):
        for objective in ('bond', 'patron'):
            s = self.game(objective)
            result = AutoPlayer(s, objective=objective, mode='basic', max_days=2).run()
            self.assertEqual(result.reason, 'day_limit')
            self.assertEqual(result.days, 2)
            target = s.core.bond_goal if objective=='bond' else s.core.patron
            self.assertEqual(target['status'], 'active')
            self.assertEqual(sum(state(s.core)['total'].values()), 0)
            self.assertEqual(len(s.core.cats), 5)
            self.replay(s)

    def test_resume_mid_player_interaction_matches_uninterrupted_operations(self):
        s = self.game('bond')
        player = AutoPlayer(s, objective='bond', mode='clear')
        self.assertTrue(player.step())
        self.assertTrue(active(s.core))
        self.assertTrue(player.step())
        operation_offset = len(s.core.operations)
        resumed = self.reload(s)
        resumed_offset = len(resumed.core.operations)
        result = player.run()
        resumed_result = AutoPlayer(resumed, objective='bond', mode='clear').run()
        self.assertEqual(resumed_result.reason, result.reason)
        self.assertEqual(resumed.core.operations[resumed_offset:], s.core.operations[operation_offset:])
        self.assertEqual(resumed.core.snapshot(), s.core.snapshot())
        self.replay(resumed)

    def test_resume_travelling_and_waiting_patron_returns(self):
        direct = self.game('patron')
        resumed = self.game('patron')
        a = AutoPlayer(direct, objective='patron', mode='clear')
        b = AutoPlayer(resumed, objective='patron', mode='clear')
        seen = set()
        while True:
            ids = [f'interaction-{a.operations}-{i}' for i in range(10)]
            with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                progressed = a.step()
            with patch('cat_cafe_sim.core.human_cat_relationship.uuid4', side_effect=ids):
                self.assertEqual(b.step(), progressed)
            if not progressed:
                break
            statuses = {e['status'] for e in (b.session.core.activities or {}).get('events', {}).values()}
            for status in ('travelling', 'waiting'):
                if status in statuses and status not in seen:
                    b.session = self.reload(b.session)
                    seen.add(status)
            self.assertEqual(a.session.core.snapshot(), b.session.core.snapshot())
        self.assertEqual(seen, {'travelling', 'waiting'})
        self.assertEqual(a.result, b.result)
        self.replay(b.session)

    def test_popularity_expiry_remains_separate_and_can_be_confirmed(self):
        for objective in ('bond', 'patron'):
            s = self.game(objective)
            from cat_cafe_sim.core.cafe_popularity_challenge import rules
            selected = rules(s.core)
            selected['goal']['days'] = 1
            s.start_popularity_challenge(selected)
            result = AutoPlayer(s, objective=objective, mode='basic').run()
            self.assertEqual(result.reason, 'expired')
            target = s.core.bond_goal if objective=='bond' else s.core.patron
            self.assertEqual(target['status'], 'active')
            self.assertNotIn(objective, s.core.clear_results)
            s = self.reload(s)
            s.continue_goal()
            result = AutoPlayer(s, objective=objective, mode='clear').run()
            self.assertEqual(result.reason, 'completed')
            self.assertEqual(s.core.goal['status'], 'expired')
            self.assertTrue(s.core.goal['continued'])
            self.replay(s)

    def test_popularity_first_stage_stops_without_losing_native_target(self):
        for objective in ('bond', 'patron'):
            s = self.game(objective)
            from cat_cafe_sim.core.cafe_popularity_challenge import rules
            selected = rules(s.core)
            selected['goal']['target'] = 105
            s.start_popularity_challenge(selected)
            result = AutoPlayer(s, objective=objective, mode='basic', stop_on_goal=True).run()
            self.assertEqual(result.reason, 'goal_cleared')
            target = s.core.bond_goal if objective=='bond' else s.core.patron
            self.assertEqual(target['status'], 'active')
            self.assertEqual(s.core.goal['status'], 'cleared')
            self.replay(s)

    def test_cancellation_limit_and_invalid_target_do_not_change_state(self):
        s = self.game('bond')
        for options, reason in ((dict(objective='bond'), 'cancelled'), (dict(objective='patron'), 'blocked')):
            player = AutoPlayer(s, **options)
            if reason=='cancelled':
                player.cancel()
            before = copy.deepcopy(s.core.snapshot())
            self.assertEqual(player.run().reason, reason)
            self.assertEqual(s.core.snapshot(), before)
        player = AutoPlayer(s, objective='bond', mode='clear', max_operations=1)
        player.step()
        before = copy.deepcopy(s.core.snapshot())
        self.assertEqual(player.run().reason, 'operation_limit')
        self.assertEqual(s.core.snapshot(), before)
        with self.assertRaises(ValueError):
            AutoPlayer(s, objective='free')

    def test_cli_objective_creation_and_resume(self):
        path = Path(self.temp.name)/'cli'
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['--objective','patron','--mode','clear','--max-operations','5','--directory',str(path)]), 0)
        checkpoint = Path(next(line.removeprefix('営業セーブ: ') for line in output.getvalue().splitlines() if line.startswith('営業セーブ: ')))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--objective','patron','--mode','clear','--max-operations','5','--resume',str(checkpoint)]), 0)
        restored, _ = load_game(checkpoint)
        self.assertEqual(restored.core.objective, 'patron')
        self.assertEqual(AutoPlayer(restored, objective='patron', mode='clear', max_days=1).run().reason, 'day_limit')
        self.replay(restored)

    def test_player_choice_is_readonly_and_works_for_all_initial_personalities(self):
        from dataclasses import replace
        from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction
        from cat_cafe_sim.core.human_cat_types import Personality
        from cat_cafe_sim.cafe_autoplay_objectives import player_action
        for profile in starting_conditions('bond')['profiles']['cats'].values():
            config = replace(RelationshipConfig.load(), ticks=10, personality=Personality.from_dict(profile['personality']))
            interaction = RelationshipInteraction(config)
            while not interaction.state['end_reason']:
                before = copy.deepcopy(interaction.log())
                action, target = player_action(interaction)
                self.assertEqual(interaction.log(), before)
                self.assertIn(action, interaction.valid_actions())
                interaction.step(action, target)
            self.assertGreater(interaction.result()['affinity_after'], 0, profile['name'])

    def test_final_popularity_confirmation_allows_native_goal_to_continue(self):
        s = self.game('bond')
        from cat_cafe_sim.core.cafe_popularity_challenge import rules
        selected = rules(s.core)
        selected['goal'].update(target=105, days=10, stages=[dict(target=110, days=10), dict(target=115, days=10)])
        s.start_popularity_challenge(selected)
        result = AutoPlayer(s, objective='bond', mode='basic', max_days=8).run()
        self.assertEqual(result.reason, 'day_limit')
        self.assertEqual(s.core.goal['status'], 'cleared')
        self.assertTrue(s.core.goal['continued'])
        self.assertEqual(len(s.core.goal['history']), 2)
        popularity_result = copy.deepcopy(s.core.clear_results['popularity'])
        result = AutoPlayer(s, objective='bond', mode='clear').run()
        self.assertEqual(result.reason, 'completed')
        self.assertEqual(s.core.clear_results['popularity'], popularity_result)
        self.assertEqual(set(s.core.clear_results), {'popularity', 'bond'})
        self.replay(s)

    def test_native_objective_game_over_has_priority(self):
        selected = starting_conditions('bond')
        selected['management']['starting_funds'] = 1
        selected['operating_cost']['base_cost'] = 100000
        selected['store_events']['probability'] = 0
        selected.pop('intake_request')
        s = create_game(Path(self.temp.name)/'bankrupt', selected)
        result = AutoPlayer(s, objective='bond', mode='basic').run()
        self.assertEqual(result.reason, 'game_over')
        self.assertEqual(s.core.bond_goal['status'], 'active')
        self.replay(s)
