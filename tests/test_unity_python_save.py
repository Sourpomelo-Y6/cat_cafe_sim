import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from contextlib import contextmanager
from unittest.mock import patch
import test_cafe_management as fixtures
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.storage.cafe_saves import save_game,load_game
from cat_cafe_sim.unity_state_server import make_server,objective_start_view


@contextmanager
def server_api(session,root):
    with make_server(session,0,root) as server:
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base=f'http://127.0.0.1:{server.server_port}'
        def request(route,command=None):
            try:
                req=Request(base+route,json.dumps(command).encode() if command is not None else None,{'Content-Type':'application/json'})
                with urlopen(req,timeout=30) as r:return r.status,json.load(r)
            except HTTPError as ex:return ex.code,json.load(ex)
        def read():return request('/state')[1]
        def post(kind,command=None,**fields):
            state=read()
            if command is None:
                command=dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[])
                command.update(fields)
            code,data=request('/commands',command);return code,data,command
        def preview(path):return request('/python-save?'+urlencode({'path':str(path)}))
        try:yield read,post,preview
        finally:server.shutdown();worker.join()


class UnityPythonSaveTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ManagementTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.root=Path(self.fixture.temp.name)
    def legacy(self,version=2,phase='preparation'):
        s=self.fixture.session(initial_funds=500)
        if version==1:
            from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
            from cat_cafe_sim.cafe_interaction import CafeInteractionSession
            core=MultiSeatCafeCore(s.core.config,cat_ids=list(s.core.cats))
            s=CafeInteractionSession(core=core,store=self.fixture.store,interaction_config=s.interaction_config)
        if phase!='preparation':
            s.automatic_step()
            if phase=='closed':self.fixture.close(s)
        path=self.root/f'旧 営業 {version} {phase}.json'
        if version==2:save_game(s,path,auto_assign=False)
        else:
            path.write_text(json.dumps(dict(kind='cafe-save',format_version=1,core=s.core.log(),interaction_config=s.interaction_config.to_dict(),relationship_path=str(s.store.path.resolve()),relationships=s.store._read(),policy_version=s.policy.version,auto_assign=False)),encoding='utf-8')
        return s,path
    def test_preview_import_all_formats_phases_retry_and_separate_save(self):
        for version,phase in [(1,'preparation'),(2,'preparation'),(2,'open'),(2,'closed')]:
            with self.subTest(version=version,phase=phase):
                old,path=self.legacy(version,phase);expected=load_game(path)[0].core.snapshot();originals={p:p.read_bytes() for p in [path,self.fixture.store.path]}
                current=create_game(self.root/f'current-{version}-{phase}',starting_conditions('free'))
                with server_api(current,self.root/f'unity-{version}-{phase}') as (read,post,preview):
                    before=read();code,row=preview(path);self.assertEqual(code,200,row);self.assertIn(f'資金：{old.core.funds:g}',row['details']);self.assertIn('経営ルール：未導入',row['details']);self.assertEqual(before,read());self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                    code,result,command=post('load_python_game',save_id=row['save_id']);self.assertEqual(code,200,result);self.assertEqual(expected,current.core.snapshot());self.assertEqual(post('load_python_game',command)[:2],(code,result));self.assertEqual(read(),result['state'])
                    if phase=='preparation' and version==2:self.assertEqual(post('start_objective',choice='management')[0],200)
                    elif phase=='open':
                        while not current.core.closed:self.assertEqual(post('advance_business')[0],200)
                    code,saved,_=post('save_game');self.assertEqual(code,200,saved);self.assertEqual(post('load_game',save_id=saved['save_id'])[0],200)
                self.assertEqual(originals,{p:p.read_bytes() for p in originals});self.assertEqual(load_game(self.root/f'unity-{version}-{phase}'/saved['save_id']/'cafe.json')[0].core.snapshot(),current.core.snapshot())
    def test_invalid_changed_missing_and_conflicting_files_do_not_replace_current(self):
        old,path=self.legacy();current=create_game(self.root/'current',starting_conditions('free'))
        with server_api(current,self.root/'unity') as (read,post,preview):
            before=read()
            for source in ['', 'relative.json',self.root/'missing.json',self.fixture.store.path]:self.assertEqual(preview(source)[0],422);self.assertEqual(before,read())
            for token in ['', 'unknown','../outside']:
                self.assertEqual(post('load_python_game',save_id=token)[0],422);self.assertEqual(before,read())
            row=preview(path)[1];self.assertEqual(post('load_python_game',save_id=row['save_id'],working_cats=['a'])[0],422);self.assertEqual(before,read())
            data=path.read_bytes();path.write_bytes(data+b'\n');self.assertEqual(post('load_python_game',save_id=row['save_id'])[0],422);self.assertEqual(before,read());path.write_bytes(data)
            row=preview(path)[1];relationship=self.fixture.store.path.read_bytes();self.fixture.store.register_cat('other','other',fixtures.Personality());self.assertEqual(post('load_python_game',save_id=row['save_id'])[0],422);self.assertEqual(before,read());self.fixture.store.path.write_bytes(relationship)
            def change_during_load(source):
                loaded=load_game(source)
                self.fixture.store.register_cat('race','race',fixtures.Personality())
                return loaded
            with patch('cat_cafe_sim.storage.cafe_saves.load_game',side_effect=change_during_load):
                self.assertEqual(preview(path)[0],422);self.assertEqual(before,read())
            self.fixture.store.path.write_bytes(relationship)
            # Relationship progression beyond the checkpoint must use the existing conflict check.
            row=preview(path)[1];old.automatic_step();old.automatic_step();self.assertEqual(preview(path)[0],422);self.assertEqual(post('load_python_game',save_id=row['save_id'])[0],422);self.assertEqual(before,read())
    def test_preview_revision_and_no_automatic_management_or_new_game_features(self):
        old,path=self.legacy();current=create_game(self.root/'current',starting_conditions('free'))
        with server_api(current,self.root/'unity') as (read,post,preview):
            row=preview(path)[1];state=read();stale=dict(kind='load_python_game',request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],save_id=row['save_id'])
            self.assertEqual(post('set_shifts',working_cats=[])[0],200);before=read();self.assertEqual(post('load_python_game',stale)[0],409);self.assertEqual(before,read())
            row=preview(path)[1];self.assertEqual(post('load_python_game',save_id=row['save_id'])[0],200);self.assertIsNone(current.core.management);self.assertIsNone(current.core.goal);self.assertIsNone(current.core.pet_shop)
    def test_management_matches_python_grant_rules_and_restrictions(self):
        for funds in (500,1500):
            s=self.fixture.session(initial_funds=funds);expected=copy.deepcopy(s);expected.enable_management();original=s.core.snapshot()
            view=objective_start_view(s);row=next(r for r in view['rows'] if r['choice']=='management');self.assertTrue(row['can_start']);self.assertIn(f'補充：{max(0,1000-funds)}',row['details']);self.assertIn('ゲームオーバー',row['details']);self.assertEqual(original,s.core.snapshot())
            with server_api(s,self.root/f'management-{funds}') as (read,post,preview):
                code,result,command=post('start_objective',choice='management');self.assertEqual(code,200,result);self.assertEqual(expected.core.snapshot(),s.core.snapshot());self.assertEqual(post('start_objective',command)[:2],(code,result));before=read();self.assertEqual(post('start_objective',choice='management')[0],422);self.assertEqual(before,read());self.assertTrue(next(r for r in read()['objective_start']['rows'] if r['choice']=='management')['started']);self.assertEqual(post('start_objective',choice='popularity')[0],200)
        for restriction in ('health','open','closed'):
            s=self.fixture.session()
            if restriction=='health':s.core.health_rules=None
            else:s.automatic_step()
            if restriction=='closed':self.fixture.close(s)
            original=s.core.snapshot();self.assertFalse(next(r for r in objective_start_view(s)['rows'] if r['choice']=='management')['can_start'])
            with server_api(s,self.root/restriction) as (read,post,preview):self.assertEqual(post('start_objective',choice='management')[0],422);self.assertEqual(original,s.core.snapshot())


if __name__=='__main__':unittest.main()
