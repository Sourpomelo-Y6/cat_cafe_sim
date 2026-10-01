from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class NewGameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'games'

    def test_start_timestamp_collision_and_failed_retry_preserve_existing_games(self):
        stamp = datetime(2026, 9, 30, 10, 30, 0)
        with patch('cat_cafe_sim.cafe_new_game.datetime') as clock:
            clock.now.return_value = stamp
            first = create_game(self.directory)
            second = create_game(self.directory)
            self.assertEqual(first.checkpoint_path.parent.name, '20260930103000')
            self.assertEqual(second.checkpoint_path.parent.name, '20260930103000_1')
            before = {p: p.read_bytes() for game in (first, second) for p in game.checkpoint_path.parent.iterdir()}
            with patch('cat_cafe_sim.cafe_new_game.save_game', side_effect=OSError('full')):
                with self.assertRaises(OSError):
                    create_game(self.directory)
            self.assertFalse((self.directory / '20260930103000_2').exists())
            third = create_game(self.directory)
            self.assertEqual(third.checkpoint_path.parent.name, '20260930103000_2')
            self.assertEqual(before, {p: p.read_bytes() for p in before})
        save_game(first, first.checkpoint_path)
        self.assertEqual(first.checkpoint_path.parent.name, '20260930103000')
        self.assertEqual(load_game(second.checkpoint_path)[0].core.snapshot(), second.core.snapshot())

    def test_timestamp_collision_with_existing_file_and_legacy_folder(self):
        self.directory.mkdir()
        (self.directory / '20260930103000').write_text('keep')
        with patch('cat_cafe_sim.cafe_new_game.datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 30, 10, 30, 0)
            session = create_game(self.directory)
        self.assertEqual(session.checkpoint_path.parent.name, '20260930103000_1')
        self.assertEqual((self.directory / '20260930103000').read_text(), 'keep')
        legacy = self.directory / 'game-existing'
        legacy.mkdir()
        save_game(session, legacy / 'cafe.json')
        original = {p: p.read_bytes() for p in legacy.iterdir()}
        loaded, _ = load_game(legacy / 'cafe.json')
        self.assertEqual(loaded.checkpoint_path.parent, legacy)
        self.assertEqual(original, {p: p.read_bytes() for p in legacy.iterdir()})

    def test_initial_conditions_and_initial_save_resume(self):
        session = create_game(self.directory)
        core = session.core
        self.assertEqual((core.day, core.tick, core.funds), (1, 0, 1000))
        self.assertEqual(core.management['popularity'], 100)
        self.assertEqual(len(core.cats), 5)
        self.assertEqual(len(core.seats), 2)
        self.assertIsNone(core.adoption)
        self.assertIsNone(core.recruitment)
        self.assertEqual(core.working_cats, set(core.cats))
        self.assertEqual(session.store.list_relationships(), [])
        self.assertTrue(all(c.stamina == core.config.max_stamina and c.health_status == 'healthy' and c.fatigue == 0 for c in core.cats.values()))
        self.assertEqual(verify_cafe_interaction(core.log()).snapshot(), core.snapshot())
        restored, auto = load_game(session.checkpoint_path)
        self.assertFalse(auto)
        self.assertEqual(restored.core.snapshot(), core.snapshot())
        restored.day_off()
        self.assertEqual(restored.core.funds, 940)
        self.assertEqual(restored.core.day_results[-1]['summary']['operating_cost'],60)
        self.assertEqual(restored.core.day, 2)

    def test_adopted_goal_rules_apply_to_new_games_and_later_challenges(self):
        expected = dict(days=20, target=250, cap=650, gain_per_success=5,
                        stages=[dict(days=20, target=450), dict(days=25, target=650)])
        for mode in ('popularity', 'free', 'bond', 'patron'):
            with self.subTest(mode=mode):
                session = create_game(self.directory/mode, starting_conditions(mode))
                session, _ = load_game(session.checkpoint_path)
                if mode != 'popularity':
                    session.day_off()
                    session.start_popularity_challenge()
                    self.assertEqual(session.core.goal['challenge_started_day'], 2)
                self.assertEqual(session.core.goal['rules'], expected)
                save_game(session, session.checkpoint_path)
                self.assertEqual(load_game(session.checkpoint_path)[0].core.snapshot(), session.core.snapshot())

    def test_legacy_goal_survives_load_stage_transition_and_replay(self):
        from cat_cafe_sim.cafe_autoplay import AutoPlayer
        selected = starting_conditions()
        expected = dict(days=10, target=150, cap=300, gain_per_success=5,
                        stages=[dict(days=10, target=225), dict(days=10, target=300)])
        selected['goal'] = expected
        session = create_game(self.directory, selected)
        before = session.checkpoint_path.read_bytes()
        session, _ = load_game(session.checkpoint_path)
        self.assertEqual(session.checkpoint_path.read_bytes(), before)
        self.assertEqual(session.core.goal['rules'], expected)
        result = AutoPlayer(session, mode='clear', stop_on_goal=True).run()
        self.assertEqual((result.reason, result.days), ('goal_cleared', 4))
        session.advance_goal()
        session.next_day()
        save_game(session, session.checkpoint_path)
        restored, _ = load_game(session.checkpoint_path)
        self.assertEqual(restored.core.goal['rules'], expected)
        self.assertEqual(restored.core.goal['stage_started_day'], 5)
        self.assertEqual(verify_cafe_interaction(restored.core.log()).snapshot(), restored.core.snapshot())

    def test_legacy_tracking_saves_start_old_challenge_in_all_other_modes(self):
        expected = dict(days=10, target=150, cap=300, gain_per_success=5,
                        stages=[dict(days=10, target=225), dict(days=10, target=300)])
        for mode in ('free', 'bond', 'patron'):
            with self.subTest(mode=mode):
                selected = starting_conditions(mode)
                selected['goal'] = expected
                session = create_game(self.directory/mode, selected)
                session.day_off()
                save_game(session, session.checkpoint_path)
                session, _ = load_game(session.checkpoint_path)
                before = session.core.snapshot()
                session.start_popularity_challenge()
                self.assertEqual(session.core.goal['rules'], expected)
                self.assertEqual(session.core.goal['challenge_started_day'], 2)
                self.assertEqual(session.core.goal['days'], before['goal']['days'])
                for key in before:
                    if key != 'goal':
                        self.assertEqual(session.core.snapshot()[key], before[key])
                save_game(session, session.checkpoint_path)
                loaded, _ = load_game(session.checkpoint_path)
                self.assertEqual(loaded.core.snapshot(), session.core.snapshot())
                self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(), loaded.core.snapshot())

    def test_new_game_does_not_inherit_or_change_previous_game(self):
        first = create_game(self.directory)
        first.open_recruitment()
        first.recruit_cat(next(iter(first.core.recruitment['candidates'])))
        while not first.core.closed:
            first.automatic_step()
        self.assertTrue(first.store.list_relationships())
        save_game(first, first.checkpoint_path)
        old_files = {p: p.read_bytes() for p in first.checkpoint_path.parent.iterdir()}
        second = create_game(self.directory)
        self.assertNotEqual(first.store.path, second.store.path)
        self.assertNotEqual(first.checkpoint_path, second.checkpoint_path)
        self.assertEqual(len(second.core.cats), 5)
        self.assertEqual(second.core.funds, 1000)
        self.assertEqual(second.store.list_relationships(), [])
        self.assertIsNone(second.core.player_bond)
        self.assertEqual(old_files, {p: p.read_bytes() for p in old_files})
        loaded, _ = load_game(first.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), first.core.snapshot())

    def test_failed_creation_preserves_previous_files(self):
        first = create_game(self.directory)
        old_files = {p: p.read_bytes() for p in first.checkpoint_path.parent.iterdir()}
        with patch('cat_cafe_sim.cafe_new_game.save_game', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                create_game(self.directory)
        self.assertEqual(old_files, {p: p.read_bytes() for p in old_files})
        self.assertEqual(load_game(first.checkpoint_path)[0].core.snapshot(), first.core.snapshot())
        self.assertEqual(list(self.directory.iterdir()), [first.checkpoint_path.parent])
        second = create_game(self.directory)
        self.assertEqual(second.core.funds, 1000)

    def test_legacy_save_resume_does_not_enable_management(self):
        store = RelationshipStore(Path(self.temp.name) / 'legacy_relations.json')
        old = CafeInteractionSession(store=store)
        path = Path(self.temp.name) / 'legacy.json'
        save_game(old, path)
        before = path.read_bytes()
        loaded, _ = load_game(path)
        self.assertIsNone(loaded.core.management)
        self.assertEqual(loaded.core.funds, 0)
        self.assertEqual(path.read_bytes(), before)

    def test_default_gui_opens_start_screen_but_explicit_relationships_keep_legacy_route(self):
        from cat_cafe_sim.cafe_interaction import main
        with patch('sys.argv', ['cafe', 'gui']), patch('tkinter.Tk') as root, \
                patch('cat_cafe_sim.cafe_start_gui.CafeStartWindow') as start, \
                patch('cat_cafe_sim.cafe_interaction.CafeInteractionSession') as session:
            main()
            start.assert_called_once_with(root.return_value)
            root.return_value.mainloop.assert_called_once()
            session.assert_not_called()
        with patch('sys.argv', ['cafe', 'gui', '--relationships', str(Path(self.temp.name)/'legacy.json')]), \
                patch('tkinter.Tk'), patch('cat_cafe_sim.cafe_start_gui.CafeStartWindow') as start, \
                patch('cat_cafe_sim.cafe_interaction_gui.CafeInteractionWindow') as window:
            main()
            start.assert_not_called()
            session = window.call_args.args[1]
            self.assertIsNone(session.core.management)
            self.assertEqual(session.core.funds, 0)
