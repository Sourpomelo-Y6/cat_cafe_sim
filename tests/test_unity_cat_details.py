import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core.cafe_growth import description
from cat_cafe_sim.unity_state_server import make_server, state_view

class UnityCatDetailsTests(unittest.TestCase):
    def test_http_details_are_read_only_and_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source')
            original={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                def read():
                    with urlopen(f'http://127.0.0.1:{server.server_port}/state') as response: return json.load(response)
                try:
                    before=session.core.snapshot();first=read();self.assertEqual(first,read())
                    self.assertEqual(before,session.core.snapshot())
                    for cat in first['cats']:
                        self.assertEqual(cat['growth_details'],description(session.core,cat['cat_id']))
                        self.assertTrue(cat['health_label']);self.assertTrue(cat['activity_label'])
                    key=first['cats'][0]['cat_id'];session.core.cats[key].stamina=42;session.core.cats[key].fatigue=13
                    updated=next(cat for cat in read()['cats'] if cat['cat_id']==key)
                    self.assertEqual(updated['stamina'],42);self.assertEqual(updated['fatigue'],13)
                    self.assertEqual(original,{p:p.read_bytes() for p in original})
                finally: server.shutdown();thread.join()

    def test_learned_actions_and_progress(self):
        from test_cafe_second_group_type_mastery import SecondGroupTypeTests
        fixture=SecondGroupTypeTests();fixture.setUp()
        try:
            session,key=fixture.prepare();fixture.qualify(session,key)
            before=session.core.snapshot()
            cat=next(cat for cat in state_view(session)['cats'] if cat['cat_id']==key)
            self.assertIn('得意な交流',cat['growth_details']);self.assertIn('2つ目の分類',cat['growth_details'])
            self.assertEqual(cat['growth_details'],description(session.core,key));self.assertEqual(before,session.core.snapshot())
            session.resolve_growth_type_mastery(key,'brush')
            updated=next(cat for cat in state_view(session)['cats'] if cat['cat_id']==key)
            self.assertIn('ブラッシング',updated['growth_details'])
        finally: fixture.doCleanups()

    def test_unconfigured_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source');session.core.growth=None
            self.assertTrue(all(cat['growth_details']=='成長ルールは未導入です。' for cat in state_view(session)['cats']))
