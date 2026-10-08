import copy
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, PropertyMock
from test_unity_dispatch_choices import api
import test_cafe_waiting_area_upgrade as fixtures
import test_unity_expansion as expansion_fixtures
from cat_cafe_sim.core.cafe_waiting_area import queue_capacity, max_wait_ticks, daily_cost, upgrade_rules
from cat_cafe_sim.core.cafe_operating_cost import estimate
from cat_cafe_sim.unity_state_server import state_view

class UnityWaitingAreaTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.WaitingUpgradeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.fixture.temp.name)
    def test_read_only_saved_rules_conditions_and_legacy(self):
        selected=dict(cost=850,queue_bonus=1,wait_bonus=3,daily_cost=13)
        s=self.fixture.session(selected=selected);before=s.core.snapshot();view=state_view(s)['waiting_area']
        self.assertEqual(s.core.snapshot(),before);self.assertEqual(view['status'],'未購入')
        self.assertEqual(view['actions'][0]['cost'],850);self.assertFalse(view['actions'][0]['can_execute']);self.assertIn('第1段階',view['actions'][0]['reason'])
        self.fixture.close(s);s.advance_goal();s.next_day();s.purchase_waiting_area()
        before=s.core.snapshot();view=state_view(s)['waiting_area'];self.assertEqual(s.core.snapshot(),before)
        self.assertEqual(view['daily_cost'],13);self.assertEqual(view['max_wait_ticks'],s.core.config.max_wait_ticks+3)
        self.assertIn('支払額 850',view['details']);self.assertFalse(view['actions'][1]['can_execute']);self.assertIn('第2段階',view['actions'][1]['reason'])
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            self.assertTrue(all(not r['can_execute'] for r in state_view(s)['waiting_area']['actions']))
        legacy=self.fixture.session(legacy=True)
        with api(legacy,self.root/'legacy') as (read,post):
            self.assertIsNone(read()['waiting_area']);self.assertEqual(post('purchase_waiting_area')[0],422);self.assertEqual(post('upgrade_waiting_area')[0],422)
    def test_http_stages_immediate_effect_retry_finance_and_save(self):
        s=self.fixture.session()
        with api(s,self.root/'saves') as (read,post):
            initial=post('save_game')[1]['save_id'];self.assertEqual(post('purchase_waiting_area')[0],422)
            saved=[];snapshots=[]
            for index,kind in enumerate(('purchase_waiting_area','upgrade_waiting_area')):
                self.fixture.close(s);s.advance_goal();s.next_day()
                row=read()['waiting_area']['actions'][index];reference=copy.deepcopy(s);getattr(reference,kind)()
                code,result,command=post(kind);self.assertEqual(code,200,result);self.assertEqual(s.core.snapshot(),reference.core.snapshot())
                self.assertEqual(s.core.funds,row['funds_after']);self.assertEqual(queue_capacity(s.core),row['capacity_after']);self.assertEqual(max_wait_ticks(s.core),row['wait_after'])
                self.assertEqual(daily_cost(s.core),row['daily_after']);self.assertEqual(estimate(s.core),row['operating_after'])
                self.assertEqual(post(kind,command)[:2],(code,result));self.assertEqual(post(kind)[0],422)
                self.assertEqual(post(kind,dict(command,request_id=uuid.uuid4().hex))[0],409)
                saved.append(post('save_game')[1]['save_id']);snapshots.append(s.core.snapshot())
            self.assertEqual(post('load_game',save_id=initial)[0],200);self.assertEqual(read()['waiting_area']['status'],'未購入')
            for save,snapshot in zip(saved,snapshots):
                self.assertEqual(post('load_game',save_id=save)[0],200);self.assertEqual(s.core.snapshot(),snapshot)
            before=estimate(s.core);reference=copy.deepcopy(s);reference.day_off();self.assertEqual(post('day_off')[0],200)
            self.assertEqual(s.core.snapshot(),reference.core.snapshot());result=s.core.day_results[-1]['summary']
            self.assertEqual(result['waiting_area_expenses'],1200);self.assertEqual(result['operating_cost'],before)
            self.assertEqual(daily_cost(s.core),20)
    def test_funds_boundaries_and_authoritative_payloads(self):
        for kind,cost,buy in (('purchase_waiting_area',800,False),('upgrade_waiting_area',upgrade_rules()['cost'],True)):
            for amount in (cost-1,cost,cost+1):
                s=self.fixture.unlocked(buy=buy);s.core.funds=amount
                with api(s,self.root/(kind+str(amount))) as (read,post):
                    before=s.core.snapshot()
                    for extra in (dict(cost=0),dict(choice='free'),dict(target_type='seat-1'),dict(cat_id=next(iter(s.core.cats))),dict(working_cats=[next(iter(s.core.cats))])):
                        self.assertIn(post(kind,**extra)[0],(400,422));self.assertEqual(before,s.core.snapshot())
                    self.assertEqual(post(kind)[0],200 if amount>cost else 422)
                    if amount>cost:self.assertEqual(s.core.funds,1)
                    else:self.assertEqual(before,s.core.snapshot())
    def test_required_events_player_business_and_closed_block(self):
        source=expansion_fixtures.UnityExpansionTests();source.setUp();self.addCleanup(source.doCleanups);s=source.game();cat=next(iter(s.core.cats))
        with api(s,self.root/'ready') as (read,post):
            s.dispatch(cat);s.day_off()
            self.assertTrue(all(not r['can_execute'] for r in read()['waiting_area']['actions']));self.assertEqual(post('purchase_waiting_area')[0],422)
            s.resolve_activity(f'dispatch-1-{cat}');self.assertEqual(post('player_begin',cat_id=cat)[0],200)
            self.assertTrue(all(not r['can_execute'] for r in read()['waiting_area']['actions']));self.assertEqual(post('purchase_waiting_area')[0],422)
            self.assertEqual(post('player_finish',cat_id=cat)[0],200);self.assertEqual(post('start_business')[0],200)
            self.assertTrue(all(not r['can_execute'] for r in read()['waiting_area']['actions']));self.assertEqual(post('upgrade_waiting_area')[0],422)
            while not s.core.closed:s.automatic_step()
            self.assertTrue(all(not r['can_execute'] for r in read()['waiting_area']['actions']));self.assertEqual(post('purchase_waiting_area')[0],422)

if __name__=='__main__':unittest.main()
