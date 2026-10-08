import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from test_unity_dispatch_choices import api
import test_cafe_expansion as expansion_fixture
import test_cafe_eight_seat_expansion as stages_fixture
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.core.cafe_operating_cost import estimate
from cat_cafe_sim.core.cafe_expansion import rules,next_step,extra_schedule,EIGHTH_CUSTOMER_ID
from cat_cafe_sim.core.cafe_reservation import waiting
from cat_cafe_sim.unity_state_server import state_view

class UnityExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def game(self):
        selected=starting_conditions('free')
        for key in ('store_events','intake_request','dispatch_unlocks'):selected.pop(key)
        return create_game(Path(self.temp.name)/'source',selected)
    def test_read_only_cost_conditions_and_history(self):
        s=self.game();before=s.core.snapshot()
        row=state_view(s)['expansion'];self.assertEqual(s.core.snapshot(),before)
        self.assertEqual((row['seats'],row['next_seats'],row['cost']),(2,3,rules()['cost']))
        self.assertEqual(row['next_operating_cost'],estimate(s.core,3))
        self.assertTrue(row['can_expand']);self.assertIn('第1段階',row['details'])
        s.expand_seats();before=s.core.snapshot();row=state_view(s)['expansion']
        self.assertEqual(s.core.snapshot(),before);self.assertFalse(row['can_expand'])
        self.assertIn('第1段階',row['reason']);self.assertIn('3席へ増設',row['details'])
    def test_purchase_retry_save_load_and_immediate_seats(self):
        s=self.game();originals={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()}
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            initial=post('save_game')[1]['save_id'];row=read()['expansion']
            self.assertEqual(post('expand_seats',cost=0)[0],400)
            self.assertEqual(post('expand_seats',working_cats=[next(iter(s.core.cats))])[0],422)
            self.assertEqual(post('expand_seats',choice='free')[0],422)
            reference=copy.deepcopy(s);reference.expand_seats()
            code,result,command=post('expand_seats');self.assertEqual(code,200,result)
            self.assertEqual(s.core.snapshot(),reference.core.snapshot())
            self.assertEqual(s.core.funds,row['funds_after']);self.assertEqual(len(read()['seats']),3)
            self.assertEqual(read()['seats'][2]['seat_id'],'seat-3')
            self.assertEqual(post('expand_seats',command)[:2],(code,result))
            self.assertEqual(post('expand_seats')[0],422)
            self.assertEqual(post('expand_seats',dict(command,request_id=uuid.uuid4().hex))[0],409)
            expanded=post('save_game')[1]['save_id'];snapshot=s.core.snapshot()
            self.assertEqual(post('load_game',save_id=initial)[0],200);self.assertEqual(len(read()['seats']),2)
            self.assertEqual(post('load_game',save_id=expanded)[0],200);self.assertEqual(s.core.snapshot(),snapshot)
            self.assertEqual(read()['expansion']['seats'],3)
            self.assertEqual(post('day_off')[0],200)
            self.assertEqual(s.core.day_results[-1]['summary']['expansion_expenses'],row['cost'])
            self.assertEqual(s.core.day_results[-1]['summary']['operating_cost'],row['next_operating_cost'])
        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
    def test_funds_boundary_and_legacy_single_seat(self):
        fixture=expansion_fixture.ExpansionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for funds in (499,500,501):
            s=fixture.session(funds=funds)
            with api(s,Path(self.temp.name)/str(funds)) as (read,post):
                self.assertEqual(read()['expansion']['can_expand'],funds>500)
                before=s.core.snapshot();code=post('expand_seats')[0]
                self.assertEqual(code,200 if funds>500 else 422)
                if funds<=500:self.assertEqual(s.core.snapshot(),before)
                else:self.assertEqual(s.core.funds,1)
        old=fixture.session(seats=1)
        with api(old,Path(self.temp.name)/'legacy') as (read,post):
            self.assertFalse(read()['expansion']['can_expand']);self.assertEqual(read()['expansion']['seats'],1)
            self.assertEqual(post('expand_seats')[0],422)
    def test_player_business_closed_and_required_events_block(self):
        s=self.game();cat=next(iter(s.core.cats))
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            s.dispatch(cat);s.day_off()
            self.assertFalse(read()['expansion']['can_expand']);self.assertEqual(post('expand_seats')[0],422)
            s.resolve_activity(f'dispatch-1-{cat}')
            self.assertEqual(post('player_begin',cat_id=cat)[0],200)
            self.assertFalse(read()['expansion']['can_expand']);self.assertEqual(post('expand_seats')[0],422)
            self.assertEqual(post('player_finish',cat_id=cat)[0],200)
            self.assertEqual(post('start_business')[0],200)
            before=s.core.snapshot();self.assertFalse(read()['expansion']['can_expand'])
            self.assertEqual(post('expand_seats')[0],422);self.assertEqual(s.core.snapshot(),before)
            while not s.core.closed:s.automatic_step()
            self.assertFalse(read()['expansion']['can_expand']);self.assertEqual(post('expand_seats')[0],422)
    def test_all_stages_to_eight_and_saved_maintenance(self):
        fixture=stages_fixture.EightSeatExpansionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=fixture.session
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            def purchase(count):
                row=read()['expansion'];self.assertTrue(row['can_expand'],row)
                self.assertEqual(row['next_seats'],count)
                self.assertEqual(row['cost'],next_step(s.core)['cost'])
                reference=copy.deepcopy(s);reference.expand_seats()
                code,result,_=post('expand_seats');self.assertEqual(code,200,result)
                self.assertEqual(s.core.snapshot(),reference.core.snapshot())
                self.assertEqual(len(read()['seats']),count)
                self.assertEqual(s.core.funds,row['funds_after'])
            purchase(3)
            self.assertFalse(read()['expansion']['can_expand'])
            while not s.core.closed:s.automatic_step()
            s.advance_goal();s.next_day()
            purchase(4);purchase(5)
            self.assertEqual(s.core.goal['status'],'active')
            self.assertEqual(len(s.core.goal['history']),1)
            self.assertFalse(read()['expansion']['can_expand'])
            while not s.core.closed:s.automatic_step()
            s.advance_goal();s.next_day()
            if waiting(s.core):s.resolve_reservation('decline')
            self.assertEqual(s.core.goal['status'],'active')
            self.assertEqual(len(s.core.goal['history']),2)
            purchase(6)
            purchase(7);purchase(8)
            row=read()['expansion'];self.assertFalse(row['can_expand']);self.assertFalse(row['has_next'])
            before=s.core.snapshot();self.assertEqual(post('expand_seats')[0],422);self.assertEqual(s.core.snapshot(),before)
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200)
            self.assertEqual(read()['expansion'],row)
            self.assertEqual(extra_schedule(s.core,s.core.day+1)[EIGHTH_CUSTOMER_ID],24)
            self.assertNotIn(EIGHTH_CUSTOMER_ID,extra_schedule(s.core,s.core.day))
            self.assertEqual(post('day_off')[0],200)
            self.assertEqual(s.core.operating_cost['charges'][-1]['seat_count'],8)
            self.assertEqual(s.core.operating_cost['charges'][-1]['total'],120)

    def test_single_stage_clear_unlocks_five_but_not_six(self):
        selected=starting_conditions('popularity')
        for key in ('intake_request','reservation','vip_customer','longhair_customer','play_customer','contact_customer','quiet_customer','advanced_customers','visiting_cat','dispatch_unlocks'):selected.pop(key,None)
        selected['store_events']['probability']=0
        selected['goal'].pop('stages');selected['goal']['target']=105
        selected['management']['starting_funds']=20000
        s=create_game(Path(self.temp.name)/'single-stage',selected)
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            self.assertEqual(post('expand_seats')[0],200)
            while not s.core.closed:s.automatic_step()
            s.continue_goal();s.next_day()
            self.assertEqual(post('expand_seats')[0],200)
            self.assertEqual(post('expand_seats')[0],200)
            self.assertEqual(read()['expansion']['seats'],5)
            self.assertFalse(read()['expansion']['can_expand'])
            self.assertIn('第2段階',read()['expansion']['reason'])
            saved=post('save_game')[1]['save_id']
            self.assertEqual(post('load_game',save_id=saved)[0],200)
            self.assertEqual(read()['expansion']['seats'],5)
