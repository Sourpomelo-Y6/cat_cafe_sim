import copy
import unittest
from pathlib import Path
from unittest.mock import patch
import test_cafe_cat_details as fixtures
from test_unity_dispatch_choices import api
from cat_cafe_sim.unity_state_server import pending_results_view
from cat_cafe_sim.storage.cafe_saves import MemoryRelationships, save_game, load_game

class UnityPendingResultsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CatDetailsTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.s=self.fixture.session;self.root=Path(self.fixture.temp.name)
        self.s.automatic_step();self.s.automatic_step()
        with patch.object(self.s.store,'apply',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.s.automatic_step()
        self.assertTrue(self.s.pending)

    def test_projection_and_python_save_restore_read_only(self):
        s=self.s;before=copy.deepcopy(s.core.snapshot());raw=s.store.path.read_bytes()
        view=pending_results_view(s)
        self.assertEqual(view['count'],len(s.pending));self.assertEqual(view['reason'],'')
        self.assertIn('親しみ：',view['rows'][0]['details']);self.assertIn('会計・体力・報酬は反映済み',view['notes'])
        self.assertEqual(before,s.core.snapshot());self.assertEqual(raw,s.store.path.read_bytes())
        save_game(s,self.root/'pending.json');restored,_=load_game(self.root/'pending.json')
        self.assertEqual(view,pending_results_view(restored))

    def test_retry_failure_recovery_and_duplicate_request(self):
        s=self.s;original_path=s.store.path;raw=original_path.read_bytes();core=copy.deepcopy(s.core.snapshot())
        with api(s,self.root/'unity') as (read,post):
            before=copy.deepcopy(s.store._read());initial=read();pending=set(s.pending)
            self.assertEqual(post('advance_business')[0],422);self.assertEqual(post('save_game')[0],422)
            with patch.object(MemoryRelationships,'apply',side_effect=OSError('disk full')):
                code,failed,request=post('persist_retry');self.assertEqual(code,422)
                failed_state=read();self.assertEqual(failed_state['pending_results']['reason'],'disk full')
                self.assertGreater(failed_state['revision'],initial['revision'])
                self.assertEqual(post('persist_retry',request)[1],failed)
            self.assertEqual(core,s.core.snapshot());self.assertEqual(before,s.store._read());self.assertEqual(pending,s.pending)
            code,reply,request=post('persist_retry');self.assertEqual(code,200)
            after=copy.deepcopy(s.store._read());self.assertFalse(s.pending)
            self.assertEqual(reply['state']['pending_results']['count'],0)
            self.assertEqual(post('persist_retry',request)[1],reply);self.assertEqual(post('persist_retry')[0],422)
            self.assertEqual(after,s.store._read());self.assertEqual(raw,original_path.read_bytes())
            self.assertEqual(core,s.core.snapshot())
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200)
            self.assertEqual(read()['pending_results']['count'],0);self.assertEqual(after,s.store._read())

    def test_saved_receipts_are_skipped(self):
        s=self.s;s.persist();before=copy.deepcopy(s.store._read());s.persist()
        self.assertEqual(before,s.store._read());self.assertEqual(pending_results_view(s)['count'],0)
