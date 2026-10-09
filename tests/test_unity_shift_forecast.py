import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.cafe_shift_forecast import shift_forecast, estimate_text
from cat_cafe_sim.core.cafe_shifts import fatigue_rest_schedule
from cat_cafe_sim.unity_state_server import make_server, state_view


class UnityShiftForecastTests(unittest.TestCase):
    def test_forecast_and_proposal_are_read_only_and_match_python(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source')
            while not session.core.closed: session.automatic_step(auto_assign=True)
            session.next_day()
            keys=sorted(session.core.cats)
            for key in keys: session.core.cats[key].fatigue=60
            session.core.cats[keys[-1]].health_status='sick'
            for key in keys: session.core.day_results[-1]['cats'][key]['service_ticks']=6
            before=copy.deepcopy(session.core.snapshot())
            original={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            view=state_view(session)
            expected=fatigue_rest_schedule({key:cat for key,cat in session.core.cats.items() if session.core.activity(key)=='cafe'})
            self.assertEqual(view['rest_proposal'],expected)
            self.assertNotIn(keys[0],expected);self.assertNotIn(keys[1],expected)
            self.assertNotIn(keys[-1],expected)
            for row in view['cats']:
                forecast=shift_forecast(session.core,row['cat_id'])
                self.assertIn('前日接客：6行動',row['shift_forecast'])
                self.assertIn(estimate_text(forecast['rest']),row['shift_forecast'])
                if forecast['sick']:self.assertIn('出勤不可',row['shift_forecast'])
                else:self.assertIn(estimate_text(forecast['work']),row['shift_forecast'])
            self.assertEqual(session.core.snapshot(),before)
            session.core.day_results=[]
            self.assertIn('記録なし',state_view(session)['cats'][0]['shift_forecast'])
            session.core.shift_rules=None
            self.assertIn('未導入',state_view(session)['cats'][0]['shift_forecast'])
            absent=keys[2]
            from cat_cafe_sim.core.cafe_activities import ensure
            ensure(session.core)
            session.core.activities['cats'][absent]='dispatched'
            absent_view=state_view(session)
            self.assertNotIn(absent,absent_view['rest_proposal'])
            self.assertIn('在店していません',next(row for row in absent_view['cats'] if row['cat_id']==absent)['shift_forecast'])
            self.assertEqual(original,{p:p.read_bytes() for p in original})

    def test_http_proposal_confirm_retry_and_save_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            session=create_game(Path(directory)/'source')
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base+'/state') as response:return json.load(response)
                def send(command):
                    with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return json.load(response)
                def command(kind,**extra):
                    state=read()
                    return dict(kind=kind,request_id=str(state['revision'])+kind,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                try:
                    before=session.core.snapshot();view=read();self.assertEqual(view,read());self.assertEqual(session.core.snapshot(),before)
                    ids=view['rest_proposal'];cmd=command('set_shifts');cmd['working_cats']=ids
                    response=send(cmd);self.assertEqual(send(cmd),response)
                    self.assertEqual(sorted(session.core.working_cats),sorted(ids))
                    saved=send(command('save_game'))
                    changed=command('set_shifts');changed['working_cats']=[];send(changed)
                    send(command('load_game',save_id=saved['save_id']))
                    self.assertEqual(sorted(session.core.working_cats),sorted(ids))
                finally:server.shutdown();thread.join()
