import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_second_group_type_mastery as fixtures
from cat_cafe_sim.core.cafe_growth import (MASTERY_GROUPS,TYPE_GROUPS,begin_third_group_practice,
    description,learned_groups,learned_types,mastery_choices,mastery_pending,rules,service,third_mastery_pending)
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig,RelationshipInteraction,verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events


class ThirdGroupTests(unittest.TestCase):
    setUp=fixtures.SecondGroupTypeTests.setUp
    session=fixtures.SecondGroupTypeTests.session
    prepare=fixtures.SecondGroupTypeTests.prepare
    reload=fixtures.SecondGroupTypeTests.reload
    gain=fixtures.SecondGroupTypeTests.gain

    def qualify(self,s,key):
        s.start('guest-3',key,'seat-1');s.step('switch','voice')
        for _ in range(3):s.step('direct')

    def test_actual_service_pending_selection_save_resume_and_replay(self):
        for seats in (1,2):
            s,key=self.prepare(seats);self.qualify(s,key)
            self.assertEqual(third_mastery_pending(s.core),[key])
            self.assertEqual(mastery_choices(s.core,key),('quiet',))
            before=s.core.snapshot()
            for invalid in ('play','contact','unknown'):
                with self.assertRaises(ValueError):s.resolve_growth_mastery(key,invalid)
                self.assertEqual(s.core.snapshot(),before)
            for action in (s.day_off,s.next_day,s.automatic_step):
                with self.assertRaises(ValueError):action()
            s=self.reload(s);s.resolve_growth_mastery(key,'quiet')
            self.assertEqual(learned_groups(s.core.growth['cats'][key]),('play','contact','quiet'))
            self.assertIn('遊び・触れ合い・静かな交流',description(s.core,key))
            self.assertEqual(dict(cat_details(s,key)['basic'])['3つ目の得意な交流'],'静かな交流')
            self.assertIn('3つ目の得意な交流の選択',str(cat_events(s.core,key)))
            s.start('guest-4',key,'seat-1');s=self.reload(s)
            self.assertEqual(s.active_interactions['seat-1'].config.third_mastery_group,'quiet')
            s.step('switch','voice')
            for _ in range(3):s.step('direct')
            self.reload(s);self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.assertEqual(sum(e['kind']=='growth_third_mastery_ready' for e in s.core.events),1)
            self.assertEqual(sum(e['kind']=='growth_third_mastery_selected' for e in s.core.events),1)
            with self.assertRaises(ValueError):s.resolve_growth_mastery(key,'quiet')

    def test_successful_remaining_group_only_new_practice_and_no_reselection(self):
        s,key=self.prepare();row=s.core.growth['cats'][key]
        self.gain(s,key,{'voice':30});self.assertNotIn('third_group_practice',row)
        begin_third_group_practice(s.core,key)
        self.assertEqual(sum(row['third_group_practice']['groups'].values()),0)
        self.gain(s,key,{'teaser':30,'brush':30,'switch':30,'pause':30,'connect':30})
        self.gain(s,key,{'voice':30},0);self.gain(s,key,{'presence':30},-1)
        self.assertEqual(sum(row['third_group_practice']['groups'].values()),0)
        self.gain(s,key,{'voice':2});self.assertEqual(third_mastery_pending(s.core),[])
        self.gain(s,key,{'presence':1});self.assertEqual(mastery_choices(s.core,key),('quiet',))
        s.resolve_growth_mastery(key,'quiet');self.gain(s,key,{'voice':30})
        self.assertEqual(third_mastery_pending(s.core),[])
        with self.assertRaises(ValueError):begin_third_group_practice(s.core,key)
        with self.assertRaises(ValueError):s.resolve_growth_mastery(key,'play')

    def test_all_six_group_orders_and_existing_four_individual_slots(self):
        representatives={'play':'teaser','contact':'brush','quiet':'voice'}
        for first in MASTERY_GROUPS:
            for second in MASTERY_GROUPS:
                if first==second:continue
                s=self.session();key=next(iter(s.core.cats))
                self.gain(s,key,{representatives[first]:1});s.resolve_growth(key,'service');s.resolve_growth_mastery(key,first)
                self.gain(s,key,{representatives[second]:3});s.resolve_growth_mastery(key,second)
                begin_third_group_practice(s.core,key)
                remaining=next(g for g in MASTERY_GROUPS if g not in (first,second))
                self.gain(s,key,{representatives[remaining]:3})
                self.assertEqual(mastery_choices(s.core,key),(remaining,))
                s.resolve_growth_mastery(key,remaining);self.reload(s)
                self.assertEqual(learned_groups(s.core.growth['cats'][key]),(first,second,remaining))
        s,key=self.prepare()
        fixtures.SecondGroupTypeTests.qualify(self,s,key)
        s.resolve_growth_type_mastery(key,'brush')
        from cat_cafe_sim.core.cafe_growth import begin_second_group_second_type_practice
        begin_second_group_second_type_practice(s.core,key)
        self.gain(s,key,{'teaser':3});s.resolve_growth_type_mastery(key,'teaser')
        self.gain(s,key,{'ball':3});s.resolve_growth_type_mastery(key,'ball')
        self.gain(s,key,{'pet':3});s.resolve_growth_type_mastery(key,'pet')
        before=learned_types(s.core.growth['cats'][key])
        self.gain(s,key,{'voice':3});s.resolve_growth_mastery(key,'quiet')
        self.assertEqual(len(before),4);self.assertEqual(learned_types(s.core.growth['cats'][key]),before)
        self.reload(s)

    def test_multiplier_once_all_types_equipment_individual_and_relationship_replay(self):
        for remaining in MASTERY_GROUPS:
            first,second=[g for g in MASTERY_GROUPS if g!=remaining]
            for mode,group in TYPE_GROUPS.items():
                individual=next(key for key,g in TYPE_GROUPS.items() if g==first)
                base=replace(RelationshipConfig(),mastery_group=first,second_mastery_group=second,
                    mastery_engagement_multiplier=1.1,equipment_group=remaining,equipment_engagement_multiplier=1.35,
                    type_mastery=individual,type_mastery_engagement_multiplier=1.05)
                skilled=replace(base,third_mastery_group=remaining)
                a=RelationshipInteraction(base);b=RelationshipInteraction(skilled)
                if mode!='teaser':a.step('switch',mode);b.step('switch',mode)
                plain=a.step('direct');actual=b.step('direct')
                self.assertAlmostEqual(actual['engagement_delta'],plain['engagement_delta']*(1.1 if group==remaining else 1))
                self.assertEqual(actual['stamina_spent'],plain['stamina_spent']);self.assertEqual(actual['tension_delta'],plain['tension_delta'])
                self.assertNotIn('mastery_multiplier',b.step('pause')['diagnostic'])
                b.finish();self.assertEqual(verify_relationship(b.log()).result(),b.result())
                special=RelationshipInteraction(skilled,tension=100)
                self.assertNotIn('mastery_multiplier',special.step('connect')['diagnostic'])

    def test_policy_customer_priority_normal_first_group_boredom_and_rest(self):
        config=replace(RelationshipConfig(),mastery_group='play',second_mastery_group='contact',third_mastery_group='quiet',mastery_engagement_multiplier=1.1)
        policy=AutomaticInteractionPolicy()
        for flag,group in ((None,'play'),('contact_service','contact'),('quiet_service','quiet'),('play_service','play')):
            selected=replace(config,**({flag:True} if flag else {}));a=RelationshipInteraction(selected)
            action,target=policy.choose(a.observation(),a.valid_actions(),selected)
            self.assertEqual(TYPE_GROUPS[target if action=='switch' else a.state['mode']],group)
            if action=='switch':a.step(action,target)
            a.step('direct');a.step('direct')
            action,target=policy.choose(a.observation(),a.valid_actions(),selected)
            self.assertEqual(action,'switch');self.assertNotEqual(TYPE_GROUPS[target],group)
        low=RelationshipInteraction(config,stamina=10)
        self.assertEqual(policy.choose(low.observation(),low.valid_actions(),config),('pause',None))

    def test_old_save_log_and_inflight_service_only_new_start_enables(self):
        s,key=self.prepare();source=s.core.log()
        self.assertEqual(verify_cafe_interaction(source).snapshot(),s.core.snapshot());s=self.reload(s)
        self.assertNotIn('third_group_practice',s.core.growth['cats'][key])
        config=replace(s.interaction_config,mastery_group='play',second_mastery_group='contact',mastery_engagement_multiplier=1.1)
        s.core.start(self.store.begin(config,key,'guest-3',stamina=s.core.cats[key].stamina),'seat-1')
        s=self.reload(s);s.step('switch','voice')
        for _ in range(3):s.step('direct')
        self.assertNotIn('third_group_practice',s.core.growth['cats'][key])
        s.start('guest-4',key,'seat-1')
        self.assertEqual(sum(s.core.growth['cats'][key]['third_group_practice']['groups'].values()),0)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertNotIn('third_mastery_group',RelationshipInteraction(config).log()['config']['rules'])
        legacy=self.session(legacy=True)
        with self.assertRaises(ValueError):begin_third_group_practice(legacy.core,next(iter(legacy.core.cats)))

    def test_failed_start_and_persistence_retry_no_duplicate_practice(self):
        s,key=self.prepare()
        with self.assertRaises(ValueError):s.start('unknown',key,'seat-1')
        self.assertNotIn('third_group_practice',s.core.growth['cats'][key])
        s.start('guest-3',key,'seat-1');s.step('switch','voice');s.step('direct');s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        with self.assertRaises(ValueError):s.resolve_growth_mastery(key,'quiet')
        s=self.reload(s);s.persist();s.resolve_growth_mastery(key,'quiet');s=self.reload(s)
        self.assertEqual(s.core.growth['cats'][key]['third_group_practice']['groups']['quiet'],3)
        self.assertEqual(sum(e['kind']=='growth_third_mastery_ready' for e in s.core.events),1)
        self.assertEqual(sum(e['kind']=='growth_third_mastery_selected' for e in s.core.events),1)

    def test_corrupt_records_config_and_active_terms_rejected(self):
        s,key=self.prepare();self.qualify(s,key);s.resolve_growth_mastery(key,'quiet');source=checkpoint(s.core,set())
        for changes in (dict(started_day=0),dict(selected_day=True),dict(mastery='play'),dict(mastery='contact'),
                        dict(groups=dict.fromkeys(MASTERY_GROUPS,True)),dict(groups=dict.fromkeys(MASTERY_GROUPS,0)),dict(extra=True)):
            bad=copy.deepcopy(source);bad['state']['growth']['cats'][key]['third_group_practice'].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        for changes in (dict(third_mastery_group='quiet'),dict(second_mastery_group='contact',third_mastery_group='play'),dict(second_mastery_group='contact',third_mastery_group='contact')):
            with self.assertRaises(ValueError):replace(RelationshipConfig(),mastery_group='play',mastery_engagement_multiplier=1.1,**changes)
        s.start('guest-4',key,'seat-1');bad=checkpoint(s.core,set())
        bad['state']['interactions']['seat-1']['config']['rules'].pop('third_mastery_group')
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class ThirdGroupGuiTests(unittest.TestCase):
    setUp=ThirdGroupTests.setUp
    session=ThirdGroupTests.session
    prepare=ThirdGroupTests.prepare
    qualify=ThirdGroupTests.qualify

    def test_notice_choose_close_minimum_size_details_and_log(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s,key=self.prepare();self.qualify(s,key);app=CafeInteractionWindow(root,s)
        self.assertIn('3つ目の得意な交流',app.notice.get());self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke();dialog=app.growth_window
        dialog.window.geometry('540x300');root.update()
        self.assertEqual(set(dialog.choice_buttons),{'quiet'})
        button=dialog.choice_buttons['quiet'];self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.close();self.assertEqual(third_mastery_pending(s.core),[key])
        app.attention_button.invoke();app.growth_window.choice_buttons['quiet'].invoke()
        self.assertIn('遊び・触れ合い・静かな交流',app.roster.set(key,'growth'))
        self.assertIn('遊び・触れ合い・静かな交流',app.details.get())
        self.assertTrue(any('3つ目の得意な交流' in str(app.history.item(row,'values')) for row in app.history.get_children()))
