import json
import tempfile
import threading
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import make_server, state_view


class UnityStateTests(unittest.TestCase):
    def test_goal_results_continue_retry_and_save_restore(self):
        import copy
        from pathlib import Path
        from cat_cafe_sim.cafe_new_game import starting_conditions
        from cat_cafe_sim.storage.cafe_saves import load_game
        for status, target in (('cleared',101), ('expired',600)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                settings=starting_conditions()
                settings['goal']=dict(days=1,target=target,cap=650,gain_per_success=5,
                    stages=[dict(days=10,target=625),dict(days=10,target=650)])
                session=create_game(Path(directory)/'source',settings)
                while not session.core.closed: session.automatic_step(auto_assign=True)
                self.assertEqual(session.core.goal['status'],status)
                files={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
                with make_server(session,0,Path(directory)/'saves') as server:
                    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
                    base=f'http://127.0.0.1:{server.server_port}'; counter=0
                    def read():
                        with urlopen(base+'/state') as response:return json.load(response)
                    def post(kind,command=None,**extra):
                        nonlocal counter
                        counter+=1; state=read()
                        command=command or dict(kind=kind,request_id=str(counter),instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                        try:
                            with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                        except HTTPError as ex:return ex.code,json.load(ex),command
                    try:
                        snapshot=session.core.snapshot(); waiting=read()
                        self.assertEqual(session.core.snapshot(),snapshot)
                        self.assertEqual(waiting['goal_result']['status'],status)
                        self.assertTrue(waiting['goal_result']['can_continue'])
                        self.assertEqual(post('next_day')[0],422)
                        self.assertEqual(read(),waiting)
                        code,saved_waiting,_=post('save_game'); self.assertEqual(code,200)
                        waiting=read()
                        with patch.object(type(session),'continue_goal',side_effect=ValueError('先に帰還・譲渡イベントを確認してください。')):
                            self.assertFalse(read()['goal_result']['can_continue'])
                            self.assertEqual(post('continue_goal')[0],422)
                        self.assertEqual(read(),waiting)
                        reference=copy.deepcopy(session); reference.continue_goal()
                        code,result,command=post('continue_goal'); self.assertEqual(code,200,result)
                        self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                        self.assertEqual(read()['funds'],waiting['funds'])
                        self.assertIsNone(read()['goal_result'])
                        self.assertEqual(read()['required_action'],'')
                        confirmed=read()
                        self.assertEqual(post('continue_goal',command=command)[:2],(code,result))
                        self.assertEqual(read(),confirmed)
                        self.assertEqual(post('continue_goal')[0],422)
                        snapshot=session.core.snapshot()
                        code,saved,_=post('save_game'); self.assertEqual(code,200)
                        self.assertEqual(post('next_day')[0],200)
                        self.assertEqual(post('load_game',save_id=saved['save_id'])[0],200)
                        self.assertEqual(session.core.snapshot(),snapshot)
                        self.assertIsNone(read()['goal_result'])
                        restarted,_=load_game(Path(directory)/'saves'/saved['save_id']/'cafe.json')
                        self.assertEqual(restarted.core.snapshot(),snapshot)
                        self.assertEqual(post('load_game',save_id=saved_waiting['save_id'])[0],200)
                        self.assertEqual(read()['goal_result']['status'],status)
                        self.assertTrue(read()['goal_result']['can_continue'])
                        self.assertEqual(files,{p:p.read_bytes() for p in files})
                    finally:server.shutdown();thread.join()

    def test_housing_expansion_full_intake_both_stages_and_restore(self):
        import copy
        from pathlib import Path
        from cat_cafe_sim.cafe_new_game import starting_conditions
        from cat_cafe_sim.storage.cafe_saves import load_game
        settings = starting_conditions()
        settings['management']['starting_funds'] = 10000
        settings['intake_request']['day'] = 2
        settings['profiles']['cats']['sixth'] = copy.deepcopy(settings['profiles']['cats']['cat-mugi'])
        settings['profiles']['cats']['sixth']['name'] = 'ツキ'
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(Path(directory)/'source', settings)
            session.day_off()
            files = {p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            save_root = Path(directory)/'unity'
            with make_server(session, 0, save_root) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                base = f'http://127.0.0.1:{server.server_port}'; counter = 0
                def read():
                    with urlopen(base+'/state') as response: return json.load(response)
                def post(kind, command=None, **extra):
                    nonlocal counter
                    counter += 1; state = read()
                    command = command or dict(request_id=str(counter), instance_id=state['instance_id'],
                        expected_revision=state['revision'], kind=kind, working_cats=[], **extra)
                    try:
                        with urlopen(Request(base+'/commands', json.dumps(command).encode(), {'Content-Type':'application/json'})) as response:
                            return response.status, json.load(response), command
                    except HTTPError as ex: return ex.code, json.load(ex), command
                try:
                    before = read(); h = before['housing']
                    self.assertEqual((h['count'], h['capacity'], h['free']), (6, 6, 0))
                    self.assertTrue(h['can_expand']); self.assertFalse(before['intake_request']['can_accept'])
                    self.assertEqual(post('upgrade_housing')[0], 422)
                    self.assertEqual(read(), before)
                    for kind, stage in (('purchase_housing',1), ('upgrade_housing',2)):
                        before = read(); h = before['housing']; seats = before['seats']
                        old_funds = session.core.funds; session.core.funds = h['cost']
                        self.assertFalse(read()['housing']['can_expand'])
                        self.assertEqual(post(kind)[0], 422); self.assertEqual(session.core.funds,h['cost'])
                        session.core.funds = old_funds
                        with patch.object(type(session.core), 'require_events_resolved', side_effect=ValueError('目標の結果を確認してください。')):
                            self.assertFalse(read()['housing']['can_expand'])
                            self.assertEqual(post(kind)[0], 422)
                        self.assertEqual(read(),before)
                        reference = copy.deepcopy(session)
                        getattr(reference,kind)()
                        code, result, command = post(kind); self.assertEqual(code,200,result)
                        self.assertEqual(session.core.snapshot(),reference.core.snapshot())
                        after = read(); self.assertEqual(after['funds'],old_funds-h['cost'])
                        self.assertEqual(after['housing']['stage'],stage)
                        self.assertEqual(after['housing']['capacity'],h['next_capacity'])
                        self.assertEqual(after['housing']['daily_cost'],h['next_daily_cost'])
                        self.assertEqual(after['housing']['operating_cost'],h['next_operating_cost'])
                        self.assertEqual(after['seats'],seats)
                        self.assertEqual(post(kind,command=command)[:2],(code,result))
                        self.assertEqual(read(),after)
                        self.assertEqual(post(kind)[0],422)
                    self.assertTrue(read()['intake_request']['can_accept'])
                    self.assertFalse(read()['housing']['can_expand'])
                    snapshot=session.core.snapshot()
                    code,saved,_=post('save_game'); self.assertEqual(code,200,saved)
                    self.assertEqual(post('resolve_intake',choice='accept')[0],200)
                    self.assertEqual(read()['housing']['count'],7)
                    self.assertEqual(post('start_business')[0],200)
                    self.assertFalse(read()['housing']['can_expand'])
                    self.assertEqual(post('load_game',save_id=saved['save_id'])[0],200)
                    self.assertEqual(session.core.snapshot(),snapshot)
                    restarted,_=load_game(save_root/saved['save_id']/'cafe.json')
                    self.assertEqual(restarted.core.snapshot(),snapshot)
                    self.assertEqual(files,{p:p.read_bytes() for p in files})
                finally: server.shutdown(); thread.join()

    def test_intake_answers_retries_failures_and_saved_cat_registration(self):
        import copy
        from pathlib import Path
        from cat_cafe_sim.storage.cafe_saves import MemoryRelationships, load_game
        for choice in ('accept', 'decline'):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                session = create_game(Path(directory) / 'source')
                for _ in range(3): session.day_off()
                self.assertEqual(session.core.intake_request['status'], 'waiting')
                files = {p: p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
                save_root = Path(directory) / 'unity'
                with make_server(session, 0, save_root) as server:
                    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                    base = f'http://127.0.0.1:{server.server_port}'
                    def read():
                        with urlopen(base+'/state') as response: return json.load(response)
                    counter = 0
                    def post(kind, answer='', save_id='', command=None):
                        nonlocal counter
                        counter += 1
                        state = read()
                        command = command or dict(request_id=str(counter), instance_id=state['instance_id'],
                            expected_revision=state['revision'], kind=kind, working_cats=[], choice=answer, save_id=save_id)
                        try:
                            with urlopen(Request(base+'/commands', json.dumps(command).encode(),
                                    {'Content-Type':'application/json'})) as response:
                                return response.status, json.load(response), command
                        except HTTPError as ex: return ex.code, json.load(ex), command
                    try:
                        waiting = read(); intake = waiting['intake_request']; funds = waiting['funds']
                        self.assertTrue(intake['can_accept']); self.assertTrue(intake['can_decline'])
                        self.assertEqual(intake['name'], 'ナナ'); self.assertTrue(intake['features'])
                        self.assertEqual(post('resolve_intake', 'invalid')[0], 400)
                        self.assertEqual(post('start_business')[0], 422)
                        self.assertEqual(read(), waiting)
                        code, saved_waiting, _ = post('save_game'); self.assertEqual(code, 200)
                        waiting = read()
                        if choice == 'accept':
                            with patch.object(MemoryRelationships, '_write', side_effect=OSError('registration failed')):
                                self.assertEqual(post('resolve_intake', choice)[0], 422)
                            self.assertEqual(read(), waiting)
                            with patch('cat_cafe_sim.core.cafe_housing.admission_reason', return_value='飼育スペースが満員です。'):
                                self.assertFalse(read()['intake_request']['can_accept'])
                                self.assertTrue(read()['intake_request']['can_decline'])
                                self.assertEqual(post('resolve_intake', choice)[0], 422)
                            old_funds = session.core.funds; session.core.funds = intake['cost']
                            self.assertFalse(read()['intake_request']['can_accept'])
                            self.assertTrue(read()['intake_request']['can_decline'])
                            self.assertEqual(post('resolve_intake', choice)[0], 422)
                            session.core.funds = old_funds
                        reference = copy.deepcopy(session); reference.resolve_intake_request(choice)
                        code, result, command = post('resolve_intake', choice)
                        self.assertEqual(code, 200, result)
                        self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                        self.assertEqual(session.store._read(), reference.store._read())
                        answered = read()
                        self.assertEqual(post('resolve_intake', command=command)[:2], (code, result))
                        self.assertEqual(read(), answered)
                        self.assertEqual(answered['intake_request']['status'], 'accepted' if choice=='accept' else 'declined')
                        self.assertEqual(answered['funds'], funds-(intake['cost'] if choice=='accept' else 0))
                        self.assertEqual(len(answered['cats']), 6 if choice=='accept' else 5)
                        self.assertEqual(answered['required_action'], '')
                        if choice == 'accept':
                            cat = next(cat for cat in answered['cats'] if cat['cat_id']==intake['cat_id'])
                            self.assertFalse(cat['working']); self.assertEqual(cat['stamina'], cat['max_stamina'])
                            self.assertEqual(cat['health_status'], 'healthy')
                        self.assertEqual(post('resolve_intake', 'decline' if choice=='accept' else 'accept')[0], 422)
                        snapshot = session.core.snapshot(); relationships = session.store._read()
                        code, saved, _ = post('save_game'); self.assertEqual(code, 200, saved)
                        self.assertEqual(post('start_business')[0], 200)
                        self.assertEqual(post('load_game', save_id=saved['save_id'])[0], 200)
                        self.assertEqual(session.core.snapshot(), snapshot)
                        self.assertEqual(session.store._read(), relationships)
                        restarted, _ = load_game(save_root/saved['save_id']/'cafe.json')
                        self.assertEqual(restarted.core.snapshot(), snapshot)
                        self.assertEqual(restarted.store._read(), relationships)
                        self.assertEqual(post('load_game', save_id=saved_waiting['save_id'])[0], 200)
                        self.assertEqual(read()['intake_request']['status'], 'waiting')
                        self.assertEqual(len(read()['cats']), 5)
                        self.assertEqual(files, {p:p.read_bytes() for p in files})
                    finally: server.shutdown(); thread.join()

    def test_next_day_recovery_retry_events_and_saved_preparation(self):
        import copy
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(Path(directory) / 'source')
            with make_server(session, 0, Path(directory) / 'saves') as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base + '/state') as response: return json.load(response)
                counter = 0
                def post(kind, command=None, **extra):
                    nonlocal counter
                    counter += 1
                    state = read()
                    command = command or dict(request_id=str(counter), instance_id=state['instance_id'],
                        expected_revision=state['revision'], kind=kind, working_cats=[], **extra)
                    try:
                        with urlopen(Request(base+'/commands', json.dumps(command).encode(),
                                {'Content-Type': 'application/json'})) as response:
                            return response.status, json.load(response), command
                    except HTTPError as ex: return ex.code, json.load(ex), command
                try:
                    before = read()
                    self.assertEqual(post('next_day')[0], 422)
                    self.assertEqual(read(), before)
                    self.assertEqual(post('start_business')[0], 200)
                    while not session.core.closed: self.assertEqual(post('advance_business')[0], 200)
                    closed = read()
                    # A pending answer must be visible on every read, without changing the state.
                    with patch.object(type(session.core), 'require_events_resolved',
                                      side_effect=ValueError('保護猫の受け入れ依頼に回答してください。')):
                        blocked = read()
                        self.assertIn('受け入れ依頼', blocked['required_action'])
                        self.assertEqual(post('next_day')[0], 422)
                        self.assertEqual(read(), blocked)
                    self.assertEqual(read(), closed)
                    reference = copy.deepcopy(session)
                    reference.next_day()
                    code, result, command = post('next_day')
                    self.assertEqual(code, 200, result)
                    self.assertEqual(session.core.snapshot(), reference.core.snapshot())
                    self.assertEqual(session.store._read(), reference.store._read())
                    day_two = read()
                    self.assertEqual((day_two['day'], day_two['tick'], day_two['phase']), (2, 0, 'preparation'))
                    self.assertTrue(day_two['can_set_shifts'])
                    self.assertEqual(day_two['customers'], [])
                    self.assertTrue(all(not seat['customer_id'] for seat in day_two['seats']))
                    self.assertEqual(post('next_day', command=command)[:2], (code, result))
                    self.assertEqual(read(), day_two)
                    working = [cat['cat_id'] for cat in day_two['cats'] if cat['working']]
                    selected = working[:-1]
                    shift_command = dict(request_id='day2-shifts', instance_id=day_two['instance_id'],
                        expected_revision=day_two['revision'], kind='set_shifts', working_cats=selected)
                    self.assertEqual(post('set_shifts', command=shift_command)[0], 200)
                    snapshot = session.core.snapshot()
                    code, saved, _ = post('save_game')
                    self.assertEqual(code, 200, saved)
                    self.assertEqual(post('start_business')[0], 200)
                    self.assertEqual(post('load_game', save_id=saved['save_id'])[0], 200)
                    self.assertEqual(session.core.snapshot(), snapshot)
                    self.assertEqual(read()['day'], 2)
                    self.assertTrue(read()['can_set_shifts'])
                finally:
                    server.shutdown(); thread.join()

    def test_save_load_restart_active_service_and_closed_result(self):
        from pathlib import Path
        from cat_cafe_sim.storage.cafe_saves import load_game
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(Path(directory)/'source')
            original = {p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
            save_root = Path(directory)/'unity'
            with make_server(session, 0, save_root) as server:
                thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
                base=f'http://127.0.0.1:{server.server_port}'
                def read(path='/state'):
                    with urlopen(base+path) as response: return json.load(response)
                counter=0
                def post(kind, save_id='', command=None):
                    nonlocal counter
                    counter+=1
                    state=read()
                    command=command or dict(kind=kind,request_id=str(counter),instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],save_id=save_id)
                    request=Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})
                    try:
                        with urlopen(request) as response: return response.status,json.load(response),command
                    except HTTPError as ex: return ex.code,json.load(ex),command
                try:
                    self.assertEqual(read('/saves')['saves'],[])
                    self.assertEqual(post('start_business')[0],200)
                    self.assertEqual(post('advance_business')[0],200)
                    self.assertTrue(session.active_interactions)
                    snapshot=session.core.snapshot(); relationships=session.store._read()
                    code,result,command=post('save_game')
                    self.assertEqual(code,200,result)
                    self.assertEqual(post('save_game',command=command)[:2],(code,result))
                    self.assertEqual(len(read('/saves')['saves']),1)
                    row=read('/saves')['saves'][0]
                    self.assertEqual(row['phase'],'open')
                    self.assertTrue(row['objective_label'])
                    self.assertTrue(row['created_at'])
                    save_id=result['save_id']
                    info_path=save_root/save_id/'info.json'
                    info=json.loads(info_path.read_text(encoding='utf-8'))
                    info.pop('objective_label'); info.pop('phase')
                    info_path.write_text(json.dumps(info),encoding='utf-8')
                    self.assertEqual(read('/saves')['saves'][0]['save_id'],save_id)
                    loaded,_=load_game(save_root/save_id/'cafe.json')
                    self.assertEqual(loaded.core.snapshot(),snapshot)
                    self.assertEqual(loaded.store._read(),relationships)
                    self.assertEqual(post('advance_business')[0],200)
                    self.assertEqual(post('load_game',save_id)[0],200)
                    self.assertEqual(session.core.snapshot(),snapshot)
                    self.assertEqual(session.store._read(),relationships)
                    self.assertEqual(post('load_game','../source')[0],422)
                    self.assertEqual(session.core.snapshot(),snapshot)
                    saved_file=save_root/save_id/'cafe.json'; saved_bytes=saved_file.read_bytes()
                    saved_file.write_text('{broken',encoding='utf-8')
                    self.assertEqual(post('load_game',save_id)[0],422)
                    self.assertEqual(session.core.snapshot(),snapshot)
                    saved_file.write_bytes(saved_bytes)
                    with patch('cat_cafe_sim.storage.cafe_saves.save_game',side_effect=OSError('disk full')):
                        self.assertEqual(post('save_game')[0],422)
                    self.assertEqual(len(read('/saves')['saves']),1)
                    self.assertEqual(session.core.snapshot(),snapshot)
                    while not session.core.closed: self.assertEqual(post('advance_business')[0],200)
                    closed=session.core.snapshot()
                    code,result,_=post('save_game'); self.assertEqual(code,200,result)
                    self.assertEqual(read('/saves')['saves'][0]['phase'],'closed')
                    closed_id=result['save_id']
                    self.assertEqual(post('load_game',save_id)[0],200)
                    self.assertFalse(session.core.closed)
                    self.assertEqual(post('load_game',closed_id)[0],200)
                    self.assertEqual(session.core.snapshot(),closed)
                    self.assertEqual(original,{p:p.read_bytes() for p in original})
                finally: server.shutdown(); thread.join()
            # Snapshot remains loadable after the server/session is destroyed.
            restarted,_=load_game(save_root/closed_id/'cafe.json')
            self.assertEqual(restarted.core.snapshot(),closed)

    def test_one_day_business_matches_existing_session_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            reference = create_game(directory)
            files = {path: path.read_bytes() for path in session.checkpoint_path.parent.iterdir()}
            with make_server(session, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def read():
                    with urlopen(base + '/state') as response:
                        return json.load(response)
                def post(state, kind, request_id, working_cats=None):
                    command = dict(request_id=request_id, instance_id=state['instance_id'], expected_revision=state['revision'],
                                   kind=kind, working_cats=working_cats or [])
                    request = Request(base + '/commands', json.dumps(command).encode(), {'Content-Type': 'application/json'})
                    try:
                        with urlopen(request) as response:
                            return response.status, json.load(response)
                    except HTTPError as ex:
                        return ex.code, json.load(ex)
                try:
                    initial = read()
                    self.assertEqual(post(initial, 'advance_business', 'early')[0], 422)
                    _, response = post(initial, 'set_shifts', 'all-rest')
                    rest = response['state']
                    self.assertEqual(post(rest, 'start_business', 'no-workers')[0], 422)
                    _, response = post(rest, 'set_shifts', 'all-work', list(session.core.cats))
                    initial = response['state']
                    code, response = post(initial, 'start_business', 'start')
                    self.assertEqual(code, 200)
                    self.assertEqual(response['state']['tick'], 1)
                    self.assertFalse(response['state']['can_set_shifts'])
                    self.assertEqual(post(initial, 'start_business', 'start'), (code, response))
                    state = response['state']
                    snapshot = session.core.snapshot()
                    # If automatic assignment has happened before an error, discard
                    # the entire candidate instead of leaving a half-applied step.
                    with patch.object(type(session.policy), 'choose', side_effect=ValueError('policy failed')):
                        self.assertEqual(post(state, 'advance_business', 'failure')[0], 422)
                    self.assertEqual(session.core.snapshot(), snapshot)
                    self.assertEqual(read()['revision'], state['revision'])
                    self.assertEqual(post(state, 'start_business', 'twice')[0], 422)
                    occupied = False
                    while not state['closed']:
                        code, response = post(state, 'advance_business', f"tick-{state['tick']}")
                        self.assertEqual(code, 200, response)
                        state = response['state']
                        for seat in state['seats']:
                            if seat['customer_id']:
                                customer = next(row for row in state['customers'] if row['customer_id'] == seat['customer_id'])
                                self.assertEqual(customer['status'], 'seated')
                                self.assertEqual(customer['seat_id'], seat['seat_id'])
                                self.assertEqual(customer['name'], seat['customer_name'])
                        occupied |= any(seat['customer_id'] for seat in state['seats'])
                    while not reference.core.closed:
                        reference.automatic_step(auto_assign=True)
                    self.assertTrue(occupied)
                    self.assertEqual(state['tick'], session.core.config.opening_ticks)
                    self.assertGreater(state['completed_interactions'], 0)
                    self.assertTrue(all(customer['status'] == 'departed' for customer in state['customers']))
                    self.assertEqual(session.core.summary(), reference.core.summary())
                    self.assertEqual(state['finance']['closing_funds'], state['funds'])
                    self.assertEqual(state['finance']['net_cash_flow'], state['finance']['total_income'] - state['finance']['total_expenses'])
                    after = session.core.snapshot()
                    self.assertEqual(post(state, 'advance_business', 'after-close')[0], 422)
                    self.assertEqual(after, session.core.snapshot())
                    self.assertEqual(files, {path: path.read_bytes() for path in files})
                finally:
                    server.shutdown()
                    thread.join()

    def test_read_only_http_and_live_session_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            before = session.core.snapshot()
            with make_server(session, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = f'http://127.0.0.1:{server.server_port}'
                    with urlopen(base + '/state') as response:
                        data = json.load(response)
                    self.assertEqual(len(data['cats']), 5)
                    mike = next(cat for cat in data['cats'] if cat['cat_id'] == 'cat-mike')
                    self.assertEqual(mike['name'], 'ミケ')
                    self.assertEqual(mike['content_cat_id'], 'playtest-mike')
                    self.assertEqual(before, session.core.snapshot())
                    with urlopen(base + '/health') as response:
                        self.assertFalse(json.load(response)['read_only'])
                    for request, code in [(base + '/missing', 404), (Request(base + '/state', data=b'{}'), 404)]:
                        with self.assertRaises(HTTPError) as caught:
                            urlopen(request)
                        self.assertEqual(caught.exception.code, code)
                finally:
                    server.shutdown()
                    thread.join()
            session.set_shifts(['cat-mike'])
            session.core.cats['cat-mike'].stamina = 73
            data = state_view(session)
            rows = {cat['cat_id']: cat for cat in data['cats']}
            self.assertEqual(rows['cat-mike']['stamina'], 73)
            self.assertTrue(rows['cat-mike']['working'])
            self.assertFalse(rows['cat-tama']['working'])

    def test_shift_commands_retry_conflict_and_rule_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            session = create_game(directory)
            files = {path: path.read_bytes() for path in session.checkpoint_path.parent.iterdir()}
            with make_server(session, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                def post(command):
                    request = Request(base + '/commands', json.dumps(command).encode(), {'Content-Type': 'application/json'})
                    try:
                        with urlopen(request) as response:
                            return response.status, json.load(response)
                    except HTTPError as ex:
                        return ex.code, json.load(ex)
                try:
                    with urlopen(base + '/state') as response:
                        state = json.load(response)
                    command = dict(request_id='first', instance_id=state['instance_id'], expected_revision=0,
                                   kind='set_shifts', working_cats=['cat-mike'])
                    code, result = post(command)
                    self.assertEqual(code, 200)
                    self.assertEqual(result['state']['revision'], 1)
                    after = session.core.snapshot()
                    self.assertEqual(post(command), (code, result))
                    self.assertEqual(after, session.core.snapshot())
                    self.assertEqual(post(dict(command, working_cats=[]))[0], 409)
                    self.assertEqual(post(dict(command, request_id='stale'))[0], 409)
                    self.assertEqual(post(dict(command, request_id='restart', expected_revision=1, instance_id='old'))[0], 409)
                    for cats in [['missing'], ['cat-mike', 'cat-mike']]:
                        invalid = dict(command, request_id=str(cats), expected_revision=1, working_cats=cats)
                        self.assertEqual(post(invalid)[0], 422)
                        self.assertEqual(after, session.core.snapshot())
                    self.assertEqual(post(dict(command, request_id='rest', expected_revision=1, working_cats=[]))[0], 200)
                    self.assertEqual(session.core.working_cats, set())
                    session.core.tick = 1
                    blocked = dict(command, request_id='late', expected_revision=2)
                    self.assertEqual(post(blocked)[0], 422)
                    self.assertEqual(session.core.working_cats, set())
                    self.assertEqual(post({})[0], 400)
                    self.assertEqual(files, {path: path.read_bytes() for path in files})
                finally:
                    server.shutdown()
                    thread.join()
