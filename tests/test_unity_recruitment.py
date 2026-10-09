import copy
import tempfile
import unittest
from pathlib import Path
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import state_view
from tests.test_unity_dispatch_choices import api

class UnityRecruitmentTests(unittest.TestCase):
    def game(self,directory):
        rules=starting_conditions('free')
        for key in ('dispatch_unlocks','store_events','intake_request'):rules.pop(key)
        return create_game(Path(directory)/'source',rules)

    def test_projection_never_generates_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory)
            before=session.core.snapshot();files={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            view=state_view(session)['recruitment']
            self.assertTrue(view['can_refresh']);self.assertEqual(view['rows'],[])
            self.assertEqual(session.core.snapshot(),before)
            self.assertEqual(files,{p:p.read_bytes() for p in files})
            session.open_recruitment();before=session.core.snapshot()
            view=state_view(session)['recruitment']
            self.assertEqual(len(view['rows']),3);self.assertFalse(view['can_refresh'])
            self.assertTrue(all(r['can_purchase'] for r in view['rows']))
            self.assertEqual(session.core.snapshot(),before)
            self.assertEqual(view['rows'][0]['features'],session.core.recruitment['candidates'][view['rows'][0]['cat_id']]['features'])

    def test_http_receive_retry_and_save_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory)
            originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with api(session,Path(directory)/'saves') as (read,post):
                self.assertEqual(post('open_recruitment')[0],200)
                row=read()['recruitment']['rows'][0]
                reference=copy.deepcopy(session)
                from cat_cafe_sim.storage.cafe_saves import MemoryRelationships
                reference.store=MemoryRelationships(session.store._read());reference.recruit_cat(row['cat_id'])
                code,result,command=post('recruit_cat',cat_id=row['cat_id']);self.assertEqual(code,200)
                self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                self.assertEqual(post('recruit_cat',command)[0],200)
                self.assertEqual(post('recruit_cat',cat_id=row['cat_id'])[0],422)
                self.assertTrue(read()['recruitment']['rows'][0]['accepted'])
                remaining=[r for r in read()['recruitment']['rows'] if not r['accepted']]
                self.assertTrue(all(not r['can_purchase'] and '飼育スペース' in r['reason'] for r in remaining))
                saved=post('save_game')[1]['save_id'];post('load_game',save_id=saved)
                self.assertTrue(read()['recruitment']['rows'][0]['accepted'])
                self.assertEqual(post('recruit_cat')[0],400)
                self.assertEqual(post('open_recruitment',working_cats=['mike'])[0],422)
            self.assertEqual(originals,{p:p.read_bytes() for p in originals})

    def test_refresh_keeps_previous_candidates_and_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory);session.open_recruitment()
            previous=copy.deepcopy(session.core.recruitment['candidates'])
            for _ in range(3):session.day_off()
            self.assertTrue(state_view(session)['recruitment']['can_refresh'])
            self.assertEqual(len(session.core.recruitment['candidates']),3)
            session.open_recruitment()
            self.assertEqual(len(session.core.recruitment['candidates']),6)
            for key,row in previous.items():self.assertEqual(session.core.recruitment['candidates'][key],row)
            session.core.funds=200
            self.assertTrue(all(not r['can_purchase'] for r in state_view(session)['recruitment']['rows']))
            session.core.funds=1000
            session.automatic_step()
            view=state_view(session)['recruitment']
            self.assertFalse(view['can_refresh']);self.assertTrue(all(not r['can_purchase'] for r in view['rows']))

if __name__=='__main__':unittest.main()
