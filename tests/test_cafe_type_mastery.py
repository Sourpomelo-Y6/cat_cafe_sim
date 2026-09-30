import copy
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_growth import (blank, description, interaction_terms, rules, service, summary,
    type_mastery_choices, type_mastery_pending, TYPE_GROUPS)
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.storage.cafe_saves import load_game, save_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class TypeMasteryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relationships.json'); add_playtest_cats(self.store)
        self.path=Path(self.temp.name)/'game.json'

    def session(self, legacy=False):
        s=CafeInteractionSession(store=self.store,seat_count=2,
            cafe_config=replace(Config.load(),opening_ticks=12,arrival_ticks=(0,1,2)),
            interaction_config=replace(RelationshipConfig(),ticks=1))
        selected=dict(rules(),threshold=1,mastery_threshold=1,type_mastery_threshold=1)
        if legacy:
            selected.pop('type_mastery_threshold'); selected.pop('type_mastery_engagement_multiplier'); selected.pop('second_type_mastery_threshold')
        s.core.initialize_growth(selected)
        return s

    def prepare(self):
        s=self.session(); key=next(iter(s.core.cats))
        s.step(); s.start('guest-1',key,'seat-1'); s.step('direct')
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        self.assertEqual(sum(s.core.growth['cats'][key]['type_mastery_actions'].values()),0)
        s.start('guest-2',key,'seat-1'); s.step('direct')
        return s,key

    def reload(self,s):
        save_game(s,self.path); loaded,_=load_game(self.path)
        self.assertEqual(s.core.snapshot(),loaded.core.snapshot())
        return loaded

    def test_selection_blocks_progress_and_survives_pending_and_active_saves(self):
        s,key=self.prepare()
        self.assertEqual(type_mastery_pending(s.core),[key])
        self.assertEqual(type_mastery_choices(s.core,key),('teaser',))
        before=s.core.snapshot()
        for choice in ('brush','ball','invalid'):
            with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,choice)
            self.assertEqual(before,s.core.snapshot())
        for action in (s.automatic_step,s.next_day,s.day_off):
            with self.assertRaisesRegex(ValueError,'得意な行動'):action()
        with patch('cat_cafe_sim.core.cafe_growth.rules',side_effect=lambda data:rules(data)):
            s=self.reload(s)
        s.resolve_growth_type_mastery(key,'teaser')
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'teaser')
        self.assertIn('ねこじゃらし',summary(s.core,key))
        self.assertIn('×1.05',description(s.core,key))
        self.assertEqual(dict(cat_details(s,key)['basic'])['得意な行動'],'ねこじゃらし')
        self.assertIn('得意な行動の選択',str(cat_events(s.core,key)))
        s.start('guest-3',key,'seat-1'); self.assertEqual(s.active_interactions['seat-1'].config.type_mastery,'teaser')
        s=self.reload(s); s.step('direct'); self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertEqual(sum(e['kind']=='growth_type_mastery_selected' for e in s.core.events),1)

    def test_only_successful_normal_actions_after_group_selection_qualify(self):
        s=self.session(); key=next(iter(s.core.cats)); row=s.core.growth['cats'][key]
        def gain(actions,affinity=1):
            service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=affinity,type_actions=actions))
        gain({'pet':3})
        self.assertEqual(sum(row['type_mastery_actions'].values()),0)
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'contact')
        gain({'pet':3},0); gain({'brush':2},-1); gain({'teaser':4}); gain({})
        self.assertEqual(sum(row['type_mastery_actions'].values()),0)
        s.core.growth['rules']['type_mastery_threshold']=3
        gain({'pet':1,'brush':1})
        self.assertEqual(type_mastery_pending(s.core),[])
        gain({'brush':1})
        self.assertEqual(type_mastery_choices(s.core,key),('pet','brush'))
        self.assertEqual(sum(e['kind']=='growth_type_mastery_ready' for e in s.core.events),1)
        s.resolve_growth_type_mastery(key,'brush'); gain({'brush':3})
        self.assertEqual(type_mastery_pending(s.core),[])
        self.assertEqual(sum(e['kind']=='growth_type_mastery_ready' for e in s.core.events),1)

    def test_each_of_eight_types_can_be_selected_only_in_its_group(self):
        for kind,group in TYPE_GROUPS.items():
            s=self.session(); key=next(iter(s.core.cats))
            service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=1,type_actions={kind:1}))
            s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,group)
            service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=1,type_actions={kind:1}))
            self.assertEqual(type_mastery_choices(s.core,key),(kind,))
            s.resolve_growth_type_mastery(key,kind)
            self.assertEqual(interaction_terms(s.core,key)['type'],kind)

    def test_effect_applies_only_matching_positive_normal_actions_and_stacks(self):
        for kind,group in TYPE_GROUPS.items():
            base=replace(RelationshipConfig(),mastery_group=group,mastery_engagement_multiplier=1.1,
                         equipment_group=group,equipment_engagement_multiplier=1.35)
            selected=replace(base,type_mastery=kind,type_mastery_engagement_multiplier=1.05)
            plain=RelationshipInteraction(base); skilled=RelationshipInteraction(selected)
            if kind!='teaser':plain.step('switch',kind); skilled.step('switch',kind)
            a=plain.step('direct'); b=skilled.step('direct')
            self.assertAlmostEqual(b['engagement_delta'],a['engagement_delta']*1.05)
            self.assertEqual(b['stamina_spent'],a['stamina_spent'])
            self.assertEqual(b['diagnostic']['type_mastery_multiplier'],1.05)
            pause=skilled.step('pause'); self.assertNotIn('type_mastery_multiplier',pause['diagnostic'])
            other=next(key for key in TYPE_GROUPS if key!=kind)
            skilled.step('switch',other); rec=skilled.step('direct')
            self.assertNotIn('type_mastery_multiplier',rec['diagnostic'])
            skilled.finish(); self.assertEqual(verify_relationship(skilled.log()).result(),skilled.result())

    def test_policy_prefers_individual_but_customer_group_and_boredom_take_precedence(self):
        config=replace(RelationshipConfig(),mastery_group='contact',mastery_engagement_multiplier=1.1,
                       type_mastery='brush',type_mastery_engagement_multiplier=1.05)
        policy=AutomaticInteractionPolicy(); active=RelationshipInteraction(config)
        self.assertEqual(policy.choose(active.observation(),active.valid_actions(),config),('switch','brush'))
        active.step('switch','brush'); active.step('direct'); active.step('direct')
        action,target=policy.choose(active.observation(),active.valid_actions(),config)
        self.assertEqual(action,'switch'); self.assertNotEqual(TYPE_GROUPS[target],'contact')
        for flag,group in (('play_service','play'),('quiet_service','quiet'),('contact_service','contact')):
            customer=replace(config,**{flag:True}); fresh=RelationshipInteraction(customer)
            action,target=policy.choose(fresh.observation(),fresh.valid_actions(),customer)
            actual=target if action=='switch' else fresh.state['mode']
            self.assertEqual(TYPE_GROUPS[actual],group)
            if group=='contact':self.assertEqual(target,'brush')

    def test_legacy_rules_and_relationship_logs_do_not_gain_fields(self):
        s=self.session(legacy=True); key=next(iter(s.core.cats))
        self.assertNotIn('type_mastery',s.core.growth['cats'][key])
        s.step(); s.start('guest-1',key,'seat-1'); s.step('direct')
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        old=RelationshipInteraction(RelationshipConfig()); old.step('direct'); old.finish()
        self.assertNotIn('type_mastery',old.log()['config']['rules'])
        self.assertNotIn('type_mastery_engagement_multiplier',old.log()['config']['rules'])
        self.assertEqual(verify_relationship(old.log()).result(),old.result())

    def test_invalid_rules_flags_and_corrupt_checkpoint_are_rejected(self):
        for changes in (dict(type_mastery_threshold=0),dict(type_mastery_threshold=True),
                        dict(type_mastery_engagement_multiplier=1),dict(type_mastery_engagement_multiplier=float('nan'))):
            with self.assertRaises(ValueError):rules(dict(rules(),**changes))
        for changes in (dict(type_mastery='unknown'),dict(type_mastery='pet'),dict(type_mastery_engagement_multiplier=1.05),
                        dict(type_mastery='pet',type_mastery_engagement_multiplier=1.05,mastery_group='play',mastery_engagement_multiplier=1.1)):
            with self.assertRaises(ValueError):RelationshipConfig(**changes)
        s,key=self.prepare(); s.resolve_growth_type_mastery(key,'teaser'); source=checkpoint(s.core,set())
        for changes in (dict(type_mastery='pet'),dict(type_mastery_selected_day=2),dict(type_mastery='ball'),
                        dict(type_mastery_actions=dict.fromkeys(TYPE_GROUPS,0))):
            bad=copy.deepcopy(source); bad['state']['growth']['cats'][key].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        s.start('guest-3',key,'seat-1'); source=checkpoint(s.core,set())
        for change in ('missing','other'):
            bad=copy.deepcopy(source); config=bad['state']['interactions']['seat-1']['config']['rules']
            if change=='missing':
                config.pop('type_mastery'); config.pop('type_mastery_engagement_multiplier')
            else:config['type_mastery']='ball'
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)

    def test_save_failure_and_retry_do_not_duplicate_progress(self):
        s=self.session(); key=next(iter(s.core.cats))
        s.step(); s.start('guest-1',key,'seat-1'); s.step('direct')
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        s.start('guest-2',key,'seat-1')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        self.assertTrue(s.pending)
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'teaser')
        s=self.reload(s); s.persist(); s.resolve_growth_type_mastery(key,'teaser')
        self.assertEqual(s.core.growth['cats'][key]['type_mastery_actions']['teaser'],1)
        self.assertEqual(sum(e['kind']=='growth_type_mastery_ready' for e in s.core.events),1)
        self.reload(s)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class TypeMasteryGuiTests(unittest.TestCase):
    setUp=TypeMasteryTests.setUp
    session=TypeMasteryTests.session
    prepare=TypeMasteryTests.prepare

    def test_choice_dialog_and_main_screen_attention(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s,key=self.prepare(); app=CafeInteractionWindow(root,s)
        self.assertIn('個別行動に習熟',app.notice.get())
        self.assertTrue(app.day_off_button.instate(['disabled']))
        app.attention_button.invoke(); window=app.growth_window
        self.assertTrue(window.type_mastery_mode)
        self.assertEqual(set(window.choice_buttons),{'teaser'})
        window.choice_buttons['teaser'].invoke()
        self.assertEqual(s.core.growth['cats'][key]['type_mastery'],'teaser')
        self.assertIn('ねこじゃらし',app.roster.set(key,'growth'))
        self.assertIn('得意な行動',app.details.get())

    def test_all_four_play_choices_fit_minimum_window(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_cat_growth_gui import CafeCatGrowthWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s,key=self.prepare(); row=s.core.growth['cats'][key]
        for kind in ('teaser','ball','plush','tunnel'):row['type_mastery_actions'][kind]=1
        window=CafeCatGrowthWindow(root,s,lambda:None); window.window.geometry('540x300'); root.update()
        self.assertEqual(len(window.choice_buttons),4)
        for button in window.choice_buttons.values():
            self.assertGreater(button.winfo_width(),0)
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),window.window.winfo_rootx()+window.window.winfo_width())
        window.close()
