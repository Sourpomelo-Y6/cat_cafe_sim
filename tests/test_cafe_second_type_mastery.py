import copy
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_cat_details import cat_details
from cat_cafe_sim.cafe_cat_events import cat_events
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_growth import (TYPE_GROUPS, description, rules, service, summary,
    second_type_mastery_pending, type_mastery_choices, type_mastery_pending)
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.storage.cafe_saves import load_game, save_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class SecondMasteryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relationships.json'); add_playtest_cats(self.store)
        self.path=Path(self.temp.name)/'game.json'

    def session(self,legacy=False):
        s=CafeInteractionSession(store=self.store,seat_count=2,
            cafe_config=replace(Config.load(),opening_ticks=30,arrival_ticks=(0,1,2,3)),
            interaction_config=replace(RelationshipConfig(),ticks=3))
        selected=dict(rules(),threshold=1,mastery_threshold=1,type_mastery_threshold=1,second_type_mastery_threshold=2)
        if legacy:selected.pop('second_type_mastery_threshold')
        s.core.initialize_growth(selected)
        return s

    def prepare(self,legacy=False):
        s=self.session(legacy); key=next(iter(s.core.cats))
        s.step(); s.start('guest-1',key,'seat-1')
        for _ in range(3):s.step('direct')
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        s.start('guest-2',key,'seat-1')
        for _ in range(3):s.step('direct')
        s.resolve_growth_type_mastery(key,'teaser')
        return s,key

    def qualify(self,s,key):
        s.start('guest-3',key,'seat-1'); s.step('switch','ball'); s.step('direct'); s.step('direct')

    def reload(self,s):
        save_game(s,self.path); loaded,_=load_game(self.path)
        self.assertEqual(s.core.snapshot(),loaded.core.snapshot()); return loaded

    def test_pending_choice_active_save_and_replay_keep_both_actions(self):
        s,key=self.prepare(); row=s.core.growth['cats'][key]
        self.assertEqual(sum(row['second_type_mastery_actions'].values()),0)
        self.qualify(s,key)
        self.assertEqual(second_type_mastery_pending(s.core),[key])
        self.assertEqual(type_mastery_choices(s.core,key),('ball',))
        before=s.core.snapshot()
        for choice in ('teaser','brush','tunnel','unknown'):
            with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,choice)
            self.assertEqual(s.core.snapshot(),before)
        for action in (s.automatic_step,s.day_off,s.next_day):
            with self.assertRaisesRegex(ValueError,'得意な行動'):action()
        with patch('cat_cafe_sim.core.cafe_growth.rules',side_effect=lambda data:rules(data)):
            s=self.reload(s)
        s.resolve_growth_type_mastery(key,'ball')
        self.assertEqual(s.core.growth['cats'][key]['type_mastery'],'teaser')
        self.assertEqual(s.core.growth['cats'][key]['second_type_mastery'],'ball')
        self.assertIn('ねこじゃらし・ボール遊び',summary(s.core,key))
        self.assertIn('ねこじゃらし・ボール遊び',description(s.core,key))
        self.assertEqual(dict(cat_details(s,key)['basic'])['2つ目の得意な行動'],'ボール遊び')
        self.assertIn('2つ目の得意な行動の選択',str(cat_events(s.core,key)))
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'plush')
        s.start('guest-4',key,'seat-1'); s=self.reload(s)
        self.assertEqual(s.active_interactions['seat-1'].config.second_type_mastery,'ball')
        s.step('direct'); s.step('switch','ball'); s.step('direct')
        row=copy.deepcopy(s.core.growth['cats'][key]); s.finish()
        self.assertEqual(s.core.growth['cats'][key],row)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.assertEqual(sum(e['kind']=='growth_second_type_mastery_selected' for e in s.core.events),1)

    def test_only_post_first_successful_unlearned_actions_count(self):
        s=self.session(); key=next(iter(s.core.cats)); row=s.core.growth['cats'][key]
        def gain(actions,affinity=1):service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=affinity,type_actions=actions))
        gain({'teaser':3,'ball':3}); s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        gain({'teaser':3,'ball':3}); s.resolve_growth_type_mastery(key,'teaser')
        self.assertEqual(sum(row['second_type_mastery_actions'].values()),0)
        gain({'teaser':30,'brush':30}); gain({'ball':30},0); gain({'ball':30},-1); gain({})
        self.assertEqual(sum(row['second_type_mastery_actions'].values()),0)
        gain({'ball':1}); self.assertEqual(type_mastery_pending(s.core),[])
        gain({'plush':1}); self.assertEqual(type_mastery_choices(s.core,key),('ball','plush'))
        self.assertEqual(sum(e['kind']=='growth_second_type_mastery_ready' for e in s.core.events),1)
        s.resolve_growth_type_mastery(key,'plush'); gain({'ball':2})
        self.assertEqual(type_mastery_pending(s.core),[])
        self.assertEqual(sum(e['kind']=='growth_second_type_mastery_ready' for e in s.core.events),1)

    def test_every_distinct_pair_within_each_group_is_eligible(self):
        for first,group in TYPE_GROUPS.items():
            for second,other_group in TYPE_GROUPS.items():
                if first==second or group!=other_group:continue
                s=self.session(); key=next(iter(s.core.cats))
                def gain(kind,count=1):service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=1,type_actions={kind:count}))
                gain(first); s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,group)
                gain(first); s.resolve_growth_type_mastery(key,first)
                gain(second,2); self.assertEqual(type_mastery_choices(s.core,key),(second,))
                s.resolve_growth_type_mastery(key,second)
                self.assertEqual(s.core.growth['cats'][key]['second_type_mastery'],second)
                self.assertEqual(type_mastery_choices(s.core,key),())

    def test_both_effects_apply_once_and_other_actions_and_specials_do_not_gain_bonus(self):
        for group,first,second in (('play','teaser','ball'),('contact','pet','brush'),('quiet','voice','presence')):
            base=replace(RelationshipConfig(),mastery_group=group,mastery_engagement_multiplier=1.1,
                         equipment_group=group,equipment_engagement_multiplier=1.35)
            config=replace(base,type_mastery=first,second_type_mastery=second,type_mastery_engagement_multiplier=1.05)
            for kind in TYPE_GROUPS:
                plain=RelationshipInteraction(base); skilled=RelationshipInteraction(config)
                if kind!='teaser':plain.step('switch',kind); skilled.step('switch',kind)
                a=plain.step('direct'); b=skilled.step('direct')
                self.assertAlmostEqual(b['engagement_delta'],a['engagement_delta']*(1.05 if kind in (first,second) else 1))
                self.assertEqual(b['stamina_spent'],a['stamina_spent'])
                if kind in (first,second):self.assertEqual(b['diagnostic']['type_mastery'],kind)
                self.assertNotIn('type_mastery_multiplier',skilled.step('pause')['diagnostic'])
                skilled.finish(); self.assertEqual(verify_relationship(skilled.log()).result(),skilled.result())
            special=RelationshipInteraction(config,tension=100)
            self.assertNotIn('type_mastery_multiplier',special.step('connect')['diagnostic'])

    def test_policy_uses_personality_effect_and_keeps_customer_and_boredom_rules(self):
        policy=AutomaticInteractionPolicy()
        base=replace(RelationshipConfig(),mastery_group='contact',mastery_engagement_multiplier=1.1,
                     type_mastery='pet',second_type_mastery='brush',type_mastery_engagement_multiplier=1.05)
        for preferred in ('pet','brush'):
            preferences=tuple(1.5 if key==preferred else .5 for key in TYPE_GROUPS)
            config=replace(base,personality=replace(base.personality,type_preferences=preferences))
            active=RelationshipInteraction(config)
            self.assertEqual(policy.choose(active.observation(),active.valid_actions(),config),('switch',preferred))
            active.step('switch',preferred); active.step('direct'); active.step('direct')
            action,target=policy.choose(active.observation(),active.valid_actions(),config)
            self.assertEqual(action,'switch'); self.assertNotEqual(TYPE_GROUPS[target],'contact')
            active.step(action,target); active.step('direct'); active.step('direct')
            self.assertEqual(policy.choose(active.observation(),active.valid_actions(),config),('switch',preferred))
        for flag,group in (('play_service','play'),('quiet_service','quiet')):
            config=replace(base,**{flag:True}); active=RelationshipInteraction(config)
            action,target=policy.choose(active.observation(),active.valid_actions(),config)
            self.assertEqual(TYPE_GROUPS[target if action=='switch' else active.state['mode']],group)
        # The second mastered play action overtakes the small base-gain difference.
        config=replace(RelationshipConfig(),mastery_group='play',mastery_engagement_multiplier=1.1,
                       type_mastery='teaser',second_type_mastery='ball',type_mastery_engagement_multiplier=1.05)
        config=replace(config,personality=replace(config.personality,type_preferences=(1,1.02,1,0.9,1,1,1,1)))
        fresh=RelationshipInteraction(config)
        self.assertEqual(policy.choose(fresh.observation(),fresh.valid_actions(),config),('switch','ball'))

    def test_actual_automatic_service_preserves_both_masteries_and_replays(self):
        s,key=self.prepare(); self.qualify(s,key); s.resolve_growth_type_mastery(key,'ball')
        s.start('guest-4',key,'seat-1')
        active=s.active_interactions['seat-1']
        expected=s.policy.choose(active.observation(),active.valid_actions(),active.config)
        s.automatic_step(auto_assign=False)
        record=next(e['record'] for e in reversed(s.core.events) if e['kind']=='human_cat_action')
        self.assertEqual(record['action'],expected[0])
        while s.active_interactions:s.automatic_step(auto_assign=False)
        self.assertEqual(s.core.growth['cats'][key]['second_type_mastery'],'ball')
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_old_one_action_rules_and_logs_remain_unchanged(self):
        s,key=self.prepare(legacy=True); self.qualify(s,key)
        self.assertNotIn('second_type_mastery',s.core.growth['cats'][key])
        self.assertEqual(type_mastery_pending(s.core),[])
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'ball')
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        config=replace(RelationshipConfig(),mastery_group='contact',mastery_engagement_multiplier=1.1,
                       type_mastery='brush',type_mastery_engagement_multiplier=1.05)
        active=RelationshipInteraction(config); active.step('switch','brush'); active.step('direct'); active.finish()
        self.assertNotIn('second_type_mastery',active.log()['config']['rules'])
        self.assertEqual(verify_relationship(active.log()).result(),active.result())
        self.assertEqual(AutomaticInteractionPolicy().choose(RelationshipInteraction(config).observation(),('direct','switch'),config),('switch','brush'))

    def test_invalid_settings_duplicate_choices_and_corrupt_saved_state_are_rejected(self):
        for value in (0,True,1.5,float('inf')):
            with self.assertRaises(ValueError):rules(dict(rules(),second_type_mastery_threshold=value))
        for changes in (dict(second_type_mastery='ball'),dict(second_type_mastery='teaser',type_mastery='teaser'),dict(second_type_mastery='brush',type_mastery='teaser')):
            with self.assertRaises(ValueError):replace(RelationshipConfig(),mastery_group='play',mastery_engagement_multiplier=1.1,type_mastery_engagement_multiplier=1.05,**changes)
        s,key=self.prepare(); self.qualify(s,key); s.resolve_growth_type_mastery(key,'ball'); source=checkpoint(s.core,set())
        for changes in (dict(second_type_mastery='teaser'),dict(second_type_mastery='brush'),dict(second_type_mastery='plush'),
                        dict(second_type_mastery_selected_day=0),dict(second_type_mastery_actions=dict.fromkeys(TYPE_GROUPS,0))):
            bad=copy.deepcopy(source); bad['state']['growth']['cats'][key].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        s.start('guest-4',key,'seat-1'); source=checkpoint(s.core,set())
        bad=copy.deepcopy(source); bad['state']['interactions']['seat-1']['config']['rules'].pop('second_type_mastery')
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)

    def test_failed_persistence_retries_without_duplicate_secondary_progress(self):
        s,key=self.prepare(); s.start('guest-3',key,'seat-1'); s.step('switch','ball'); s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        self.assertTrue(s.pending)
        with self.assertRaises(ValueError):s.resolve_growth_type_mastery(key,'ball')
        s=self.reload(s); s.persist(); s.resolve_growth_type_mastery(key,'ball'); self.reload(s)
        self.assertEqual(s.core.growth['cats'][key]['second_type_mastery_actions']['ball'],2)
        self.assertEqual(sum(e['kind']=='growth_second_type_mastery_ready' for e in s.core.events),1)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class SecondMasteryGuiTests(unittest.TestCase):
    setUp=SecondMasteryTests.setUp
    session=SecondMasteryTests.session
    prepare=SecondMasteryTests.prepare
    qualify=SecondMasteryTests.qualify

    def test_second_choice_attention_and_two_action_display(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s,key=self.prepare(); self.qualify(s,key); app=CafeInteractionWindow(root,s)
        self.assertIn('2つ目の個別行動',app.notice.get()); self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke(); dialog=app.growth_window
        self.assertEqual(set(dialog.choice_buttons),{'ball'})
        dialog.choice_buttons['ball'].invoke()
        self.assertIn('ねこじゃらし・ボール遊び',app.roster.set(key,'growth'))
        self.assertIn('ねこじゃらし・ボール遊び',app.details.get())

    def test_three_remaining_play_choices_fit_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_cat_growth_gui import CafeCatGrowthWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s,key=self.prepare(); self.qualify(s,key); row=s.core.growth['cats'][key]
        row['second_type_mastery_actions'].update(plush=1,tunnel=1)
        window=CafeCatGrowthWindow(root,s,lambda:None); window.window.geometry('540x300'); root.update()
        self.assertEqual(set(window.choice_buttons),{'ball','plush','tunnel'})
        for button in window.choice_buttons.values():
            self.assertGreater(button.winfo_width(),0)
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),window.window.winfo_rootx()+window.window.winfo_width())
        window.close()
