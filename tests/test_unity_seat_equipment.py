import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from test_unity_dispatch_choices import api
import test_unity_expansion as expansion_fixtures
import test_cafe_seat_equipment as fixtures
from cat_cafe_sim.core.cafe_seat_equipment import catalog, owned
from cat_cafe_sim.unity_state_server import state_view

class UnitySeatEquipmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SeatEquipmentTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def test_read_only_projection_all_kinds_saved_effects_and_funds(self):
        s=self.fixture.session(funds=3000);before=s.core.snapshot();view=state_view(s)
        self.assertEqual(before,s.core.snapshot());self.assertEqual(len(view['seat_equipment']['catalog']),5)
        self.assertTrue(all(r['can_purchase'] for r in view['seat_equipment']['catalog']))
        for rules in catalog():s.purchase_seat_equipment('seat-1',rules)
        s.equip_seat('seat-2','equipment-1');s.equip_seat('seat-1')
        before=s.core.snapshot();view=state_view(s);self.assertEqual(before,s.core.snapshot())
        self.assertEqual(view['seats'][1]['equipment_id'],'equipment-1')
        self.assertIn(owned(s.core)[0]['rules']['name'],view['seats'][1]['equipment_description'])
        self.assertEqual(view['seat_equipment']['owned'][0]['seat_id'],'seat-2')
        self.assertTrue(all(r['seat_id']=='' for r in view['seat_equipment']['owned'][1:]))
    def test_http_purchase_exchange_move_remove_retry_and_save(self):
        s=self.fixture.session(funds=3000);s.enable_management()
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            initial=post('save_game')[1]['save_id']
            for rules in catalog():
                reference=copy.deepcopy(s);reference.purchase_seat_equipment('seat-1',rules)
                code,result,command=post('purchase_seat_equipment',target_type='seat-1',choice=rules['id'])
                self.assertEqual(code,200,result);self.assertEqual(s.core.snapshot(),reference.core.snapshot())
                self.assertEqual(post('purchase_seat_equipment',command)[:2],(code,result))
                self.assertEqual(post('purchase_seat_equipment',dict(command,request_id=uuid.uuid4().hex))[0],409)
            for seat,item in [('seat-2','equipment-5'),('seat-1','equipment-1'),('seat-1','equipment-2'),('seat-2','equipment-2'),('seat-2','')]:
                reference=copy.deepcopy(s);reference.equip_seat(seat,item or None);funds=s.core.funds
                code,result,command=post('equip_seat',target_type=seat,choice=item)
                self.assertEqual(code,200,result);self.assertEqual(s.core.snapshot(),reference.core.snapshot());self.assertEqual(s.core.funds,funds)
                self.assertEqual(post('equip_seat',command)[:2],(code,result))
            self.assertEqual(len(owned(s.core)),5);self.assertTrue(all(r['seat_id']=='' for r in read()['seat_equipment']['owned']))
            saved=post('save_game')[1]['save_id'];before=s.core.snapshot()
            self.assertEqual(post('load_game',save_id=initial)[0],200);self.assertEqual(read()['seat_equipment']['owned'],[])
            self.assertEqual(post('load_game',save_id=saved)[0],200);self.assertEqual(s.core.snapshot(),before)
            self.assertEqual(post('day_off')[0],200);self.assertEqual(s.core.day_results[0]['summary']['seat_equipment_expenses'],sum(r['cost'] for r in catalog()))
    def test_authoritative_price_invalid_payloads_and_boundary(self):
        cost=catalog()[0]['cost']
        for funds in (cost-1,cost,cost+1):
            s=self.fixture.session(funds=funds)
            with api(s,Path(self.temp.name)/str(funds)) as (read,post):
                before=s.core.snapshot()
                for extra in [dict(cost=0),dict(target_type='seat-999'),dict(choice='unknown'),dict(cat_id='a'),dict(working_cats=['a'])]:
                    args=dict(target_type='seat-1',choice='toys');args.update(extra)
                    self.assertIn(post('purchase_seat_equipment',**args)[0],(400,422));self.assertEqual(s.core.snapshot(),before)
                self.assertEqual(post('equip_seat',target_type='seat-1',choice='equipment-999')[0],422)
                self.assertEqual(post('purchase_seat_equipment',target_type='seat-1',choice='toys')[0],200 if funds>cost else 422)
                if funds>cost:
                    self.assertEqual(s.core.funds,1);self.assertEqual(post('equip_seat',target_type='seat-2',choice='equipment-1')[0],200)
                else:self.assertEqual(before,s.core.snapshot())
    def test_required_events_player_business_closed_and_legacy_seat(self):
        source=expansion_fixtures.UnityExpansionTests();source.setUp();self.addCleanup(source.doCleanups);s=source.game();cat=next(iter(s.core.cats))
        with api(s,Path(self.temp.name)/'ready') as (read,post):
            s.dispatch(cat);s.day_off();self.assertFalse(read()['seat_equipment']['can_manage'])
            self.assertEqual(post('purchase_seat_equipment',target_type='seat-1',choice='toys')[0],422)
            s.resolve_activity(f'dispatch-1-{cat}');post('player_begin',cat_id=cat)
            self.assertFalse(read()['seat_equipment']['can_manage']);self.assertEqual(post('equip_seat',target_type='seat-1',choice='')[0],422)
            self.assertEqual(post('player_finish',cat_id=cat)[0],200);self.assertEqual(post('start_business')[0],200)
            self.assertFalse(read()['seat_equipment']['can_manage']);self.assertEqual(post('purchase_seat_equipment',target_type='seat-1',choice='toys')[0],422)
            for _ in range(s.core.config.opening_ticks+1):
                if s.core.closed:break
                self.assertEqual(post('advance_business')[0],200)
            self.assertTrue(s.core.closed)
            self.assertFalse(read()['seat_equipment']['can_manage']);self.assertEqual(post('equip_seat',target_type='seat-1',choice='')[0],422)
        legacy=self.fixture.session(seats=1)
        with api(legacy,Path(self.temp.name)/'old') as (read,post):
            seat=read()['seats'][0]['seat_id'];self.assertEqual(post('purchase_seat_equipment',target_type=seat,choice='toys')[0],200)
            self.assertEqual(read()['seats'][0]['equipment_id'],'equipment-1')

if __name__=='__main__':unittest.main()
