import copy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cat_cafe_sim.core.human_cat_types import (
    TypesConfig, TypesInteraction, Personality, TYPE_IDS, InteractionType, load_presets,
)
from cat_cafe_sim.core.human_cat_interaction import HumanCatInteraction, save, verify
from cat_cafe_sim.core.human_cat_special import SpecialInteraction
from cat_cafe_sim.human_cat_gui import PlaySession
from cat_cafe_sim.evaluation.interaction_types import compare_types


class TypeTests(unittest.TestCase):
    def core(self, preset='中立', **kwargs):
        return TypesInteraction(TypesConfig(personality=load_presets()[preset]), **kwargs)

    def test_hand_calculated_examples(self):
        for kind, gain, cost, reaction in [('ball',12,5.5,'favorable'),('presence',6,1.5,'neutral')]:
            c=self.core();c.step('switch',kind);r=c.step('direct')
            self.assertAlmostEqual(r['engagement_gain'],gain)
            self.assertAlmostEqual(r['stamina_spent'],cost)
            self.assertEqual(r['reaction'],reaction)
        c=self.core('遊び好きで繊細な猫')
        self.assertAlmostEqual(c.step('intense')['engagement_gain'],8.64)
        c=self.core('遊び好きで繊細な猫')
        self.assertAlmostEqual(c.step('direct')['engagement_gain'],21.6)
        c=self.core('穏やかな甘えん坊');c.step('direct');c.step('switch','pet')
        self.assertAlmostEqual(c.step('direct')['engagement_gain'],17.28)

    def test_all_type_action_combinations(self):
        for t in TypesConfig().types:
            for action in ('direct','adapt','intense','feint'):
                with self.subTest(kind=t.id,action=action):
                    c=self.core()
                    if t.id!='teaser':c.step('switch',t.id)
                    before=c.log()
                    if action in t.actions:
                        c.step(action)
                    else:
                        with self.assertRaises(ValueError):c.step(action)
                        self.assertEqual(c.log(),before)

    def test_group_history_and_round_trip(self):
        c=self.core();c.step('direct');c.step('switch','ball')
        self.assertAlmostEqual(c.step('direct')['engagement_gain'],10.2)
        c.step('switch','pet');c.step('switch','ball')
        r=c.step('direct')
        self.assertEqual(r['after']['interaction_streak'],3)
        self.assertEqual(r['diagnostic']['switch_multiplier'],1)
        c.step('switch','pet');r=c.step('direct')
        self.assertEqual(r['after']['interaction_streak'],1)
        self.assertEqual(r['after']['last_interaction_group'],'contact')

    def test_switch_invalid_atomic(self):
        c=self.core()
        for action,target in [('switch',None),('switch','teaser'),('switch','unknown'),('direct','ball'),('switch',[]),([],None)]:
            before=c.log()
            with self.assertRaises(ValueError):c.step(action,target)
            self.assertEqual(c.log(),before)
        c=self.core(tension=100)
        before=c.log()
        with self.assertRaises(ValueError):c.step('switch','ball')
        self.assertEqual(c.log(),before)

    def test_zero_preferences_and_intensity_independence(self):
        for personality in (Personality(type_preferences=(0,)+(1,)*7),Personality(intensity_preferences=(1,1,0))):
            c=TypesInteraction(TypesConfig(personality=personality),stamina=20)
            self.assertEqual(c.step('intense')['reaction'],'turn_away')
        c=TypesInteraction(TypesConfig(personality=Personality(intensity_preferences=(2,1,0))))
        c.step('intense');r=c.step('adapt')
        self.assertEqual(r['diagnostic']['strength'],'gentle')
        self.assertEqual(r['diagnostic']['intensity_preference'],2)
        self.assertAlmostEqual(r['engagement_gain'],13.6)

    def test_pause_presence_combo_and_connect_history(self):
        c=self.core();c.step('switch','presence')
        before=c.state['stamina'];c.step('direct')
        self.assertLess(c.state['stamina'],before)
        gain=c.state['engagement'];c.step('pause')
        self.assertEqual(c.state['engagement'],gain)
        c=self.core();c.step('direct');c.step('pause')
        self.assertEqual(c.step('feint')['diagnostic']['base_gain'],18)
        c=self.core(tension=80);c.step('direct');c.step('pause');c.step('connect')
        self.assertEqual(c.state['last_interaction_group'],'play')
        self.assertEqual(c.step('feint')['diagnostic']['base_gain'],10)

    def test_special_switch_and_end_priority(self):
        c=self.core(tension=80,engagement=80)
        r=c.step('switch','brush')
        self.assertEqual(r['cat_action'],'open_up')
        self.assertEqual(r['engagement_gain'],0)
        self.assertEqual(r['stamina_spent'],0)
        self.assertEqual(c.state['tension'],90)
        self.assertEqual(c.state['mode'],'brush')
        c.step('connect')
        self.assertEqual(c.state['end_reason'],'success')
        self.assertEqual(c.state['bonus_funds'],100)
        c=self.core(tension=100,engagement=100)
        c.step('connect')
        self.assertEqual(c.state['bonus_funds'],200)

    def test_config_presets_roundtrip_and_validation(self):
        config=TypesConfig.load()
        self.assertEqual(config,TypesConfig.from_dict(config.to_dict()))
        self.assertEqual(len(load_presets()),5)
        for kwargs in ({'type_preferences':(1,)*7},{'intensity_preferences':(True,1,1)},
                       {'boredom_decay':1.1},{'switch_affinity':-.6}):
            with self.assertRaises(ValueError):Personality(**kwargs)
        for types in (config.types[:-1],config.types[:-1]+(config.types[0],)):
            with self.assertRaises(ValueError):replace(config,types=types)
        for kwargs in ({'gain':0},{'cost':float('nan')},{'actions':('direct',)}, {'id':'unknown'}):
            with self.assertRaises(ValueError):replace(config.types[0],**kwargs)
        for change in ('missing','extra','legacy'):
            d=config.to_dict()
            if change=='missing':del d['personality']['type_preferences']['ball']
            elif change=='extra':d['personality']['type_preferences']['unknown']=1
            else:d['rules']['preferences']=[1,1]
            with self.assertRaises(ValueError):TypesConfig.from_dict(d)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'bad.json';p.write_text('{"rules":{},"rules":{}}')
            with self.assertRaises(ValueError):TypesConfig.load(p)

    def test_public_observation_and_copy(self):
        c=self.core();obs=c.observation()
        self.assertNotIn('personality',obs)
        self.assertNotIn('type_preferences',obs)
        self.assertNotIn('switch_affinity',obs)
        obs['mode']='bad'
        r=c.step('direct');r['diagnostic']['type_preference']=123
        self.assertEqual(c.records[0]['diagnostic']['type_preference'],1)

    def test_three_version_replays_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'log.json'
            for c in (HumanCatInteraction(),SpecialInteraction(),self.core()):
                c.step('direct');save(c,path)
                self.assertEqual(verify(path).log(),c.log())
            for field in ('target_type','diagnostic'):
                d=copy.deepcopy(c.log())
                if field=='target_type':d['records'][0][field]='ball'
                else:d['records'][0][field]['switch_multiplier']=0
                path.write_text(json.dumps(d))
                with self.assertRaises(ValueError):verify(path)

    def test_cli_and_session_restart(self):
        ui=PlaySession(TypesConfig());ui.act('direct')
        old=ui.core.log()
        with self.assertRaises(ValueError):ui.restart_personality(Personality(), 'nan')
        self.assertEqual(ui.core.log(),old)
        ui.restart_personality(load_presets()['活発な探検家'],'20')
        self.assertEqual(ui.core.records,[])
        self.assertEqual(ui.core.state['mode'],'teaser')
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'cli.json')
            r=subprocess.run([sys.executable,'-S','-m','cat_cafe_sim.human_cat_demo','run','--rules','3','--actions','switch:ball','direct','--output',path],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(verify(path).state['mode'],'ball')

    def test_comparison_coverage_and_personality_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            rows=compare_types(TypesConfig(),Path(directory)/'comparison.json')
            self.assertEqual(len(rows),120)
            self.assertEqual(len({(r['preset'],r['policy'],r['initial_stamina']) for r in rows}),120)
            self.assertTrue(all(r['bonus_funds']==0 for r in rows if r['policy']=='pause'))
            results=[r['engagement'] for r in rows if r['policy']=='fixed:teaser' and r['initial_stamina']==100]
            self.assertGreater(len(set(results)),1)
