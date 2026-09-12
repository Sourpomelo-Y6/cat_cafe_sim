import tempfile
import unittest
from pathlib import Path

from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.relationships import RelationshipStore


class RelationshipListTests(unittest.TestCase):
    def test_empty_list_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RelationshipStore(Path(directory) / 'relations.json')
            self.assertEqual(store.list_relationships(), [])
            self.assertFalse(store.path.exists())

    def test_latest_saved_result_pair_isolation_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RelationshipStore(Path(directory) / 'relations.json')
            first = store.begin(RelationshipConfig(), 'cat-b', 'guest-1')
            first.step('direct'); first.finish(); store.apply(first)
            second = store.begin(RelationshipConfig(), 'cat-b', 'guest-1')
            second.finish(); store.apply(second)
            other = store.begin(RelationshipConfig(), 'cat-a', 'guest-2')
            other.finish(); store.apply(other)
            store.apply(first)  # 再試行した過去の交流を直近扱いしない。
            before = store.path.read_bytes()
            rows = store.list_relationships()
            self.assertEqual([(r['cat_id'], r['customer_id']) for r in rows],
                             [('cat-a', 'guest-2'), ('cat-b', 'guest-1')])
            self.assertEqual(rows[1]['affinity'], .5)
            self.assertEqual(rows[1]['latest_result']['session_id'], second.session_id)
            self.assertEqual(rows[1]['latest_result']['affinity_delta'], 0)
            rows[1]['latest_result']['affinity_delta'] = 99
            self.assertEqual(store.list_relationships()[1]['latest_result']['affinity_delta'], 0)
            self.assertEqual(store.path.read_bytes(), before)

    def test_corrupt_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RelationshipStore(Path(directory) / 'relations.json')
            store.path.write_text('{invalid')
            with self.assertRaises(ValueError):
                store.list_relationships()
            self.assertEqual(store.path.read_text(), '{invalid')
