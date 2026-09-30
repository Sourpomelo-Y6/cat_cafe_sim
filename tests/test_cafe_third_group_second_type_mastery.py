import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_third_group_type_mastery as fixtures
from cat_cafe_sim.core.cafe_growth import (TYPE_GROUPS, MASTERY_GROUPS, begin_third_group_second_type_practice,
    begin_third_group_practice, begin_third_group_type_practice, third_group_second_type_mastery_pending,
    type_mastery_choices, type_mastery_stage, learned_types, interaction_terms, description)
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events


class AdditionalThirdGroupTests(unittest.TestCase):
    setUp=fixtures.ThirdGroupTypeTests.setUp
    session=fixtures.ThirdGroupTypeTests.session
    prepare=fixtures.ThirdGroupTypeTests.prepare
    qualify=fixtures.ThirdGroupTypeTests.qualify
    gain=fixtures.ThirdGroupTypeTests.gain
    reload=fixtures.ThirdGroupTypeTests.reload

    def skilled(self,seats=2):
        s,key=self.prepare(seats);self.qualify(s,key);s.resolve_growth_type_mastery(key,'voice')
        s.interaction_config=replace(s.interaction_config,confused_threshold=1,favorable_threshold=2)
        return s,key

    def qualify_extra(self,s,key):
        s.start('guest-5',key,'seat-1');s.step('switch','presence')
        for _ in range(3):s.step('direct')

    def test_actual_service_save_pending_selection_and_replay(self):
        for seats in (1,2):
            s,key=self.skilled(seats);self.qualify_extra(s,key)
            self.assertEqual(third_group_second_type_mastery_pending(s.core),[key])
            self.assertEqual(type_mastery_stage(s.core,key),'third_group_second')
            self.assertEqual(type_mastery_choices(s.core,key),('presence',))
            for action in (s.automatic_step,s.day_off,s.next_day):
                with self.assertRaises(ValueError):action()
            s=self.reload(s);s.resolve_growth_type_mastery(key,'presence')
            self.assertEqual(learned_types(s.core.growth['cats'][key]),('voice','presence'))
            self.assertIn('そばで見守る',description(s.core,key))
            self.assertEqual(dict(cat_details(s,key)['basic'])['3つ目の分類の追加の得意な行動'],'そばで見守る')
            self.assertIn('3つ目の分類の追加の得意な行動の選択',str(cat_events(s.core,key)))
            self.reload(s);self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.assertEqual(sum(e['kind']=='growth_third_group_second_type_mastery_ready' for e in s.core.events),1)
            self.assertEqual(sum(e['kind']=='growth_third_group_second_type_mastery_selected' for e in s.core.events),1)
            terms=interaction_terms(s.core,key)
            self.assertEqual(terms['third_group_second_type'],'presence')

    def test_new_successful_unlearned_normal_actions_and_maximum(self):
        s,key=self.skilled();row=s.core.growth['cats'][key]
        self.gain(s,key,{'presence':20});begin_third_group_second_type_practice(s.core,key)
        extra=row['third_group_practice']['individual']['second']
        self.gain(s,key,{'voice':20,'brush':2,'teaser':2,'pause':30,'switch':30,'connect':30})
        self.gain(s,key,{'presence':30},0);self.gain(s,key,{'presence':30},-1)
        self.assertEqual(sum(extra['actions'].values()),0)
        self.gain(s,key,{'presence':2});self.assertEqual(third_group_second_type_mastery_pending(s.core),[])
        self.gain(s,key,{'presence':1});self.assertEqual(type_mastery_choices(s.core,key),('presence',))
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'voice')
        s.resolve_growth_type_mastery(key,'presence');self.gain(s,key,{'presence':30})
        self.assertEqual(third_group_second_type_mastery_pending(s.core),[])
        with self.assertRaises(ValueError):begin_third_group_second_type_practice(s.core,key)
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'presence')

    def test_all_orders_and_candidates_saved_threshold(self):
        representative={'play':'teaser','contact':'brush','quiet':'voice'}
        for first in MASTERY_GROUPS:
            for second in MASTERY_GROUPS:
                if first==second:continue
                s=self.session();key=next(iter(s.core.cats));group=next(g for g in MASTERY_GROUPS if g not in (first,second))
                self.gain(s,key,{representative[first]:1});s.resolve_growth(key,'service');s.resolve_growth_mastery(key,first)
                self.gain(s,key,{representative[second]:3});s.resolve_growth_mastery(key,second)
                begin_third_group_practice(s.core,key);self.gain(s,key,{representative[group]:3});s.resolve_growth_mastery(key,group)
                begin_third_group_type_practice(s.core,key);self.gain(s,key,{representative[group]:3});s.resolve_growth_type_mastery(key,representative[group])
                begin_third_group_second_type_practice(s.core,key)
                s.core.growth['rules']['second_type_mastery_threshold']=5
                candidates={k:4 for k,g in TYPE_GROUPS.items() if g==group and k!=representative[group]}
                # Exactly four successful actions remain below the saved custom threshold.
                target=next(iter(candidates));self.gain(s,key,{target:4})
                self.assertEqual(third_group_second_type_mastery_pending(s.core),[])
                self.gain(s,key,{k:1 for k in candidates});self.assertEqual(set(type_mastery_choices(s.core,key)),set(candidates))
                s.resolve_growth_type_mastery(key,target);self.reload(s)

    def test_six_slots_preserved(self):
        s,key=self.skilled()
        from cat_cafe_sim.core.cafe_growth import begin_second_group_second_type_practice
        self.gain(s,key,{'brush':3});s.resolve_growth_type_mastery(key,'brush')
        begin_second_group_second_type_practice(s.core,key);begin_third_group_second_type_practice(s.core,key)
        self.gain(s,key,{'teaser':3,'pet':3,'presence':3})
        for action in ('teaser','ball','pet','presence'):
            if action=='ball':self.gain(s,key,{'ball':3})
            self.assertEqual(type_mastery_choices(s.core,key),(action,));s.resolve_growth_type_mastery(key,action)
        self.assertEqual(learned_types(s.core.growth['cats'][key]),('teaser','ball','brush','pet','voice','presence'))
        self.reload(s)

    def test_effect_and_automatic_comparison_all_groups(self):
        policy=AutomaticInteractionPolicy()
        for group in MASTERY_GROUPS:
            kinds=[k for k,g in TYPE_GROUPS.items() if g==group];first,second=[g for g in MASTERY_GROUPS if g!=group]
            for selected in kinds[1:]:
                base=replace(RelationshipConfig(),mastery_group=first,second_mastery_group=second,third_mastery_group=group,
                    mastery_engagement_multiplier=1.1,third_group_type_mastery=kinds[0],type_mastery_engagement_multiplier=1.05,
                    equipment_group=group,equipment_engagement_multiplier=1.35)
                config=replace(base,third_group_second_type_mastery=selected)
                for mode in TYPE_GROUPS:
                    plain=RelationshipInteraction(base);active=RelationshipInteraction(config)
                    if mode!='teaser':plain.step('switch',mode);active.step('switch',mode)
                    a=plain.step('direct');b=active.step('direct')
                    self.assertAlmostEqual(b['engagement_delta'],a['engagement_delta']*(1.05 if mode==selected else 1))
                    self.assertEqual(b['stamina_spent'],a['stamina_spent']);self.assertEqual(b['tension_delta'],a['tension_delta'])
                    self.assertNotIn('type_mastery_multiplier',active.step('pause')['diagnostic'])
                    active.finish();self.assertEqual(verify_relationship(active.log()).result(),active.result())
                flag={'play':'play_service','contact':'contact_service','quiet':'quiet_service'}[group]
                config=replace(config,**{flag:True})
                active=RelationshipInteraction(config)
                expected=max((kinds[0],selected),key=lambda k:next(t.gain for t in config.types if t.id==k)*config.personality.type_preferences[list(TYPE_GROUPS).index(k)])
                action,target=policy.choose(active.observation(),active.valid_actions(),config)
                self.assertEqual(target if action=='switch' else active.state['mode'],expected)
                if action=='switch':active.step(action,target)
                active.step('direct');active.step('direct')
                action,target=policy.choose(active.observation(),active.valid_actions(),config)
                self.assertEqual(action,'switch');self.assertNotEqual(TYPE_GROUPS[target],group)
                low=RelationshipInteraction(config,stamina=10)
                self.assertEqual(policy.choose(low.observation(),low.valid_actions(),config),('pause',None))
                special=RelationshipInteraction(config,tension=100)
                self.assertNotIn('type_mastery_multiplier',special.step('connect')['diagnostic'])

    def test_old_save_log_inflight_and_failed_start(self):
        s,key=self.skilled();s=self.reload(s);individual=s.core.growth['cats'][key]['third_group_practice']['individual']
        self.assertNotIn('second',individual)
        with self.assertRaises(ValueError):s.start('unknown',key,'seat-1')
        self.assertNotIn('second',individual)
        terms=interaction_terms(s.core,key)
        config=replace(s.interaction_config,mastery_group=terms['group'],second_mastery_group=terms['second_group'],third_mastery_group=terms['third_group'],
            mastery_engagement_multiplier=terms['multiplier'],third_group_type_mastery=terms['third_group_type'],type_mastery_engagement_multiplier=terms['type_multiplier'])
        s.core.start(self.store.begin(config,key,'guest-5',stamina=s.core.cats[key].stamina),'seat-1')
        s=self.reload(s);s.step('switch','presence')
        for _ in range(3):s.step('direct')
        self.assertNotIn('second',s.core.growth['cats'][key]['third_group_practice']['individual'])
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertNotIn('third_group_second_type_mastery',RelationshipInteraction(config).log()['config']['rules'])

    def test_write_retry_and_corrupt_records(self):
        s,key=self.skilled();s.start('guest-5',key,'seat-1');s.step('switch','presence');s.step('direct');s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'presence')
        s=self.reload(s);s.persist();s.resolve_growth_type_mastery(key,'presence');s=self.reload(s)
        extra=s.core.growth['cats'][key]['third_group_practice']['individual']['second']
        self.assertEqual(extra['actions']['presence'],3)
        source=checkpoint(s.core,set())
        for changes in (dict(started_day=0),dict(selected_day=True),dict(type_mastery='voice'),dict(type_mastery='teaser'),
                        dict(actions=dict.fromkeys(TYPE_GROUPS,True)),dict(actions=dict.fromkeys(TYPE_GROUPS,0)),dict(extra=True)):
            bad=copy.deepcopy(source);bad['state']['growth']['cats'][key]['third_group_practice']['individual']['second'].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        for changes in (dict(third_group_second_type_mastery='presence'),dict(third_group_second_type_mastery=True),
                        dict(third_group_type_mastery='voice',third_group_second_type_mastery='voice'),
                        dict(third_group_type_mastery='voice',third_group_second_type_mastery='teaser')):
            with self.assertRaises(ValueError):replace(RelationshipConfig(),mastery_group='play',second_mastery_group='contact',third_mastery_group='quiet',mastery_engagement_multiplier=1.1,type_mastery_engagement_multiplier=1.05,**changes)

    def test_new_service_freezes_both_terms_and_rejects_missing_active_term(self):
        s,key=self.skilled();begin_third_group_second_type_practice(s.core,key)
        self.gain(s,key,{'presence':3});s.resolve_growth_type_mastery(key,'presence')
        s.start('guest-5',key,'seat-1');s=self.reload(s)
        config=s.active_interactions['seat-1'].config
        self.assertEqual((config.third_group_type_mastery,config.third_group_second_type_mastery),('voice','presence'))
        bad=checkpoint(s.core,set());bad['state']['interactions']['seat-1']['config']['rules'].pop('third_group_second_type_mastery')
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)
        s.step('switch','presence')
        for _ in range(3):s.step('direct')
        self.reload(s);self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())



@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class AdditionalThirdGroupGuiTests(unittest.TestCase):
    setUp=AdditionalThirdGroupTests.setUp
    session=AdditionalThirdGroupTests.session
    prepare=AdditionalThirdGroupTests.prepare
    qualify=AdditionalThirdGroupTests.qualify
    skilled=AdditionalThirdGroupTests.skilled
    qualify_extra=AdditionalThirdGroupTests.qualify_extra

    def test_notice_selection_close_details_history_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s,key=self.skilled();self.qualify_extra(s,key);app=CafeInteractionWindow(root,s)
        self.assertIn('3つ目の分類の追加個別行動',app.notice.get());self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke();dialog=app.growth_window;dialog.window.geometry('540x300');root.update()
        self.assertEqual(set(dialog.choice_buttons),{'presence'})
        button=dialog.choice_buttons['presence'];self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.close();self.assertEqual(third_group_second_type_mastery_pending(s.core),[key])
        app.attention_button.invoke();app.growth_window.choice_buttons['presence'].invoke()
        self.assertIn('そばで見守る',app.roster.set(key,'growth'));self.assertIn('声をかける・そばで見守る',app.details.get())
        self.assertTrue(any('3つ目の分類の追加の得意な行動' in str(app.history.item(row,'values')) for row in app.history.get_children()))
