import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_second_group_type_mastery as fixtures
from cat_cafe_sim.core.cafe_growth import (
    TYPE_GROUPS, begin_second_group_second_type_practice, description, learned_types,
    second_group_second_type_mastery_pending, type_mastery_choices, type_mastery_stage,
)
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events


class AdditionalSecondGroupTests(unittest.TestCase):
    setUp = fixtures.SecondGroupTypeTests.setUp
    session = fixtures.SecondGroupTypeTests.session
    prepare = fixtures.SecondGroupTypeTests.prepare
    qualify = fixtures.SecondGroupTypeTests.qualify
    gain = fixtures.SecondGroupTypeTests.gain
    reload = fixtures.SecondGroupTypeTests.reload

    def skilled(self, seats=2):
        s, key = self.prepare(seats)
        self.qualify(s, key)
        s.resolve_growth_type_mastery(key, 'brush')
        return s, key

    def qualify_extra(self, s, key):
        s.start('guest-4', key, 'seat-1')
        s.step('switch', 'pet')
        for _ in range(3):
            s.step('direct')

    def test_actual_service_pending_selection_save_and_replay(self):
        for seats in (1, 2):
            s, key = self.skilled(seats)
            self.qualify_extra(s, key)
            self.assertEqual(second_group_second_type_mastery_pending(s.core), [key])
            self.assertEqual(type_mastery_stage(s.core, key), 'second_group_second')
            self.assertEqual(type_mastery_choices(s.core, key), ('pet',))
            for action in (s.automatic_step, s.day_off, s.next_day):
                with self.assertRaises(ValueError): action()
            s = self.reload(s)
            s.resolve_growth_type_mastery(key, 'pet')
            self.assertEqual(learned_types(s.core.growth['cats'][key]), ('brush', 'pet'))
            self.assertIn('なでる', description(s.core, key))
            self.assertEqual(dict(cat_details(s, key)['basic'])['2つ目の分類の追加の得意な行動'], 'なでる')
            self.assertIn('追加の得意な行動の選択', str(cat_events(s.core, key)))
            s.start('guest-5', key, 'seat-1')
            s = self.reload(s)
            self.assertEqual(s.active_interactions['seat-1'].config.second_group_second_type_mastery, 'pet')
            s.step('switch', 'pet')
            for _ in range(3): s.step('direct')
            s = self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
            self.assertEqual(sum(e['kind']=='growth_second_group_second_type_mastery_ready' for e in s.core.events), 1)

    def test_successful_unlearned_actions_only_and_no_third_slot(self):
        s, key = self.skilled()
        begin_second_group_second_type_practice(s.core, key)
        extra=s.core.growth['cats'][key]['second_group_type_practice']['second']
        self.gain(s, key, {'brush':30, 'voice':30, 'switch':30, 'pause':30, 'connect':30})
        self.gain(s, key, {'pet':30}, 0)
        self.gain(s, key, {'pet':30}, -1)
        self.assertEqual(sum(extra['actions'].values()), 0)
        self.gain(s, key, {'pet':2})
        self.assertEqual(type_mastery_choices(s.core, key), ())
        self.gain(s, key, {'pet':1})
        self.assertEqual(type_mastery_choices(s.core, key), ('pet',))
        with self.assertRaises(ValueError): s.resolve_growth_type_mastery(key, 'brush')
        s.resolve_growth_type_mastery(key, 'pet')
        self.gain(s, key, {'pet':30})
        self.assertEqual(second_group_second_type_mastery_pending(s.core), [])
        with self.assertRaises(ValueError): s.resolve_growth_type_mastery(key, 'pet')

    def test_four_slots_and_first_category_order_preserved(self):
        s, key = self.skilled()
        begin_second_group_second_type_practice(s.core, key)
        self.gain(s, key, {'teaser':3, 'pet':3})
        self.assertEqual(type_mastery_choices(s.core, key), ('teaser',))
        s.resolve_growth_type_mastery(key, 'teaser')
        self.gain(s, key, {'ball':3})
        self.assertEqual(type_mastery_choices(s.core, key), ('ball',))
        s.resolve_growth_type_mastery(key, 'ball')
        self.assertEqual(type_mastery_choices(s.core, key), ('pet',))
        s.resolve_growth_type_mastery(key, 'pet')
        self.assertEqual(learned_types(s.core.growth['cats'][key]), ('teaser', 'ball', 'brush', 'pet'))
        self.reload(s)

    def test_all_action_pairs_single_multiplier_and_relationship_replay(self):
        for first, group in TYPE_GROUPS.items():
            for second, second_group in TYPE_GROUPS.items():
                if group!=second_group or first==second: continue
                base=replace(RelationshipConfig(), mastery_group='contact' if group=='play' else 'play',
                    second_mastery_group=group, mastery_engagement_multiplier=1.1,
                    equipment_group=group, equipment_engagement_multiplier=1.35)
                skilled=replace(base, second_group_type_mastery=first, second_group_second_type_mastery=second,
                    type_mastery_engagement_multiplier=1.05)
                for mode in TYPE_GROUPS:
                    a=RelationshipInteraction(base);b=RelationshipInteraction(skilled)
                    if mode!='teaser': a.step('switch', mode);b.step('switch', mode)
                    plain=a.step('direct');actual=b.step('direct')
                    self.assertAlmostEqual(actual['engagement_delta'], plain['engagement_delta']*(1.05 if mode in (first,second) else 1))
                    self.assertEqual(actual['stamina_spent'], plain['stamina_spent'])
                    self.assertEqual(actual['tension_delta'], plain['tension_delta'])
                    self.assertNotIn('type_mastery_multiplier', b.step('pause')['diagnostic'])
                    b.finish();self.assertEqual(verify_relationship(b.log()).result(), b.result())

    def test_policy_four_slots_customer_priority_boredom_and_rest(self):
        config=replace(RelationshipConfig(), mastery_group='play',second_mastery_group='contact',mastery_engagement_multiplier=1.1,
            type_mastery='teaser',second_type_mastery='ball',second_group_type_mastery='brush',
            second_group_second_type_mastery='pet',type_mastery_engagement_multiplier=1.05)
        policy=AutomaticInteractionPolicy()
        for flag,group in ((None,'play'),('contact_service','contact'),('quiet_service','quiet')):
            selected=replace(config, **({flag:True} if flag else {}))
            a=RelationshipInteraction(selected)
            action,target=policy.choose(a.observation(),a.valid_actions(),selected)
            chosen=target if action=='switch' else a.state['mode']
            self.assertEqual(TYPE_GROUPS[chosen],group)
            if group=='contact':self.assertIn(chosen,('brush','pet'))
            if action=='switch':a.step(action,target)
            a.step('direct');a.step('direct')
            action,target=policy.choose(a.observation(),a.valid_actions(),selected)
            self.assertEqual(action,'switch');self.assertNotEqual(TYPE_GROUPS[target],group)
        low=RelationshipInteraction(config,stamina=10)
        self.assertEqual(policy.choose(low.observation(),low.valid_actions(),config),('pause',None))

    def test_legacy_save_and_inflight_service_only_new_start_enables(self):
        s,key=self.skilled()
        source=s.core.log()
        self.assertEqual(verify_cafe_interaction(source).snapshot(),s.core.snapshot())
        s=self.reload(s)
        practice=s.core.growth['cats'][key]['second_group_type_practice']
        self.assertNotIn('second',practice)
        # Reconstruct an old session's in-flight service without the new opt-in operation.
        from cat_cafe_sim.core.cafe_growth import interaction_terms
        terms=interaction_terms(s.core,key)
        config=replace(s.interaction_config,mastery_group=terms['group'],second_mastery_group=terms['second_group'],
            mastery_engagement_multiplier=terms['multiplier'],second_group_type_mastery='brush',type_mastery_engagement_multiplier=1.05)
        s.core.start(self.store.begin(config,key,'guest-4',stamina=s.core.cats[key].stamina),'seat-1')
        s=self.reload(s);s.step('switch','pet')
        for _ in range(3):s.step('direct')
        self.assertNotIn('second',s.core.growth['cats'][key]['second_group_type_practice'])
        s.start('guest-5',key,'seat-1')
        self.assertEqual(sum(s.core.growth['cats'][key]['second_group_type_practice']['second']['actions'].values()),0)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertNotIn('second_group_second_type_mastery', RelationshipInteraction(config).log()['config']['rules'])

    def test_failed_start_and_write_retry_no_duplicate_practice(self):
        s,key=self.skilled()
        with self.assertRaises(ValueError):s.start('unknown',key,'seat-1')
        self.assertNotIn('second',s.core.growth['cats'][key]['second_group_type_practice'])
        s.start('guest-4',key,'seat-1');s.step('switch','pet');s.step('direct');s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'pet')
        s=self.reload(s);s.persist();s.resolve_growth_type_mastery(key,'pet');s=self.reload(s)
        self.assertEqual(s.core.growth['cats'][key]['second_group_type_practice']['second']['actions']['pet'],3)
        self.assertEqual(sum(e['kind']=='growth_second_group_second_type_mastery_selected' for e in s.core.events),1)

    def test_invalid_records_and_active_terms(self):
        s,key=self.skilled();self.qualify_extra(s,key);s.resolve_growth_type_mastery(key,'pet')
        source=checkpoint(s.core,set())
        for changes in (dict(started_day=0),dict(selected_day=True),dict(type_mastery='brush'),dict(type_mastery='teaser'),
                        dict(actions=dict.fromkeys(TYPE_GROUPS,True)),dict(actions=dict.fromkeys(TYPE_GROUPS,0)),dict(extra=True)):
            bad=copy.deepcopy(source);bad['state']['growth']['cats'][key]['second_group_type_practice']['second'].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        for changes in (dict(second_group_second_type_mastery='pet'),dict(second_group_type_mastery='brush',second_group_second_type_mastery='brush'),
                        dict(second_group_type_mastery='brush',second_group_second_type_mastery='teaser')):
            with self.assertRaises(ValueError):replace(RelationshipConfig(),mastery_group='play',second_mastery_group='contact',
                mastery_engagement_multiplier=1.1,type_mastery_engagement_multiplier=1.05,**changes)
        s.start('guest-5',key,'seat-1');bad=checkpoint(s.core,set())
        bad['state']['interactions']['seat-1']['config']['rules'].pop('second_group_second_type_mastery')
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class AdditionalSecondGroupGuiTests(unittest.TestCase):
    setUp=AdditionalSecondGroupTests.setUp
    session=AdditionalSecondGroupTests.session
    prepare=AdditionalSecondGroupTests.prepare
    qualify=AdditionalSecondGroupTests.qualify
    skilled=AdditionalSecondGroupTests.skilled
    qualify_extra=AdditionalSecondGroupTests.qualify_extra

    def test_notice_choice_details_history_minimum_size_and_close(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s,key=self.skilled();self.qualify_extra(s,key)
        app=CafeInteractionWindow(root,s)
        self.assertIn('2つ目の分類の追加個別行動',app.notice.get())
        self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke();dialog=app.growth_window
        dialog.window.geometry('540x300');root.update()
        self.assertEqual(set(dialog.choice_buttons),{'pet'})
        button=dialog.choice_buttons['pet']
        self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),dialog.window.winfo_rooty()+dialog.window.winfo_height())
        dialog.close();self.assertEqual(second_group_second_type_mastery_pending(s.core),[key])
        app.attention_button.invoke();app.growth_window.choice_buttons['pet'].invoke()
        self.assertIn('なでる',app.roster.set(key,'growth'))
        self.assertIn('ブラッシング・なでる',app.details.get())
        self.assertEqual(second_group_second_type_mastery_pending(s.core),[])
