import copy
import json
import threading
from urllib.request import urlopen
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.storage.cafe_saves import load_game
from cat_cafe_sim.unity_state_server import service_assignment_view, make_server
from test_unity_dispatch_choices import api


class UnityServiceAssignmentTests(unittest.TestCase):
    def game(self, directory):
        settings=starting_conditions('free')
        for key in ('dispatch_unlocks','store_events','intake_request'):
            settings.pop(key,None)
        settings['weekdays']['patterns']=[list(range(7))]
        session=create_game(Path(directory)/'source',settings)
        session.core.config=replace(session.core.config,arrival_ticks=(0,0),opening_ticks=20)
        return session

    def test_projection_is_read_only_and_explains_unavailable_cats_and_seats(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory)
            session.automatic_step(auto_assign=False)
            before=copy.deepcopy(session.core.snapshot())
            view=service_assignment_view(session,False)
            self.assertTrue(view['waiting'])
            self.assertEqual(session.core.snapshot(),before)
            self.assertEqual(len(view['customers']),2)
            customer=view['customers'][0]['customer_id'];cat=view['cats'][0]['cat_id'];seat=view['seats'][0]['seat_id']
            session.start(customer,cat,seat)
            cats=list(session.core.cats)
            resting=next(k for k in cats if k!=cat)
            session.core.working_cats.remove(resting)
            tired=next(k for k in cats if k not in (cat,resting))
            session.core.cats[tired].stamina=0
            before=copy.deepcopy(session.core.snapshot());view=service_assignment_view(session,False)
            rows={r['cat_id']:r for r in view['cats']}
            self.assertIn('接客中',rows[cat]['reason']);self.assertIn('出勤',rows[resting]['reason']);self.assertIn('体力',rows[tired]['reason'])
            self.assertFalse(next(r for r in view['seats'] if r['seat_id']==seat)['available'])
            self.assertEqual(session.core.snapshot(),before)

    def test_manual_http_assignment_matches_python_and_rejects_duplicate_or_invalid_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory)
            originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir() if p.is_file()}
            with api(session,Path(directory)/'saves') as (read,post):
                self.assertEqual(post('set_auto_assignment',choice='manual')[0],200)
                self.assertEqual(post('start_business')[0],200)
                waiting=read();self.assertTrue(waiting['service_assignment']['waiting'])
                self.assertEqual(post('advance_business')[0],422);self.assertEqual(read(),waiting)
                view=waiting['service_assignment'];customer=view['customers'][0]['customer_id'];cat=view['cats'][0]['cat_id'];seat=view['seats'][0]['seat_id']
                reference=copy.deepcopy(session);reference.start(customer,cat,seat)
                code,response,command=post('assign_service',customer_id=customer,cat_id=cat,seat_id=seat)
                self.assertEqual(code,200,response)
                self.assertEqual(session.core.tick,reference.core.tick);self.assertEqual(session.core.funds,reference.core.funds)
                self.assertEqual(session.active_interactions[seat].config,reference.active_interactions[seat].config)
                self.assertEqual(session.core.seats[seat].customer_id,customer);self.assertEqual(session.core.seats[seat].cat_id,cat)
                assigned=read();self.assertEqual(post('assign_service',command=command)[:2],(code,response));self.assertEqual(read(),assigned)
                other=next(r['customer_id'] for r in view['customers'] if r['customer_id']!=customer)
                othercat=next(r['cat_id'] for r in view['cats'] if r['cat_id']!=cat and r['available'])
                otherseat=next(r['seat_id'] for r in view['seats'] if r['seat_id']!=seat and r['available'])
                for c,k,s in ((customer,othercat,otherseat),(other,cat,otherseat),(other,othercat,seat),(other,'missing',otherseat),(other,othercat,'missing')):
                    self.assertEqual(post('assign_service',customer_id=c,cat_id=k,seat_id=s)[0],422);self.assertEqual(read(),assigned)
                self.assertEqual(post('assign_service',customer_id=other,cat_id=othercat,seat_id=otherseat)[0],200)
                self.assertFalse(read()['service_assignment']['waiting']);self.assertEqual(post('advance_business')[0],200)
                self.assertEqual(session.core.tick,reference.core.tick+1)
            self.assertEqual(originals,{p:p.read_bytes() for p in originals})

    def test_auto_mode_save_load_restart_and_manual_assignments_coexist(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory);saves=Path(directory)/'saves'
            with api(session,saves) as (read,post):
                self.assertTrue(read()['service_assignment']['auto_assign'])
                self.assertEqual(post('set_auto_assignment',choice='manual')[0],200);self.assertEqual(post('start_business')[0],200)
                view=read()['service_assignment'];cat=view['cats'][0]['cat_id'];seat=view['seats'][0]['seat_id'];customer=view['customers'][0]['customer_id']
                self.assertEqual(post('assign_service',customer_id=customer,cat_id=cat,seat_id=seat)[0],200)
                saved=post('save_game')[1]['save_id'];snapshot=copy.deepcopy(session.core.snapshot())
                self.assertEqual(post('set_auto_assignment',choice='automatic')[0],200)
                self.assertEqual(session.core.snapshot(),snapshot)
                self.assertEqual(post('assign_service',customer_id=customer,cat_id=cat,seat_id=seat)[0],422)
                self.assertEqual(post('advance_business')[0],200)
                self.assertEqual(session.core.seats[seat].cat_id,cat);self.assertEqual(session.core.seats[seat].customer_id,customer)
                self.assertEqual(len(session.active_interactions),2)
                auto_saved=post('save_game')[1]['save_id']
                self.assertEqual(post('load_game',save_id=saved)[0],200)
                self.assertFalse(read()['service_assignment']['auto_assign']);self.assertTrue(read()['service_assignment']['waiting'])
                self.assertEqual(session.core.snapshot(),snapshot)
                self.assertEqual(post('load_game',save_id=auto_saved)[0],200);self.assertTrue(read()['service_assignment']['auto_assign'])
            restarted,flag=load_game(saves/saved/'cafe.json');self.assertFalse(flag)
            with make_server(restarted,0,saves,auto_assign=flag) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    with urlopen(f'http://127.0.0.1:{server.server_port}/state') as response:state=json.load(response)
                    self.assertFalse(state['service_assignment']['auto_assign']);self.assertTrue(state['service_assignment']['waiting'])
                    self.assertEqual(restarted.core.snapshot(),snapshot)
                finally:server.shutdown();thread.join()

    def test_legacy_single_seat_and_no_available_cat_can_advance(self):
        from test_unity_adoption import adoption_game
        with tempfile.TemporaryDirectory() as directory:
            session=adoption_game(Path(directory)/'source')
            with api(session,Path(directory)/'saves') as (read,post):
                self.assertEqual(post('set_auto_assignment',choice='manual')[0],200)
                self.assertEqual(post('start_business')[0],200)
                view=read()['service_assignment'];self.assertEqual(len(view['seats']),1);self.assertTrue(view['waiting'])
                self.assertEqual(post('assign_service',customer_id=view['customers'][0]['customer_id'],cat_id=view['cats'][0]['cat_id'],seat_id=view['seats'][0]['seat_id'])[0],200)
                self.assertFalse(read()['service_assignment']['waiting'])
                saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200)
                self.assertEqual(len(session.active_interactions),1);self.assertFalse(read()['service_assignment']['auto_assign'])
            session=self.game(Path(directory)/'unavailable')
            session.automatic_step(auto_assign=False)
            for cat in session.core.cats.values():cat.stamina=0
            with api(session,Path(directory)/'unavailable-saves') as (read,post):
                self.assertEqual(post('set_auto_assignment',choice='manual')[0],200)
                self.assertFalse(read()['service_assignment']['waiting'])
                tick=session.core.tick;self.assertEqual(post('advance_business')[0],200);self.assertEqual(session.core.tick,tick+1)

    def test_command_validation_and_preparation_do_not_change_state(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.game(directory)
            with api(session,Path(directory)/'saves') as (read,post):
                before=read()
                self.assertEqual(post('set_auto_assignment',choice='invalid')[0],400);self.assertEqual(read(),before)
                self.assertEqual(post('assign_service',cat_id='cat-mike')[0],400);self.assertEqual(read(),before)
                self.assertEqual(post('set_auto_assignment',choice='manual')[0],200)
                before=read();self.assertEqual(post('assign_service',customer_id='guest-1',cat_id='cat-mike',seat_id='seat-1')[0],422);self.assertEqual(read(),before)
                self.assertEqual(post('new_game',choice='free')[0],200);self.assertTrue(read()['service_assignment']['auto_assign'])


if __name__=='__main__':unittest.main()
