import json
import tempfile
import unittest
from pathlib import Path
from cat_cafe_sim.content_images import ImageRegistry

class ImageReaderTests(unittest.TestCase):
    def test_external_tool_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ImageRegistry(directory)
            self.assertIsNone(registry.image_path('cat-1', 'normal'))
            registry.path.write_text(json.dumps({'version': 1, 'cats': {'cat-1': {'normal': 'images/a.png'}}}), encoding='utf-8')
            self.assertEqual(registry.image_path('cat-1', 'normal'), Path(directory).resolve() / 'images/a.png')
            self.assertIsNone(registry.image_path('cat-2', 'normal'))
            self.assertFalse(hasattr(registry, 'register'))

    def test_invalid_and_external_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ImageRegistry(directory)
            for data in ('{invalid', json.dumps({'version': 1, 'cats': {'cat-1': {'normal': '../outside.png'}}})):
                registry.path.write_text(data, encoding='utf-8')
                with self.assertRaises(ValueError):
                    registry.read()
