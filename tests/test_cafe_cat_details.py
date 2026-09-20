import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_cat_details import cat_details, MISSING
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats


class CatDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relations.json')
        add_playtest_cats(self.store)
        self.session = CafeInteractionSession(store=self.store,
            cafe_config=replace(Config.load(), opening_ticks=4, arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(), ticks=2))
        self.ids = list(self.session.core.cats)

    def close_day(self):
        while not self.session.core.closed:self.session.automatic_step()

    def test_current_values_and_read_only_first_day(self):
        before = self.session.core.log()
        saved = self.store.path.read_bytes()
        a = cat_details(self.session, self.ids[0])
        b = cat_details(self.session, self.ids[1])
        self.assertNotEqual(a['basic'], b['basic'])
        self.assertEqual(a['history'], [])
        self.assertEqual(a['relationships'], [])
        self.assertEqual(self.session.core.log(), before)
        self.assertEqual(self.store.path.read_bytes(), saved)

    def test_unregistered_cat_uses_config_personality_without_creating_store(self):
        from cat_cafe_sim.core.human_cat_types import Personality
        store = RelationshipStore(Path(self.temp.name)/'new.json')
        personality = replace(Personality(), type_preferences=(1.5,)*8)
        session = CafeInteractionSession(store=store,
            interaction_config=replace(RelationshipConfig(), personality=personality))
        view = dict(cat_details(session, 'cat-1')['basic'])
        self.assertIn('未登録・営業の既定個性', view['個性'])
        self.assertEqual(view['好み：ねこじゃらし'], '1.5')
        self.assertFalse(store.path.exists())

    def test_days_rest_health_and_resume_preserve_rows(self):
        self.close_day()
        first = cat_details(self.session, self.ids[0])
        self.assertEqual(len(first['history']), 1)
        self.session.next_day()
        self.session.set_shifts([])
        self.session.day_off()
        before = cat_details(self.session, self.ids[0])
        self.assertEqual(before['history'][1][1:5], ('休業','休養','0','0'))
        self.assertEqual(dict(before['basic'])['担当状態'], '休養')
        path = Path(self.temp.name)/'save.json'
        save_game(self.session, path)
        loaded, _ = load_game(path)
        self.assertEqual(cat_details(loaded, self.ids[0]), before)
        loaded.core.cats[self.ids[0]].health_status = 'sick'
        loaded.core.cats[self.ids[0]].recovery_days_remaining = 2
        self.assertEqual(dict(cat_details(loaded,self.ids[0])['basic'])['体調'], '療養あと2日')

    def test_missing_old_fields_are_not_zero(self):
        self.close_day();self.session.next_day()
        row = self.session.core.day_results[0]['cats'][self.ids[0]]
        for key in ('service_ticks','interactions','fatigue_before','fatigue_after','health','shift'):
            row.pop(key, None)
        before = copy.deepcopy(self.session.core.day_results)
        history = cat_details(self.session,self.ids[0])['history'][0]
        self.assertEqual(history[2:5], (MISSING,MISSING,MISSING))
        self.assertEqual(history[6:8], (MISSING,MISSING))
        self.assertEqual(self.session.core.day_results, before)

    def test_pending_result_does_not_replace_saved_affinity(self):
        self.session.automatic_step();self.session.automatic_step()
        active = next(iter(self.session.active_interactions.values()))
        cat_id = active.cat_id
        self.assertEqual(dict(cat_details(self.session, cat_id)['basic'])['担当状態'], '交流中')
        with patch.object(self.store, 'apply', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.session.automatic_step()
        view = cat_details(self.session,cat_id)
        self.assertTrue(view['pending'])
        self.assertEqual(view['relationships'][0][1], '0')
        self.assertEqual(view['relationships'][0][3], '未交流')
        self.session.persist()
        view = cat_details(self.session,cat_id)
        self.assertFalse(view['pending'])
        self.assertEqual(view['relationships'][0][3], '交流済み')
