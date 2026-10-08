import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from test_unity_dispatch_choices import api
from cat_cafe_sim.cafe_new_game import create_game,starting_conditions
from cat_cafe_sim.unity_state_server import state_view
import test_cafe_day_off as legacy_fixture
import test_cafe_reservation as reservation_fixture
import test_cafe_store_events as store_fixture

class UnityDayOffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def game(self):
        selected=starting_conditions('free')
        for key in ('store_events','intake_request','dispatch_unlocks'):
            selected.pop(key)
        return create_game(Path(self.temp.name)/'source',selected)
    def test_projection_cost_recovery_is_read_only(self):
        s=self.game();cat=next(iter(s.core.cats))
        s.core.cats[cat].fatigue=30;s.core.management['stress'][cat]=20
        before=s.core.snapshot();originals={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()}
        row=state_view(s)['day_off'];reference=copy.deepcopy(s);reference.day_off()
        self.assertEqual(s.core.snapshot(),before)
        self.assertTrue(row['can_select']);self.assertEqual(row['day_after'],2)
        self.assertEqual(row['funds_after'],reference.core.funds)
        self.assertEqual(row['cost'],s.core.funds-reference.core.funds)
        self.assertIn('30 →',row['details']);self.assertIn('20 →',row['details'])
        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
    def test_http_matches_python_no_arrivals_retry_and_save_resume(self):
        s=self.game()
        originals={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()}
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            prep=post('save_game')[1]['save_id'];row=read()['day_off'];reference=copy.deepcopy(s);reference.day_off()
            code,result,command=post('day_off');self.assertEqual(code,200,result)
            self.assertEqual(s.core.snapshot(),reference.core.snapshot())
            self.assertEqual(s.core.funds,row['funds_after']);self.assertEqual(s.core.day,row['day_after'])
            self.assertEqual(s.core.day_results[-1]['day_type'],'day_off')
            self.assertEqual(s.core.day_results[-1]['summary']['arrivals'],0)
            self.assertEqual(post('day_off',command)[:2],(code,result))
            self.assertEqual(len(s.core.day_results),1)
            self.assertEqual(post('day_off',dict(command,request_id=uuid.uuid4().hex))[0],409)
            rested=post('save_game')[1]['save_id'];snapshot=s.core.snapshot()
            self.assertEqual(post('load_game',save_id=prep)[0],200);self.assertEqual(s.core.day,1)
            self.assertEqual(post('load_game',save_id=rested)[0],200);self.assertEqual(s.core.snapshot(),snapshot)
            before=s.core.snapshot()
            self.assertEqual(post('day_off',working_cats=[next(iter(s.core.cats))])[0],422)
            self.assertEqual(post('day_off',choice='skip')[0],422)
            self.assertEqual(s.core.snapshot(),before)
        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
    def test_open_closed_and_player_interaction_block(self):
        s=self.game()
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            cat=next(iter(s.core.cats));self.assertEqual(post('player_begin',cat_id=cat)[0],200)
            self.assertFalse(read()['day_off']['can_select']);self.assertEqual(post('day_off')[0],422)
            self.assertEqual(post('player_finish',cat_id=cat)[0],200)
            self.assertEqual(post('start_business')[0],200)
            self.assertFalse(read()['day_off']['can_select']);before=s.core.snapshot()
            self.assertEqual(post('day_off')[0],422);self.assertEqual(s.core.snapshot(),before)
            while not s.core.closed:s.automatic_step()
            self.assertFalse(read()['day_off']['can_select']);self.assertEqual(post('day_off')[0],422)
    def test_reservation_waiting_and_accepted_day_block(self):
        fixture=reservation_fixture.ReservationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=fixture.unlock(fixture.game())
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            self.assertFalse(read()['day_off']['can_select']);self.assertEqual(post('day_off')[0],422)
            s.resolve_reservation('accept');self.assertTrue(read()['day_off']['can_select'])
            s.day_off()
            if s.core.goal['status']!='active':s.continue_goal()
            self.assertFalse(read()['day_off']['can_select']);self.assertIn('特別予約',read()['day_off']['reason'])
            self.assertEqual(post('day_off')[0],422)
    def test_store_trouble_can_close_and_pending_support_blocks(self):
        fixture=store_fixture.StoreEventTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=fixture.game();s.day_off()
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            self.assertFalse(read()['day_off']['can_select']);self.assertEqual(post('day_off')[0],422)
            s.resolve_store_event('decline');s.day_off();s.day_off()
            self.assertTrue(read()['day_off']['can_select']);self.assertIn('店舗トラブル',read()['day_off']['details'])
            reference=copy.deepcopy(s);reference.day_off()
            self.assertEqual(post('day_off')[0],200);self.assertEqual(s.core.snapshot(),reference.core.snapshot())
    def test_ending_and_legacy_without_rules(self):
        s=self.game()
        for _ in range(9):s.purchase_item()
        s.day_off()
        with api(s,Path(self.temp.name)/'saves') as (read,post):
            row=read()['day_off'];self.assertTrue(row['ends_game']);self.assertEqual(row['day_after'],2)
            self.assertEqual(post('day_off')[0],200);self.assertIsNotNone(read()['game_over'])
            self.assertEqual(s.core.day,2);self.assertEqual(post('day_off')[0],422)
            saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200)
        fixture=legacy_fixture.CafeDayOffTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        old=fixture.session(legacy=True);before=old.core.snapshot()
        self.assertTrue(state_view(old)['day_off']['can_select']);self.assertEqual(old.core.snapshot(),before)
        with api(old,Path(self.temp.name)/'legacy') as (read,post):
            self.assertEqual(post('day_off')[0],200);self.assertEqual(old.core.day,2)
            self.assertIsNotNone(old.core.shift_rules);self.assertIsNotNone(old.core.health_rules)
