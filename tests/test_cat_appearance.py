import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.storage.cafe_saves import load_game, save_game
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.core.human_cat_types import load_presets


class AppearanceTests(unittest.TestCase):
    def test_save_load_edit_and_interaction_preserve_appearance(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            session.set_cat_appearance('cat-tama', {'eye_color': '金色', 'markings': '白い胸、黒い背中'})
            path = Path(directory) / 'edited.json'
            save_game(session, path)
            restored, _ = load_game(path)
            self.assertEqual(restored.profiles['cat-tama']['appearance']['eye_color'], '金色')
            restored.set_cat_appearance('cat-tama', {'eye_color': '緑色'})
            save_game(restored, path)
            restored, _ = load_game(path)
            self.assertEqual(restored.profiles['cat-tama']['appearance']['eye_color'], '緑色')
            restored.set_cat_appearance('cat-tama', {'eye_color': '緑色', 'markings': '白い胸、黒い背中'})
            core = restored.store.begin(restored.interaction_config, 'cat-tama', 'appearance-test')
            core.finish()
            restored.store.apply(core)
            self.assertEqual(restored.store.cat_profile('cat-tama')['appearance']['markings'], '白い胸、黒い背中')

    def test_legacy_and_invalid_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RelationshipStore(Path(directory) / 'cats.json')
            store.register_cat('cat', '猫', load_presets()['中立'])
            before = store.path.read_bytes()
            self.assertNotIn('appearance', store.cat_profile('cat'))
            for value in ({'eye_color': 1}, {'unknown': ''}, {'body_type': 'a' * 1001}):
                with self.assertRaises(ValueError):
                    store.set_cat_appearance('cat', value)
                self.assertEqual(before, store.path.read_bytes())

    def test_starting_profiles_have_unset_appearance(self):
        for profile in starting_conditions()['profiles']['cats'].values():
            self.assertEqual(set(profile['appearance'].values()), {''})
