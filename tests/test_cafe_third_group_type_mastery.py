import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_third_group_mastery as third
import test_cafe_second_group_type_mastery as fixtures
from cat_cafe_sim.core.cafe_growth import (MASTERY_GROUPS,TYPE_GROUPS,begin_third_group_practice,
    begin_third_group_type_practice,description,learned_types,type_mastery_choices,type_mastery_stage,
    third_group_type_mastery_pending,interaction_terms)
from cat_cafe_sim.core.cafe_checkpoint import checkpoint,digest,restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig,RelationshipInteraction,verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events


class ThirdGroupTypeTests(unittest.TestCase):
    setUp=third.ThirdGroupTests.setUp
    session=third.ThirdGroupTests.session
    reload=third.ThirdGroupTests.reload
    gain=third.ThirdGroupTests.gain

    def prepare(self,seats=2):
        s,key=third.ThirdGroupTests.prepare(self,seats)
        third.ThirdGroupTests.qualify(self,s,key)
        s.resolve_growth_mastery(key,'quiet')
        return s,key

    def qualify(self,s,key):
        s.start('guest-4',key,'seat-1');s.step('switch','voice')
        for _ in range(3):s.step('direct')

    def test_actual_service_pending_save_select_effect_and_replay(self):
        for seats in (1,2):
            s,key=self.prepare(seats);self.qualify(s,key)
            self.assertEqual(third_group_type_mastery_pending(s.core),[key])
            self.assertEqual(type_mastery_stage(s.core,key),'third_group')
            self.assertEqual(type_mastery_choices(s.core,key),('voice',))
            for action in (s.automatic_step,s.day_off,s.next_day):
                with self.assertRaises(ValueError):action()
            s=self.reload(s);s.resolve_growth_type_mastery(key,'voice')
            self.assertEqual(learned_types(s.core.growth['cats'][key]),('voice',))
            self.assertIn('3つ目の分類（静かな交流）の得意な行動',description(s.core,key))
            self.assertIn('声をかける',dict(cat_details(s,key)['basic'])['3つ目の分類の得意な行動'])
            self.assertIn('3つ目の分類の得意な行動の選択',str(cat_events(s.core,key)))
            s.start('guest-5',key,'seat-1');s=self.reload(s)
            config=s.active_interactions['seat-1'].config
            self.assertEqual(config.third_group_type_mastery,'voice')
            self.assertEqual(config.type_mastery_engagement_multiplier,1.05)
            s.step('switch','voice')
            for _ in range(3):s.step('direct')
            self.reload(s);self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.assertEqual(sum(e['kind']=='growth_third_group_type_mastery_ready' for e in s.core.events),1)
            self.assertEqual(sum(e['kind']=='growth_third_group_type_mastery_selected' for e in s.core.events),1)

    def test_only_new_successful_normal_actions_and_one_slot(self):
        s,key=self.prepare();row=s.core.growth['cats'][key]
        before=copy.deepcopy(row['third_group_practice'])
        begin_third_group_type_practice(s.core,key)
        individual=row['third_group_practice']['individual']
        self.assertEqual(individual['actions'],dict.fromkeys(TYPE_GROUPS,0))
        self.assertEqual(row['third_group_practice']['groups'],before['groups'])
        self.gain(s,key,{'teaser':2,'brush':2,'switch':30,'pause':30,'connect':30})
        self.gain(s,key,{'voice':30},0);self.gain(s,key,{'presence':30},-1)
        self.assertEqual(sum(individual['actions'].values()),0)
        self.gain(s,key,{'voice':2});self.assertEqual(third_group_type_mastery_pending(s.core),[])
        self.gain(s,key,{'presence':1});self.assertEqual(type_mastery_choices(s.core,key),('voice','presence'))
        s.resolve_growth_type_mastery(key,'voice');self.gain(s,key,{'presence':30})
        self.assertEqual(third_group_type_mastery_pending(s.core),[])
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'presence')
        with self.assertRaises(ValueError):begin_third_group_type_practice(s.core,key)

    def test_all_group_orders_all_eight_action_candidates(self):
        representatives={'play':'teaser','contact':'brush','quiet':'voice'}
        for first in MASTERY_GROUPS:
            for second in MASTERY_GROUPS:
                if first==second:continue
                s=self.session();key=next(iter(s.core.cats))
                self.gain(s,key,{representatives[first]:1});s.resolve_growth(key,'service');s.resolve_growth_mastery(key,first)
                self.gain(s,key,{representatives[second]:3});s.resolve_growth_mastery(key,second)
                begin_third_group_practice(s.core,key)
                remaining=next(g for g in MASTERY_GROUPS if g not in (first,second))
                self.gain(s,key,{representatives[remaining]:3});s.resolve_growth_mastery(key,remaining)
                begin_third_group_type_practice(s.core,key)
                actions={key:3 for key,g in TYPE_GROUPS.items() if g==remaining}
                self.gain(s,key,actions);self.assertEqual(set(type_mastery_choices(s.core,key)),set(actions))
                s.resolve_growth_type_mastery(key,next(iter(actions)))
                self.assertEqual(len(learned_types(s.core.growth['cats'][key])),1)
                self.reload(s)

    def test_all_five_slots_and_existing_selection_priority(self):
        s,key=fixtures.SecondGroupTypeTests.prepare(self)
        fixtures.SecondGroupTypeTests.qualify(self,s,key);s.resolve_growth_type_mastery(key,'brush')
        from cat_cafe_sim.core.cafe_growth import begin_second_group_second_type_practice
        begin_second_group_second_type_practice(s.core,key)
        self.gain(s,key,{'voice':3});s.resolve_growth_mastery(key,'quiet')
        begin_third_group_type_practice(s.core,key)
        self.gain(s,key,{'teaser':3,'pet':3,'presence':3})
        self.assertEqual(type_mastery_choices(s.core,key),('teaser',));s.resolve_growth_type_mastery(key,'teaser')
        self.gain(s,key,{'ball':3});self.assertEqual(type_mastery_choices(s.core,key),('ball',));s.resolve_growth_type_mastery(key,'ball')
        self.assertEqual(type_mastery_choices(s.core,key),('pet',));s.resolve_growth_type_mastery(key,'pet')
        self.assertEqual(type_mastery_choices(s.core,key),('presence',));s.resolve_growth_type_mastery(key,'presence')
        self.assertEqual(learned_types(s.core.growth['cats'][key]),('teaser','ball','brush','pet','presence'))
        self.reload(s)

    def test_effects_all_eight_modes_once_equipment_replay_and_policy(self):
        policy=AutomaticInteractionPolicy()
        for kind,group in TYPE_GROUPS.items():
            first,second=[g for g in MASTERY_GROUPS if g!=group]
            base=replace(RelationshipConfig(),mastery_group=first,second_mastery_group=second,third_mastery_group=group,
                mastery_engagement_multiplier=1.1,equipment_group=group,equipment_engagement_multiplier=1.35)
            config=replace(base,third_group_type_mastery=kind,type_mastery_engagement_multiplier=1.05)
            for mode in TYPE_GROUPS:
                a=RelationshipInteraction(base);b=RelationshipInteraction(config)
                if mode!='teaser':a.step('switch',mode);b.step('switch',mode)
                plain=a.step('direct');actual=b.step('direct')
                self.assertAlmostEqual(actual['engagement_delta'],plain['engagement_delta']*(1.05 if mode==kind else 1))
                self.assertEqual(actual['stamina_spent'],plain['stamina_spent']);self.assertEqual(actual['tension_delta'],plain['tension_delta'])
                self.assertNotIn('type_mastery_multiplier',b.step('pause')['diagnostic'])
                b.finish();self.assertEqual(verify_relationship(b.log()).result(),b.result())
            flag={'play':'play_service','contact':'contact_service','quiet':'quiet_service'}[group]
            for learned in ({},dict(type_mastery=next(k for k,g in TYPE_GROUPS.items() if g==first))):
                selected=replace(config,**{flag:True},**learned);active=RelationshipInteraction(selected)
                action,target=policy.choose(active.observation(),active.valid_actions(),selected)
                self.assertEqual(target if action=='switch' else active.state['mode'],kind)
                if action=='switch':active.step(action,target)
                active.step('direct');active.step('direct')
                action,target=policy.choose(active.observation(),active.valid_actions(),selected)
                self.assertEqual(action,'switch');self.assertNotEqual(TYPE_GROUPS[target],group)
            low=RelationshipInteraction(config,stamina=10)
            self.assertEqual(policy.choose(low.observation(),low.valid_actions(),config),('pause',None))
            special=RelationshipInteraction(config,tension=100)
            self.assertNotIn('type_mastery_multiplier',special.step('connect')['diagnostic'])

    def test_legacy_save_log_and_old_inflight_unchanged_until_new_start(self):
        s,key=self.prepare();source=s.core.log();self.assertEqual(verify_cafe_interaction(source).snapshot(),s.core.snapshot())
        s=self.reload(s);self.assertNotIn('individual',s.core.growth['cats'][key]['third_group_practice'])
        terms=interaction_terms(s.core,key)
        config=replace(s.interaction_config,mastery_group=terms['group'],second_mastery_group=terms['second_group'],third_mastery_group=terms['third_group'],mastery_engagement_multiplier=terms['multiplier'])
        s.core.start(self.store.begin(config,key,'guest-4',stamina=s.core.cats[key].stamina),'seat-1')
        s=self.reload(s);s.step('switch','voice')
        for _ in range(3):s.step('direct')
        self.assertNotIn('individual',s.core.growth['cats'][key]['third_group_practice'])
        s.start('guest-5',key,'seat-1')
        self.assertEqual(sum(s.core.growth['cats'][key]['third_group_practice']['individual']['actions'].values()),0)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertNotIn('third_group_type_mastery',RelationshipInteraction(config).log()['config']['rules'])

    def test_failed_start_and_pending_write_retry_no_duplicate(self):
        s,key=self.prepare()
        with self.assertRaises(ValueError):s.start('unknown',key,'seat-1')
        self.assertNotIn('individual',s.core.growth['cats'][key]['third_group_practice'])
        s.start('guest-4',key,'seat-1');s.step('switch','voice');s.step('direct');s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'voice')
        s=self.reload(s);s.persist();s.resolve_growth_type_mastery(key,'voice');s=self.reload(s)
        self.assertEqual(s.core.growth['cats'][key]['third_group_practice']['individual']['actions']['voice'],3)
        self.assertEqual(sum(e['kind']=='growth_third_group_type_mastery_selected' for e in s.core.events),1)

    def test_corrupt_records_and_active_terms_rejected(self):
        s,key=self.prepare();self.qualify(s,key);s.resolve_growth_type_mastery(key,'voice');source=checkpoint(s.core,set())
        for changes in (dict(started_day=0),dict(selected_day=True),dict(type_mastery='teaser'),dict(type_mastery='presence'),
                        dict(actions=dict.fromkeys(TYPE_GROUPS,True)),dict(actions=dict.fromkeys(TYPE_GROUPS,0)),dict(extra=True)):
            bad=copy.deepcopy(source);bad['state']['growth']['cats'][key]['third_group_practice']['individual'].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        for changes in (dict(third_group_type_mastery='presence'),dict(third_mastery_group='quiet',third_group_type_mastery='teaser')):
            with self.assertRaises(ValueError):replace(RelationshipConfig(),mastery_group='play',second_mastery_group='contact',mastery_engagement_multiplier=1.1,type_mastery_engagement_multiplier=1.05,**changes)
        s.start('guest-5',key,'seat-1');bad=checkpoint(s.core,set())
        bad['state']['interactions']['seat-1']['config']['rules'].pop('third_group_type_mastery')
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class ThirdGroupTypeGuiTests(unittest.TestCase):
    setUp=ThirdGroupTypeTests.setUp
    session=ThirdGroupTypeTests.session
    prepare=ThirdGroupTypeTests.prepare
    qualify=ThirdGroupTypeTests.qualify

    def test_notice_selection_close_details_history_and_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s,key=self.prepare();self.qualify(s,key);app=CafeInteractionWindow(root,s)
        self.assertIn('3つ目の分類の個別行動',app.notice.get());self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke();dialog=app.growth_window;dialog.window.geometry('540x300');root.update()
        self.assertEqual(set(dialog.choice_buttons),{'voice'})
        button=dialog.choice_buttons['voice'];self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.close();self.assertEqual(third_group_type_mastery_pending(s.core),[key])
        app.attention_button.invoke();app.growth_window.choice_buttons['voice'].invoke()
        self.assertIn('声をかける',app.roster.set(key,'growth'))
        self.assertIn('3つ目の分類（静かな交流）の得意な行動',app.details.get())
        self.assertTrue(any('3つ目の分類の得意な行動' in str(app.history.item(row,'values')) for row in app.history.get_children()))
