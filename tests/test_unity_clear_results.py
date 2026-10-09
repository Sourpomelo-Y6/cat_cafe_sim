import copy
import json
import threading
import unittest
from urllib.request import Request, urlopen
import test_cafe_clear_results as fixtures
from cat_cafe_sim.unity_state_server import clear_results_view, make_server, state_view


class UnityClearResultsTests(unittest.TestCase):
    setUp=fixtures.ClearResultsTests.setUp
    create=fixtures.ClearResultsTests.create
    achieve_bond=fixtures.ClearResultsTests.achieve_bond

    def test_popularity_only_final_stage_and_frozen_record(self):
        session=self.create('popularity')
        self.assertEqual(clear_results_view(session)['rows'],[])
        while not session.core.closed:session.automatic_step()
        self.assertEqual(clear_results_view(session)['rows'],[])
        session.advance_goal();session.next_day();session.day_off()
        self.assertEqual(clear_results_view(session)['rows'],[])
        from cat_cafe_sim.core.cafe_reservation import waiting
        if waiting(session.core):session.resolve_reservation('decline')
        session.advance_goal();session.day_off()
        before=session.core.snapshot();view=clear_results_view(session)
        self.assertEqual(session.core.snapshot(),before)
        row=view['rows'][0];saved=session.core.clear_results['popularity']
        self.assertEqual(row['mode'],'popularity')
        for field,label in [('funds','所持金'),('popularity','店の人気'),('cats','在籍猫数'),('revenue','累計接客売上')]:
            self.assertIn(f"{label}：{saved[field]:g}",row['details'])
        session.continue_goal();session.day_off()
        self.assertEqual(clear_results_view(session)['rows'][0]['details'],row['details'])
        self.assertIn('確認済み',clear_results_view(session)['rows'][0]['notes'])

    def test_multiple_goals_legacy_and_non_clear(self):
        session=self.create('patron');key=next(iter(session.core.cats))
        session.dispatch(key,session.core.patron['rules']['destination']);session.day_off();session.day_off()
        session.resolve_activity(f'dispatch-1-{key}');session.continue_patron()
        session.enable_bond_goal(dict(target=1,affinity=.5));self.achieve_bond(session)
        rows=clear_results_view(session)['rows']
        self.assertEqual([r['mode'] for r in rows],['patron','bond'])
        self.assertIn('1 / 1匹',rows[1]['details'])
        before=session.core.snapshot();self.assertEqual(state_view(session)['clear_results']['rows'],rows);self.assertEqual(session.core.snapshot(),before)
        legacy=copy.deepcopy(session);legacy.core.clear_results=None;legacy.core.funds=9876
        legacy_rows=clear_results_view(legacy)['rows']
        for row in legacy_rows:
            self.assertIn('所持金：記録なし',row['details']);self.assertNotIn('9876',row['details']);self.assertIn('旧セーブ',row['notes'])
        session=self.create('popularity')
        for _ in range(session.core.goal['rules']['days']):session.day_off()
        self.assertEqual(session.core.goal['status'],'expired')
        self.assertEqual(clear_results_view(session)['rows'],[])

    def test_http_continue_save_load_and_new_game(self):
        session=self.create('bond');self.achieve_bond(session)
        files={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
        with make_server(session,0,self.directory/'saves') as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}';counter=0
            def read():
                with urlopen(base+'/state') as response:return json.load(response)
            def post(kind,**extra):
                nonlocal counter
                counter+=1;state=read();command=dict(kind=kind,request_id=str(counter),instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return json.load(response)
            try:
                before=session.core.snapshot();first=read()
                self.assertEqual(first,read());self.assertEqual(session.core.snapshot(),before)
                details=first['clear_results']['rows'][0]['details']
                self.assertIsNotNone(first['goal_result'])
                post('continue_bond_goal')
                self.assertIsNone(read()['goal_result'])
                self.assertEqual(read()['clear_results']['rows'][0]['details'],details)
                post('day_off');saved=post('save_game')
                post('set_shifts');post('load_game',save_id=saved['save_id'])
                self.assertEqual(read()['clear_results']['rows'][0]['details'],details)
                post('new_game',choice='free')
                self.assertEqual(read()['clear_results']['rows'],[])
                self.assertEqual(files,{p:p.read_bytes() for p in files})
            finally:server.shutdown();thread.join()
