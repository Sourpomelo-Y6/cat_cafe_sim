import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.unity_state_server import make_server,state_view


def missing_game(directory,kitten=True,cost=250):
    settings=starting_conditions('free')
    settings['management'].update(starting_funds=10000,stress_per_service_tick=100,runaway_threshold=100,return_stress=10,kitten_probability=int(kitten),kitten_cost=cost)
    settings['store_events']['probability']=0
    settings.pop('intake_request',None);settings.pop('growth',None)
    session=create_game(directory,settings)
    session.set_shifts(['cat-sora'])
    while not session.core.closed:session.automatic_step(auto_assign=True)
    return session


class UnityMissingTests(unittest.TestCase):
    def test_projection_hides_future_outcome_and_matches_saved_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            session=missing_game(Path(directory))
            before=session.core.snapshot();rows=state_view(session)['missing_cats'];self.assertEqual(session.core.snapshot(),before)
            self.assertEqual(len(rows),1);row=rows[0]
            self.assertEqual(row['status'],'missing');self.assertEqual(row['remaining'],2)
            self.assertFalse(row['kitten']);self.assertEqual(row['cost'],0);self.assertFalse(row['can_resolve'])
            cat=next(r for r in state_view(session)['cats'] if r['cat_id']=='cat-sora')
            self.assertEqual(cat['activity'],'missing');self.assertFalse(cat['working']);self.assertFalse(cat['can_player_start'])
            session.next_day();session.day_off();session.day_off()
            before=session.core.snapshot();row=state_view(session)['missing_cats'][0];self.assertEqual(session.core.snapshot(),before)
            self.assertTrue(row['can_resolve']);self.assertTrue(row['kitten']);self.assertEqual(row['cost'],250);self.assertEqual(row['return_stress'],10)
            self.assertEqual(row['funds_after'],session.core.funds-250)

    def test_http_return_retries_and_all_save_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            session=missing_game(Path(directory)/'source')
            originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base+'/state') as response:return json.load(response)
                def post(kind,command=None,**extra):
                    state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                    try:
                        with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                    except HTTPError as ex:return ex.code,json.load(ex),command
                try:
                    row=read()['missing_cats'][0];event=row['choice'];before=session.core.snapshot()
                    self.assertEqual(post('resolve_missing',cat_id='cat-sora')[0],400)
                    self.assertEqual(post('resolve_missing',cat_id='cat-sora',choice=event)[0],422);self.assertEqual(session.core.snapshot(),before)
                    missing=post('save_game')[1]['save_id'];session.next_day();session.day_off();session.day_off()
                    self.assertTrue(read()['missing_cats'][0]['can_resolve']);waiting=post('save_game')[1]['save_id']
                    self.assertEqual(post('load_game',save_id=missing)[0],200);self.assertEqual(read()['missing_cats'][0],row)
                    self.assertEqual(post('load_game',save_id=waiting)[0],200)
                    for cat,event_id in [('cat-mike',event),('cat-sora','unknown')]:
                        before=session.core.snapshot();self.assertEqual(post('resolve_missing',cat_id=cat,choice=event_id)[0],422);self.assertEqual(session.core.snapshot(),before)
                    self.assertEqual(post('next_day')[0],422)
                    reference=copy.deepcopy(session);reference.resolve_missing(event);funds=session.core.funds
                    code,result,command=post('resolve_missing',cat_id='cat-sora',choice=event);self.assertEqual(code,200,result)
                    self.assertEqual(session.core.snapshot(),reference.core.snapshot());self.assertEqual(session.core.funds,funds-250)
                    self.assertEqual(post('resolve_missing',command)[:2],(code,result))
                    self.assertEqual(post('resolve_missing',cat_id='cat-sora',choice=event)[0],422)
                    self.assertEqual(session.core.activity('cat-sora'),'cafe');self.assertNotIn('cat-sora',session.core.working_cats)
                    self.assertEqual(session.core.cats['cat-sora'].stamina,session.core.config.max_stamina);self.assertEqual(session.core.management['stress']['cat-sora'],10)
                    final=read()['missing_cats'][0];resolved=post('save_game')[1]['save_id']
                    self.assertEqual(post('load_game',save_id=waiting)[0],200);self.assertTrue(read()['missing_cats'][0]['can_resolve'])
                    self.assertEqual(post('load_game',save_id=resolved)[0],200);self.assertEqual(read()['missing_cats'][0],final)
                    self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                finally:server.shutdown();thread.join()

    def test_no_kitten_and_cost_ending_game(self):
        with tempfile.TemporaryDirectory() as directory:
            for kitten,cost in [(False,250),(True,20000)]:
                with self.subTest(kitten=kitten):
                    session=missing_game(Path(directory)/str(kitten),kitten,cost);session.next_day();session.day_off();session.day_off()
                    row=state_view(session)['missing_cats'][0];self.assertTrue(row['can_resolve']);self.assertEqual(row['cost'],cost if kitten else 0)
                    session.resolve_missing(row['choice']);self.assertEqual(bool(session.core.management['game_over']),kitten)
                    self.assertFalse(state_view(session)['missing_cats'][0]['can_resolve'])

    def test_rest_without_working_cats_uses_existing_day_off_and_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            session=missing_game(Path(directory)/'source');session.next_day()
            self.assertFalse(session.core.working_cats)
            before=session.core.snapshot();view=state_view(session)['missing_rest'];self.assertTrue(view['can_rest']);self.assertEqual(session.core.snapshot(),before)
            with make_server(session,0,Path(directory)/'saves') as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
                def post(command):
                    try:
                        with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response)
                    except HTTPError as ex:return ex.code,json.load(ex)
                try:
                    with urlopen(base+'/state') as response:state=json.load(response)
                    command=dict(kind='rest_for_missing',request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[])
                    reference=copy.deepcopy(session);reference.day_off()
                    result=post(command);self.assertEqual(result[0],200,result);self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                    self.assertEqual(session.core.funds,view['funds_after']);self.assertEqual(post(command),result)
                    self.assertEqual(state_view(session)['missing_cats'][0]['remaining'],1)
                    command.update(request_id=uuid.uuid4().hex,expected_revision=result[1]['state']['revision'])
                    result=post(command);self.assertEqual(result[0],200,result);self.assertEqual(state_view(session)['missing_cats'][0]['status'],'waiting')
                    command.update(request_id=uuid.uuid4().hex,expected_revision=result[1]['state']['revision']);before=session.core.snapshot()
                    self.assertEqual(post(command)[0],422);self.assertEqual(session.core.snapshot(),before)
                finally:server.shutdown();thread.join()
