import json
import tempfile
import unittest
from pathlib import Path
from cat_cafe_sim.content_texts import TextReader, DEFAULT_SCENES


class TextReaderTests(unittest.TestCase):
    def test_registered_partial_empty_and_corrupt_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = TextReader(Path(directory) / 'texts.json')
            self.assertEqual(reader.display('a', 'ミケ', 'play'),
                             ('ミケの様子をご覧ください。', DEFAULT_SCENES['play']))
            data = {'version': 1, 'cats': {'a': {'introduction': 'ミケの紹介',
                                               'scenes': {'play': '遊ぶミケ', 'sleep': '  '}}}}
            reader.path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(reader.display('a', 'ミケ', 'play'), ('ミケの紹介', '遊ぶミケ'))
            self.assertEqual(reader.display('a', 'ミケ', 'sleep')[1], DEFAULT_SCENES['sleep'])
            self.assertEqual(reader.display('b', 'タマ', 'play')[1], DEFAULT_SCENES['play'])
            for content in ('{bad', '{"version":2,"cats":{}}',
                            '{"version":1,"cats":{"a":{"introduction":3,"scenes":{}}}}'):
                reader.path.write_text(content, encoding='utf-8')
                self.assertEqual(reader.display('a', 'ミケ', 'play')[1], DEFAULT_SCENES['play'])
                self.assertEqual(reader.path.read_text(encoding='utf-8'), content)
            self.assertFalse(hasattr(reader, 'save'))
