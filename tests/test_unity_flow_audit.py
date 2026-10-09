"""Cross-feature service, overlapping events and snapshot resume against Python."""
import copy
import tempfile
import unittest
from pathlib import Path
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.unity_state_server import state_view
from test_unity_dispatch_choices import api


class UnityFlowAuditTests(unittest.TestCase):
    def compare(self, session, reference):
        actual=state_view(session);expected=state_view(reference)
        for key in ('day','tick','closed','can_set_shifts','funds','required_action','objective',
                    'objective_progress','cats','finance','finance_history','business_history',
                    'housing','rest_proposal','clear_results','recruitment'):
            self.assertEqual(actual[key],expected[key],key)

    def resolve(self, session, reference, post):
        for _ in range(30):
            state=state_view(session)
            if not state['required_action']:return
            growth=state['growth_choices']
            store=state['store_event']
            intake=state['intake_request']
            if growth and any(row['can_select'] for row in growth[0]['choices']):
                row=growth[0];choice=next(c['choice'] for c in row['choices'] if c['can_select'])
                getattr(reference,row['kind'])(row['cat_id'],choice)
                code,result,_=post(row['kind'],cat_id=row['cat_id'],choice=choice)
            elif store and any(c['can_select'] and c['choice']!='close' for c in store['choices']):
                choice=next(c['choice'] for c in store['choices'] if c['can_select'] and c['choice']!='close')
                reference.resolve_store_event(choice);code,result,_=post('resolve_store_event',choice=choice)
            elif intake and intake['status']=='waiting' and intake['can_decline']:
                reference.resolve_intake_request('decline');code,result,_=post('resolve_intake',choice='decline')
            else:self.fail('Unresolved flow: '+state['required_action'])
            self.assertEqual(code,200,result);self.compare(session,reference)
        self.fail('Events did not finish')

    def test_four_modes_three_days_midday_closed_and_resume(self):
        for mode in ('popularity','patron','bond','free'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);s=create_game(root/'source',starting_conditions(mode))
                originals={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir() if p.is_file()}
                with api(s,root/'unity') as (read,post):
                    reference=copy.deepcopy(s)
                    for day in range(1,4):
                        self.resolve(s,reference,post)
                        working=[key for key,cat in s.core.cats.items() if cat.health_status=='healthy' and s.core.activity(key)=='cafe']
                        reference.set_shifts(working);self.assertEqual(post('set_shifts',working_cats=working)[0],200)
                        reference.automatic_step(auto_assign=True);code,result,command=post('start_business');self.assertEqual(code,200,result)
                        self.assertEqual(post('start_business',command)[1],result);self.compare(s,reference)
                        saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200);self.compare(s,reference)
                        while not s.core.closed:
                            self.resolve(s,reference,post);reference.automatic_step(auto_assign=True)
                            code,result,_=post('advance_business');self.assertEqual(code,200,result)
                        self.compare(s,reference);finance=read()['finance']
                        self.assertEqual(finance['opening_funds']+finance['net_cash_flow'],finance['closing_funds'])
                        saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200);self.compare(s,reference)
                        if day<3:
                            reference.next_day();self.assertEqual(post('next_day')[0],200);self.compare(s,reference)
                self.assertEqual(originals,{p:p.read_bytes() for p in originals})

    def test_overlapping_events_pending_save_answer_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=starting_conditions('free')
            settings['store_events']['probability']=1;settings['growth']['threshold']=1;settings['intake_request']['day']=2
            s=create_game(root/'source',settings)
            event=state_view(s)['store_event']
            if event:s.resolve_store_event(next(c['choice'] for c in event['choices'] if c['can_select'] and c['choice']!='close'))
            s.day_off();initial=state_view(s)
            self.assertTrue(initial['growth_choices']);self.assertIsNotNone(initial['store_event']);self.assertEqual(initial['intake_request']['status'],'waiting')
            with api(s,root/'unity') as (read,post):
                reference=copy.deepcopy(s);before=copy.deepcopy(s.core.snapshot())
                self.assertEqual(post('start_business')[0],422);self.assertEqual(before,s.core.snapshot())
                saved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=saved)[0],200);self.compare(s,reference)
                self.resolve(s,reference,post);self.assertFalse(read()['required_action'])
                reference.automatic_step(auto_assign=True);self.assertEqual(post('start_business')[0],200);self.compare(s,reference)
