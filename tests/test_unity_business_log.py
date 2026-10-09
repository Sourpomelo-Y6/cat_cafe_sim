import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.unity_state_server import make_server
from cat_cafe_sim.unity_business_log import projection


class UnityBusinessLogTests(unittest.TestCase):
    def server(self,session,folder):
        server=make_server(session,0,folder);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def cleanup():server.shutdown();thread.join();server.server_close()
        self.addCleanup(cleanup)
        def read(route,**query):
            try:
                with urlopen(f'http://127.0.0.1:{server.server_port}'+route+('?' + urlencode(query) if query else '')) as response:
                    return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)
        return read

    def test_current_export_actions_paging_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            s=create_game(Path(directory)/'source')
            for _ in range(26):s.automatic_step()
            original={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()};before=copy.deepcopy(s.core.snapshot())
            read=self.server(s,Path(directory)/'saves')
            code,first=read('/business-log');self.assertEqual(code,200);self.assertEqual(len(first['rows']),20)
            rows=[row for page in range(0,first['total'],20) for row in read('/business-log',offset=page)[1]['rows']]
            self.assertTrue(any('反応：' in row['details'] for row in rows))
            for row in rows:
                if '反応：' in row['details']:self.assertLess(row['details'].index('反応：'),row['details'].index('操作の記録'))
            self.assertTrue(any('体力：' in row['details'] for row in rows))
            code,last=read('/business-log',offset=20);self.assertEqual(code,200);self.assertEqual(last['rows'][0]['index'],20)
            self.assertEqual(read('/business-log',offset=99999)[1]['offset'],((first['total']-1)//20)*20)
            code,export=read('/business-log/export');self.assertEqual(code,200)
            log=json.loads(export['log_json']);self.assertEqual(log,s.core.log());self.assertEqual(verify_cafe_interaction(log).log(),log)
            self.assertEqual(first,read('/business-log')[1]);self.assertEqual(before,s.core.snapshot());self.assertEqual(original,{p:p.read_bytes() for p in original})
            self.assertFalse((Path(directory)/'saves').exists())

    def test_saved_replay_is_independent_and_invalid_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            s=create_game(Path(directory)/'source');s.automatic_step();read=self.server(s,Path(directory)/'saves')
            exported=read('/business-log/export')[1]['log_json'];path=Path(directory)/'log.json';path.write_text(exported,encoding='utf-8')
            s.automatic_step();before=copy.deepcopy(s.core.snapshot());raw=path.read_bytes()
            code,view=read('/business-log',path=str(path));self.assertEqual(code,200);self.assertEqual(view['total'],len(json.loads(exported)['operations']))
            self.assertNotEqual(view['total'],read('/business-log')[1]['total']);self.assertIn('リプレイ検証',view['notes'])
            self.assertEqual(raw,path.read_bytes());self.assertEqual(before,s.core.snapshot())
            for bad in ('{bad',json.dumps({'mode_id':'not-a-log'}),json.dumps({**json.loads(exported),'summary':{}})):
                path.write_text(bad,encoding='utf-8');self.assertEqual(read('/business-log',path=str(path))[0],422)
            for route,query in [('/business-log',{'offset':-1}),('/business-log',{'offset':'oops'}),('/business-log',{'path':'relative.json'}),('/business-log',{'extra':'x'}),('/business-log/export',{'path':str(path)})]:
                self.assertEqual(read(route,**query)[0],422)
            self.assertEqual(before,s.core.snapshot())

    def test_player_actions_and_results_are_viewable(self):
        with tempfile.TemporaryDirectory() as directory:
            s=create_game(Path(directory)/'source');key=next(iter(s.core.cats))
            s.play_with_player(key);s.player_command('direct');s.player_command(finish=True)
            before=copy.deepcopy(s.core.snapshot());log=s.core.log();self.assertEqual(verify_cafe_interaction(log).log(),log)
            rows=[row for offset in range(0,len(log['operations']),20) for row in projection(log,offset)['rows']]
            self.assertTrue(any('反応：' in row['details'] for row in rows));self.assertEqual(before,s.core.snapshot())

    def test_legacy_multi_seat_log_and_empty_record_projection(self):
        from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore
        from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
        for cls,ids,version in [(CafeInteractionCore,None,1),(CafeInteractionCore,['test-cat'],2),(MultiSeatCafeCore,['test-cat'],3)]:
            core=cls(cat_ids=ids)
            self.assertEqual(core.log()['format_version'],version);self.assertEqual(projection(core.log())['rows'],[])
            if cls is MultiSeatCafeCore:core.step({})
            else:core.step()
            log=core.log();self.assertEqual(verify_cafe_interaction(log).log(),log)
            view=projection(log);self.assertEqual(view['total'],len(log['operations']));self.assertTrue(view['rows'])
