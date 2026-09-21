import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class NewGameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'games'

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
        self.assertEqual(restored.core.funds, 1000)
        self.assertEqual(restored.core.day, 2)

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
