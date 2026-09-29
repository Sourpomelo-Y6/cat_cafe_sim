import unittest
from tests import test_cafe_dispatch_match as matching
from cat_cafe_sim.cafe_dispatch_results import result_rows,result_text
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.storage.cafe_saves import save_game,load_game

class DispatchResultsTests(unittest.TestCase):
    setUp=matching.DispatchMatchTests.setUp
    game=matching.DispatchMatchTests.game
    def test_result_and_cat_history_survive_save_without_changes(self):
        s=self.game();s.dispatch('cat-sora');s.day_off();s.resolve_activity('dispatch-1-cat-sora')
        event=s.core.activities['events']['dispatch-1-cat-sora'];before=s.core.log()
        rows=dict(result_rows(s.core,event))
        self.assertEqual(rows['基本報酬'],'100');self.assertEqual(rows['歓迎ボーナス'],'+20')
        self.assertEqual(rows['資金報酬合計'],'120');self.assertIn('一致',rows['歓迎する特徴'])
        self.assertIn('歓迎ボーナス',str(cat_events(s.core,'cat-sora')))
        self.assertEqual(s.core.log(),before)
        save_game(s,s.checkpoint_path);loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(result_text(loaded.core,loaded.core.activities['events'][event['id']]),result_text(s.core,event))
    def test_patron_actual_increase_is_capped(self):
        s=self.game('patron');s.core.patron['rules']['target']=28
        s.dispatch('cat-sora',s.core.patron['rules']['destination']);s.day_off();s.day_off();s.resolve_activity('dispatch-1-cat-sora')
        rows=dict(result_rows(s.core,s.core.activities['events']['dispatch-1-cat-sora']))
        self.assertEqual(rows['歓迎の追加満足度'],'5')
        self.assertEqual(rows['満足度の実増加'],'28（0 → 28 / 上限28）')
