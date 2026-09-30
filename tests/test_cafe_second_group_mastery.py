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
from cat_cafe_sim.core.cafe_growth import (MASTERY_GROUPS, TYPE_GROUPS, description,
    mastery_choices, mastery_pending, rules, service, second_mastery_pending, summary)
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.storage.cafe_saves import load_game, save_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class SecondGroupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=RelationshipStore(Path(self.temp.name)/'relationships.json'); add_playtest_cats(self.store)
        self.path=Path(self.temp.name)/'game.json'

    def session(self, legacy=False, seats=2):
        s=CafeInteractionSession(store=self.store,seat_count=seats,
            cafe_config=replace(Config.load(),opening_ticks=30,arrival_ticks=(0,1,2,3)),
            interaction_config=replace(RelationshipConfig(),ticks=4,confused_threshold=3,favorable_threshold=5))
        selected=dict(rules(),threshold=1,mastery_threshold=1,second_mastery_threshold=3)
        if legacy:selected.pop('second_mastery_threshold')
        s.core.initialize_growth(selected)
        return s

    def prepare(self,legacy=False,seats=2):
        s=self.session(legacy,seats); key=next(iter(s.core.cats))
        s.step(); s.start('guest-1',key,'seat-1')
        for _ in range(4):s.step('direct')
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        return s,key

    def qualify(self,s,key):
        s.start('guest-2',key,'seat-1'); s.step('switch','brush')
        for _ in range(3):s.step('direct')

    def reload(self,s):
        save_game(s,self.path); loaded,_=load_game(self.path)
        self.assertEqual(s.core.snapshot(),loaded.core.snapshot()); return loaded

    def test_actual_service_pending_selection_active_save_and_replay(self):
        for seats in (1,2):
            s,key=self.prepare(seats=seats); self.qualify(s,key)
            self.assertEqual(second_mastery_pending(s.core),[key])
            self.assertEqual(mastery_choices(s.core,key),('contact',))
            before=s.core.snapshot()
            for invalid in ('play','quiet','unknown'):
                with self.assertRaises(ValueError):s.resolve_growth_mastery(key,invalid)
                self.assertEqual(s.core.snapshot(),before)
            for action in (s.automatic_step,s.next_day,s.day_off):
                with self.assertRaisesRegex(ValueError,'得意な交流'):action()
            with patch('cat_cafe_sim.core.cafe_growth.rules',side_effect=lambda data:rules(data)):
                s=self.reload(s)
            s.resolve_growth_mastery(key,'contact')
            row=s.core.growth['cats'][key]
            self.assertEqual((row['mastery'],row['second_mastery']),('play','contact'))
            self.assertIn('遊び・触れ合い',summary(s.core,key))
            self.assertIn('遊び・触れ合い',description(s.core,key))
            self.assertEqual(dict(cat_details(s,key)['basic'])['2つ目の得意な交流'],'触れ合い')
            self.assertIn('2つ目の得意な交流の選択',str(cat_events(s.core,key)))
            with self.assertRaises(ValueError):s.resolve_growth_mastery(key,'quiet')
            s.start('guest-3',key,'seat-1'); s=self.reload(s)
            self.assertEqual(s.active_interactions['seat-1'].config.second_mastery_group,'contact')
            for _ in range(4):
                active=s.active_interactions['seat-1']
                s.step(*s.policy.choose(active.observation(),active.valid_actions(),active.config))
            self.assertFalse(s.active_interactions)
            self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
            self.assertEqual(sum(e['kind']=='growth_second_mastery_selected' for e in s.core.events),1)

    def test_only_post_first_successful_other_group_counts_per_group(self):
        s=self.session(); key=next(iter(s.core.cats)); row=s.core.growth['cats'][key]
        def gain(actions,affinity=1):service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=affinity,type_actions=actions))
        gain({'teaser':3,'brush':3}); s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        self.assertEqual(sum(row['second_mastery_groups'].values()),0)
        gain({'teaser':30}); gain({'brush':30},0); gain({'voice':30},-1); gain({})
        self.assertEqual(sum(row['second_mastery_groups'].values()),0)
        gain({'brush':2,'voice':2}); self.assertEqual(second_mastery_pending(s.core),[])
        gain({'pet':1}); self.assertEqual(mastery_choices(s.core,key),('contact',))
        gain({'presence':1}); self.assertEqual(mastery_choices(s.core,key),('contact','quiet'))
        self.assertEqual(sum(e['kind']=='growth_second_mastery_ready' for e in s.core.events),1)
        s.resolve_growth_mastery(key,'quiet'); gain({'brush':10})
        self.assertEqual(mastery_pending(s.core),[])
        self.assertEqual(sum(e['kind']=='growth_second_mastery_ready' for e in s.core.events),1)
        # Individual practice stays in the first category.
        self.assertEqual(row['type_mastery_actions']['brush'],0)
        self.assertEqual(row['type_mastery_actions']['voice'],0)

    def test_all_distinct_group_pairs_and_independent_individual_choices(self):
        representatives={'play':'teaser','contact':'brush','quiet':'voice'}
        for first in MASTERY_GROUPS:
            for second in MASTERY_GROUPS:
                if first==second:continue
                s=self.session(); key=next(iter(s.core.cats))
                def gain(group,count):service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=1,type_actions={representatives[group]:count}))
                gain(first,1); s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,first)
                gain(first,30); gain(second,3)
                self.assertEqual(mastery_choices(s.core,key),(second,))
                s.resolve_growth_mastery(key,second)
                s.resolve_growth_type_mastery(key,representatives[first])
                self.assertEqual(s.core.growth['cats'][key]['second_mastery'],second)
                self.assertEqual(s.core.growth['cats'][key]['type_mastery'],representatives[first])
                self.assertEqual(mastery_choices(s.core,key),())

    def test_effects_apply_once_with_equipment_and_individual_mastery(self):
        for first in MASTERY_GROUPS:
            for second in MASTERY_GROUPS:
                if first==second:continue
                base=replace(RelationshipConfig(),mastery_group=first,mastery_engagement_multiplier=1.1,
                    equipment_group=second,equipment_engagement_multiplier=1.35)
                config=replace(base,second_mastery_group=second)
                for kind,group in TYPE_GROUPS.items():
                    plain=RelationshipInteraction(base); skilled=RelationshipInteraction(config)
                    if kind!='teaser':plain.step('switch',kind); skilled.step('switch',kind)
                    a=plain.step('direct'); b=skilled.step('direct')
                    self.assertAlmostEqual(b['engagement_delta'],a['engagement_delta']*(1.1 if group==second else 1))
                    self.assertEqual(b['stamina_spent'],a['stamina_spent'])
                    if group in (first,second):self.assertEqual(b['diagnostic']['mastery_group'],group)
                    self.assertNotIn('mastery_multiplier',skilled.step('pause')['diagnostic'])
                    skilled.finish(); self.assertEqual(verify_relationship(skilled.log()).result(),skilled.result())
        base=replace(RelationshipConfig(),mastery_group='play',second_mastery_group='contact',mastery_engagement_multiplier=1.1,
            type_mastery='teaser',second_type_mastery='ball',type_mastery_engagement_multiplier=1.05)
        plain=RelationshipInteraction(replace(base,type_mastery='',second_type_mastery='',type_mastery_engagement_multiplier=1))
        skilled=RelationshipInteraction(base)
        self.assertAlmostEqual(skilled.step('direct')['engagement_delta'],plain.step('direct')['engagement_delta']*1.05)
        special=RelationshipInteraction(base,tension=100)
        self.assertNotIn('mastery_multiplier',special.step('connect')['diagnostic'])

    def test_policy_keeps_first_group_customer_priority_and_boredom(self):
        policy=AutomaticInteractionPolicy()
        base=replace(RelationshipConfig(),mastery_group='contact',second_mastery_group='quiet',mastery_engagement_multiplier=1.1)
        for flag,expected in ((None,'contact'),('play_service','play'),('contact_service','contact'),('quiet_service','quiet')):
            config=replace(base,**({flag:True} if flag else {})); active=RelationshipInteraction(config)
            action,target=policy.choose(active.observation(),active.valid_actions(),config)
            self.assertEqual(TYPE_GROUPS[target if action=='switch' else active.state['mode']],expected)
            if action=='switch':active.step(action,target)
            active.step('direct'); active.step('direct')
            action,target=policy.choose(active.observation(),active.valid_actions(),config)
            self.assertEqual(action,'switch'); self.assertNotEqual(TYPE_GROUPS[target],expected)
            active.step(action,target); active.step('direct'); active.step('direct')
            action,target=policy.choose(active.observation(),active.valid_actions(),config)
            self.assertEqual(TYPE_GROUPS[target],expected)
        low=RelationshipInteraction(base,stamina=10)
        self.assertEqual(policy.choose(low.observation(),low.valid_actions(),base),('pause',None))

    def test_old_rules_saves_and_relationship_logs_stay_unchanged(self):
        s,key=self.prepare(legacy=True); self.qualify(s,key)
        self.assertNotIn('second_mastery',s.core.growth['cats'][key])
        self.assertEqual(second_mastery_pending(s.core),[])
        with self.assertRaises(ValueError):s.resolve_growth_mastery(key,'contact')
        self.reload(s); self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        old=RelationshipInteraction(replace(RelationshipConfig(),mastery_group='play',mastery_engagement_multiplier=1.1))
        old.step('direct'); old.finish()
        self.assertNotIn('second_mastery_group',old.log()['config']['rules'])
        self.assertEqual(verify_relationship(old.log()).result(),old.result())

    def test_invalid_rules_saved_counts_choices_dates_and_interaction_rejected(self):
        for value in (0,True,1.5,float('inf')):
            with self.assertRaises(ValueError):rules(dict(rules(),second_mastery_threshold=value))
        for changes in (dict(second_mastery_group='quiet'),dict(mastery_group='play',second_mastery_group='play'),dict(mastery_group='play',second_mastery_group='bad')):
            with self.assertRaises(ValueError):replace(RelationshipConfig(),**changes)
        s,key=self.prepare(); self.qualify(s,key); s.resolve_growth_mastery(key,'contact'); source=checkpoint(s.core,set())
        for changes in (dict(second_mastery='play'),dict(second_mastery='quiet'),dict(second_mastery_selected_day=0),
            dict(second_mastery_groups=dict(play=1,contact=3,quiet=0)),dict(second_mastery_groups=dict(play=0,contact=2,quiet=0)),
            dict(second_mastery_groups=dict(play=0,contact=True,quiet=0))):
            bad=copy.deepcopy(source); bad['state']['growth']['cats'][key].update(changes)
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)
        s.start('guest-3',key,'seat-1'); bad=checkpoint(s.core,set())
        bad['state']['interactions']['seat-1']['config']['rules'].pop('second_mastery_group')
        bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):restore(bad)

    def test_persistence_failure_retry_does_not_duplicate_progress_or_selection(self):
        s,key=self.prepare(); s.start('guest-2',key,'seat-1'); s.step('switch','brush'); s.step('direct'); s.step('direct')
        with patch.object(s.store,'apply',side_effect=OSError('full')):
            with self.assertRaises(OSError):s.step('direct')
        self.assertTrue(s.pending)
        with self.assertRaises(ValueError):s.resolve_growth_mastery(key,'contact')
        s=self.reload(s); s.persist(); s.resolve_growth_mastery(key,'contact'); self.reload(s)
        self.assertEqual(s.core.growth['cats'][key]['second_mastery_groups']['contact'],3)
        self.assertEqual(sum(e['kind']=='growth_second_mastery_ready' for e in s.core.events),1)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires a display')
class SecondGroupGuiTests(unittest.TestCase):
    setUp=SecondGroupTests.setUp
    session=SecondGroupTests.session
    prepare=SecondGroupTests.prepare
    qualify=SecondGroupTests.qualify

    def test_attention_choice_roster_details_and_log(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s,key=self.prepare(); self.qualify(s,key); app=CafeInteractionWindow(root,s)
        self.assertIn('2つ目の得意な交流',app.notice.get()); self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke(); dialog=app.growth_window
        self.assertEqual(set(dialog.choice_buttons),{'contact'})
        dialog.choice_buttons['contact'].invoke()
        self.assertIn('遊び・触れ合い',app.roster.set(key,'growth'))
        self.assertIn('遊び・触れ合い',app.details.get())
        self.assertEqual(sum(e['kind']=='growth_second_mastery_selected' for e in s.core.events),1)

    def test_two_eligible_choices_fit_minimum_size_and_close_keeps_pending(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_cat_growth_gui import CafeCatGrowthWindow
        root=tk.Tk(); self.addCleanup(root.destroy)
        s,key=self.prepare(); self.qualify(s,key)
        service(s.core,dict(cat_id=key,stamina_spent=0,affinity_delta=1,type_actions={'voice':3}))
        window=CafeCatGrowthWindow(root,s,lambda:None); window.window.geometry('540x300'); root.update()
        self.assertEqual(set(window.choice_buttons),{'contact','quiet'})
        for button in window.choice_buttons.values():
            self.assertGreater(button.winfo_width(),0)
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),window.window.winfo_rootx()+window.window.winfo_width())
        window.close(); self.assertEqual(second_mastery_pending(s.core),[key])
