import copy
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, PropertyMock
from test_unity_dispatch_choices import api
import test_cafe_equipment as fixtures
import test_cafe_soundproof as sound_fixtures
import test_unity_expansion as expansion_fixtures
from cat_cafe_sim.core.cafe_equipment import rules, upgrade_rules, soundproof_rules
from cat_cafe_sim.core.cafe_management import rules as management_rules
from cat_cafe_sim.unity_state_server import state_view

class UnityRestSpaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.EquipmentTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.fixture.temp.name)
    def action(self,session,kind):
        return next(r for r in state_view(session)['rest_space']['actions'] if r['kind']==kind)
    def test_read_only_conditions_and_saved_effects(self):
        s=self.fixture.session();before=s.core.snapshot();view=state_view(s)['rest_space']
        self.assertEqual(before,s.core.snapshot());self.assertEqual(view['status'],'未購入')
        self.assertEqual([r['can_execute'] for r in view['actions']],[True,False,False])
        s.purchase_rest_space(dict(cost=410,recovery_bonus=12))
        before=s.core.snapshot();view=state_view(s)['rest_space'];self.assertEqual(before,s.core.snapshot())
        self.assertEqual(view['recovery_bonus'],12);self.assertIn('支払額 410',view['details'])
        self.assertFalse(view['actions'][0]['can_execute']);self.assertIn('第1段階',view['actions'][1]['reason'])
        with patch.object(type(s),'pending',new_callable=PropertyMock,return_value={'pending'}):
            self.assertTrue(all(not r['can_execute'] for r in state_view(s)['rest_space']['actions']))
    def test_http_all_stages_retries_finance_recovery_and_save(self):
        s=self.fixture.session(funds=10000)
        s.enable_management(dict(management_rules(),starting_funds=10000,stress_per_service_tick=0))
        s.enable_goal(dict(days=10,target=105,cap=300,gain_per_success=5,stages=[dict(days=10,target=110),dict(days=10,target=200)]))
        original=self.fixture.store.path.read_bytes() if hasattr(self.fixture.store,'path') else None
        with api(s,self.root/'saves') as (read,post):
            initial=post('save_game')[1]['save_id'];snapshots=[];saved=[]
            for index,kind in enumerate(('purchase_rest_space','upgrade_rest_space','soundproof_rest_space')):
                if index:
                    self.fixture.close(s);s.advance_goal();s.next_day()
                before_cats=copy.deepcopy(s.core.cats);reference=copy.deepcopy(s);getattr(reference,kind)()
                projected=next(r for r in read()['rest_space']['actions'] if r['kind']==kind)
                self.assertTrue(projected['can_execute'])
                code,result,command=post(kind);self.assertEqual(code,200,result)
                self.assertEqual(s.core.snapshot(),reference.core.snapshot());self.assertEqual(s.core.cats,before_cats)
                self.assertEqual(s.core.funds,projected['funds_after']);self.assertEqual(post(kind,command)[:2],(code,result))
                self.assertEqual(post(kind,dict(command,request_id=uuid.uuid4().hex))[0],409)
                self.assertEqual(post(kind)[0],422)
                saved.append(post('save_game')[1]['save_id']);snapshots.append(s.core.snapshot())
            self.assertEqual(read()['rest_space']['recovery_bonus'],20);self.assertEqual(read()['rest_space']['stress_recovery_bonus'],10)
            self.assertEqual(post('load_game',save_id=initial)[0],200);self.assertEqual(read()['rest_space']['status'],'未購入')
            for save,snapshot in zip(saved,snapshots):
                self.assertEqual(post('load_game',save_id=save)[0],200);self.assertEqual(s.core.snapshot(),snapshot)
            reference=copy.deepcopy(s);reference.day_off();self.assertEqual(post('day_off')[0],200)
            self.assertEqual(s.core.snapshot(),reference.core.snapshot());self.assertEqual(s.core.day_results[-1]['summary']['equipment_expenses'],1000)
        if original is not None:self.assertEqual(self.fixture.store.path.read_bytes(),original)
    def test_funds_boundary_and_invalid_payloads_for_each_action(self):
        sound=sound_fixtures.SoundproofTests();sound.setUp();self.addCleanup(sound.doCleanups)
        for kind,cost,make in (
            ('purchase_rest_space',rules()['cost'],self.fixture.session),
            ('upgrade_rest_space',upgrade_rules()['cost'],self.fixture.unlocked_upgrade),
            ('soundproof_rest_space',soundproof_rules()['cost'],sound.unlocked)):
            for amount in (cost-1,cost,cost+1):
                s=make()
                if kind=='upgrade_rest_space':s.purchase_rest_space()
                s.core.funds=amount
                with api(s,self.root/(kind+str(amount))) as (read,post):
                    before=s.core.snapshot()
                    for extra in (dict(cost=0),dict(choice='free'),dict(target_type='seat-1'),dict(cat_id='a'),dict(working_cats=['a'])):
                        self.assertIn(post(kind,**extra)[0],(400,422));self.assertEqual(before,s.core.snapshot())
                    self.assertEqual(self.action(s,kind)['can_execute'],amount>cost)
                    self.assertEqual(post(kind)[0],200 if amount>cost else 422)
                    if amount>cost:self.assertEqual(s.core.funds,1)
                    else:self.assertEqual(before,s.core.snapshot())
    def test_required_events_player_business_closed_and_legacy(self):
        source=expansion_fixtures.UnityExpansionTests();source.setUp();self.addCleanup(source.doCleanups);s=source.game();cat=next(iter(s.core.cats))
        with api(s,self.root/'ready') as (read,post):
            s.dispatch(cat);s.day_off()
            self.assertFalse(self.action(s,'purchase_rest_space')['can_execute']);self.assertEqual(post('purchase_rest_space')[0],422)
            s.resolve_activity(f'dispatch-1-{cat}');self.assertEqual(post('player_begin',cat_id=cat)[0],200)
            self.assertFalse(self.action(s,'purchase_rest_space')['can_execute']);self.assertEqual(post('purchase_rest_space')[0],422)
            self.assertEqual(post('player_finish',cat_id=cat)[0],200);self.assertEqual(post('start_business')[0],200)
            self.assertFalse(self.action(s,'purchase_rest_space')['can_execute']);self.assertEqual(post('purchase_rest_space')[0],422)
            while not s.core.closed:s.automatic_step()
            self.assertFalse(self.action(s,'purchase_rest_space')['can_execute']);self.assertEqual(post('purchase_rest_space')[0],422)
        legacy=self.fixture.session(seats=1)
        with api(legacy,self.root/'legacy') as (read,post):
            self.assertEqual(post('purchase_rest_space')[0],200);self.assertEqual(read()['rest_space']['recovery_bonus'],10)
        legacy=self.fixture.session();legacy.core.health_rules=None
        self.assertFalse(self.action(legacy,'purchase_rest_space')['can_execute'])

if __name__=='__main__':unittest.main()
