import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import load_presets
from cat_cafe_sim.storage.relationships import RelationshipStore, RelationshipConflict


class CatProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'relations.json'
        self.store = RelationshipStore(self.path)
        self.config = RelationshipConfig()
        self.personality = load_presets()['穏やかな甘えん坊']

    def test_registration_and_reunion_across_customers(self):
        self.store.register_cat('cat', 'ミケ', self.personality)
        before = self.path.read_bytes()
        self.store.register_cat('cat', 'ミケ', self.personality)
        self.assertEqual(self.path.read_bytes(), before)
        for guest in ('guest-1', 'guest-2'):
            core = self.store.begin(self.config, 'cat', guest)
            self.assertEqual(core.config.personality, self.personality)
            core.finish(); self.store.apply(core)
        self.assertEqual([row['cat_name'] for row in self.store.list_relationships()], ['ミケ', 'ミケ'])
        self.assertEqual(self.store.begin(self.config, 'another-cat', 'guest-1').config.personality,
                         self.config.personality)

    def test_legacy_read_and_registration_preserve_history(self):
        core = self.store.begin(self.config, 'cat', 'guest')
        core.step('direct'); core.finish(); self.store.apply(core)
        data = json.loads(self.path.read_text())
        del data['cats']; data['format_version'] = 1
        self.path.write_text(json.dumps(data))
        before = self.path.read_bytes()
        self.assertIsNone(self.store.cat_profile('cat'))
        self.assertEqual(self.store.list_relationships()[0]['cat_name'], 'cat')
        self.assertEqual(self.path.read_bytes(), before)
        self.store.register_cat('cat', 'ミケ', self.personality)
        updated = json.loads(self.path.read_text())
        self.assertEqual(updated['pairs'], data['pairs'])
        self.assertEqual(updated['applied'], data['applied'])
        self.assertEqual(self.store.snapshot('cat', 'guest')['affinity'], .5)
        before = self.path.read_bytes()
        self.store.apply(core)  # 過去の旧個性の結果の再試行も二重反映しない。
        self.assertEqual(self.path.read_bytes(), before)

    def test_conflicting_registration_or_inflight_personality_does_not_write(self):
        core = self.store.begin(self.config, 'cat', 'guest'); core.finish()
        self.store.register_cat('cat', 'ミケ', self.personality)
        before = self.path.read_bytes()
        with self.assertRaises(RelationshipConflict):
            self.store.register_cat('cat', '別名', self.personality)
        with self.assertRaises(RelationshipConflict):
            self.store.apply(core)
        self.assertEqual(self.path.read_bytes(), before)

    def test_registration_and_result_save_failure_are_atomic(self):
        with patch.object(self.store, '_write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                self.store.register_cat('cat', 'ミケ', self.personality)
        self.assertFalse(self.path.exists())
        core = self.store.begin(replace(self.config, personality=self.personality), 'cat', 'guest')
        core.finish()
        with patch('cat_cafe_sim.storage.relationships.os.replace', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                self.store.apply(core, cat_name='ミケ')
        self.assertFalse(self.path.exists())
        self.store.apply(core, cat_name='ミケ')
        self.assertEqual(self.store.cat_profile('cat')['name'], 'ミケ')

    def test_invalid_profile_rejected_without_overwrite(self):
        with self.assertRaises(ValueError):
            self.store.register_cat('cat', ' ', self.personality)
        self.assertFalse(self.path.exists())
        self.store.register_cat('cat', 'ミケ', self.personality)
        data = json.loads(self.path.read_text())
        data['cats']['cat']['personality']['type_preferences']['pet'] = 99
        self.path.write_text(json.dumps(data))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.begin(self.config, 'cat', 'guest')
        self.assertEqual(self.path.read_bytes(), before)
