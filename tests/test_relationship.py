from dataclasses import replace
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.core.human_cat_interaction import save, verify
from cat_cafe_sim.storage.relationships import RelationshipStore, RelationshipConflict
from cat_cafe_sim.human_cat_relationship_gui import RelationshipPlaySession, result_text


class RelationshipCoreTests(unittest.TestCase):
    def test_short_positive_interaction_without_specials(self):
        c=RelationshipInteraction();c.step('direct');r=c.finish()
        self.assertEqual(r['end_reason'],'manual')
        self.assertEqual((r['affinity_before'],r['affinity_after'],r['bonus_funds']),(0,.5,0))
        self.assertEqual(r['ticks'],1)

    def test_normal_reaction_mapping(self):
        for prefs,stamina,action,expected in [((1,1,1),100,'intense',1),((1,1,1),100,'direct',.5),
                 ((1,.5,1),100,'direct',0),((1,.4,1),100,'direct',0),((1,1,1),20,'direct',0),((1,0,1),100,'direct',-1)]:
            c=RelationshipInteraction(RelationshipConfig(personality=Personality(intensity_preferences=prefs)),stamina=stamina,affinity=10)
            r=c.step(action)
            self.assertEqual(r['affinity_breakdown']['normal'],expected)

    def test_pause_switch_and_immediate_finish_do_not_add_affinity(self):
        c=RelationshipInteraction(affinity=10);c.step('pause');c.step('switch','ball')
        self.assertEqual(c.finish()['affinity_delta'],0)
        c=RelationshipInteraction(affinity=10)
        self.assertEqual(c.finish()['ticks'],0)
        self.assertEqual(c.result()['affinity_after'],10)

    def test_simultaneous_specials_continue_and_add_four(self):
        c=RelationshipInteraction(tension=80,engagement=80,affinity=10)
        r=c.step('connect')
        self.assertIsNone(c.state['end_reason'])
        self.assertEqual(c.state['affinity_pending'],4)
        self.assertEqual(c.state['bonus_funds'],200)
        c.step('pause')
        self.assertEqual(c.finish()['affinity_after'],14)
        self.assertEqual(r['affinity_breakdown']['normal'],0)

    def test_cat_special_and_normal_count_separately_once(self):
        c=RelationshipInteraction(tension=80,engagement=80)
        r=c.step('direct')
        self.assertEqual(r['affinity_breakdown']['normal'],.5)
        self.assertEqual(c.finish()['affinity_delta'],2.5)
        self.assertEqual(c.result()['bonus_funds'],50)

    def test_exhaustion_penalty_once_and_preserves_bonus(self):
        c=RelationshipInteraction(RelationshipConfig(direct_cost=100),tension=80,engagement=80,affinity=10)
        c.step('direct')
        self.assertEqual(c.result()['end_reason'],'exhausted')
        self.assertEqual(c.result()['affinity_after'],10.5)
        self.assertEqual(c.result()['bonus_funds'],50)
        before=c.log()
        c.finish();c.finish()
        self.assertEqual(c.log(),before)

    def test_negative_experience_and_clipping_only_at_end(self):
        c=RelationshipInteraction(RelationshipConfig(personality=Personality(type_preferences=(0,)+(1,)*7)),affinity=0)
        c.step('direct');c.step('switch','pet');c.step('direct')
        r=c.finish()
        self.assertEqual(r['affinity_pending'],-.5)
        self.assertEqual(r['affinity_after'],0)
        c=RelationshipInteraction(tension=80,engagement=80,affinity=99)
        c.step('connect');r=c.finish()
        self.assertEqual((r['affinity_delta'],r['affinity_unapplied']),(1,3))

    def test_manual_finish_cancels_reserved_actions_without_tick_or_reward(self):
        c=RelationshipInteraction(tension=100,engagement=100)
        r=c.finish()
        self.assertEqual((r['ticks'],r['bonus_funds'],r['affinity_delta']),(0,0,0))
        self.assertEqual(r['expired_reservations'],2)
        self.assertEqual(c.state['tension'],100)
        before=c.log()
        self.assertEqual(c.finish(),r)
        with self.assertRaises(ValueError):c.step('connect')
        self.assertEqual(c.log(),before)

    def test_time_limit_and_exhaustion_priority(self):
        c=RelationshipInteraction(RelationshipConfig(ticks=1),tension=100,engagement=100)
        c.step('connect')
        self.assertEqual(c.result()['end_reason'],'time_limit')
        self.assertEqual(c.result()['affinity_delta'],4)
        c=RelationshipInteraction(RelationshipConfig(ticks=1,direct_cost=100),affinity=10)
        c.step('direct')
        self.assertEqual(c.result()['end_reason'],'exhausted')
        self.assertEqual(c.result()['affinity_delta'],-1.5)

    def test_replay_partial_manual_automatic_and_tampered_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'replay.json'
            for c in (RelationshipInteraction(),RelationshipInteraction(RelationshipConfig(ticks=1))):
                c.step('direct');save(c,path)
                self.assertEqual(verify(path).log(),c.log())
                c.finish();save(c,path)
                self.assertEqual(verify(path).log(),c.log())
                data=c.log();data['summary']['affinity_after']+=1;path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):verify(path)

    def test_validation_and_configuration_roundtrip(self):
        self.assertEqual(RelationshipConfig.load(),RelationshipConfig.from_dict(RelationshipConfig.load().to_dict()))
        for kwargs in ({'affinity':101},{'revision':True},{'cat_id':''},{'customer_id':None},{'session_id':''}):
            with self.assertRaises(ValueError):RelationshipInteraction(**kwargs)
        with self.assertRaises(ValueError):RelationshipConfig(affinity_connect=-1)
        with self.assertRaises(ValueError):RelationshipInteraction().result()

    def test_multiple_simultaneous_events_can_occur_before_time_ends(self):
        c=RelationshipInteraction(RelationshipConfig(direct_gain=100),tension=80,engagement=80)
        while not c.state['end_reason']:
            c.step('connect' if 'connect' in c.valid_actions() else 'direct')
        self.assertGreaterEqual(c.state['simultaneous_count'],2)
        self.assertEqual(c.state['end_reason'],'time_limit')
        self.assertEqual(c.result()['affinity_breakdown']['simultaneous'],c.state['simultaneous_count'])



class RelationshipStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'relations.json'
        self.store=RelationshipStore(self.path)
        self.config=RelationshipConfig()

    def finished(self, **kwargs):
        c=self.store.begin(self.config,'cat','guest',**kwargs);c.step('direct');c.finish();return c

    def test_reunion_pair_independence_and_double_apply(self):
        c=self.finished();self.store.apply(c)
        self.assertEqual(self.store.snapshot('cat','guest'),dict(affinity=.5,revision=1))
        before=self.path.read_bytes();self.store.apply(c)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.store.snapshot('cat','other'),dict(affinity=0,revision=0))
        self.assertEqual(self.store.snapshot('other','guest'),dict(affinity=0,revision=0))
        next_c=self.finished();self.store.apply(next_c)
        self.assertEqual(self.store.snapshot('cat','guest')['affinity'],1)
        self.store.apply(c)
        self.assertEqual(self.store.snapshot('cat','guest')['affinity'],1)

    def test_conflict_and_id_collision_preserve_file(self):
        first=self.finished();stale=self.finished()
        self.store.apply(first);before=self.path.read_bytes()
        with self.assertRaises(RelationshipConflict):self.store.apply(stale)
        collision=self.finished(session_id=first.session_id)
        with self.assertRaises(RelationshipConflict):self.store.apply(collision)
        self.assertEqual(self.path.read_bytes(),before)

    def test_atomic_failure_and_retry(self):
        first=self.finished();self.store.apply(first)
        second=self.finished();before=self.path.read_bytes()
        with patch('cat_cafe_sim.storage.relationships.os.replace',side_effect=OSError('write failed')):
            with self.assertRaises(OSError):self.store.apply(second)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(list(self.path.parent.glob('.relations.json.*')),[])
        self.store.apply(second);self.store.apply(second)
        self.assertEqual(self.store.snapshot('cat','guest')['affinity'],1)

    def test_serialization_failure_and_first_write_failure(self):
        c=self.finished()
        with patch('cat_cafe_sim.storage.relationships.json.dump',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.store.apply(c)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()),[])
        self.store.apply(c)

    def test_replay_never_updates_store_and_unfinished_rejected(self):
        c=self.finished();self.store.apply(c);before=self.path.read_bytes()
        path=Path(self.temp.name)/'log.json';save(c,path);verify(path);verify(path)
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaises(ValueError):self.store.apply(self.store.begin(self.config,'cat','guest'))

    def test_controller_retains_unsaved_result_and_restart_snapshot(self):
        ui=RelationshipPlaySession(self.config,self.store)
        ui.act('direct');ui.core.finish()
        with patch.object(self.store,'_write',side_effect=OSError('test')):
            with self.assertRaises(OSError):ui.persist()
        self.assertFalse(ui.persisted)
        self.assertEqual(ui.core.result()['affinity_after'],.5)
        ui.persist()
        next_ui=ui.prepare_reunion(ui.base_config.personality,'20','cat-1','guest-1')
        self.assertEqual(next_ui.core.state['affinity_start'],.5)
        self.assertEqual(next_ui.core.state['stamina'],20)
        self.assertIn('保存済み',result_text(ui.core,ui.persisted))

    def test_corrupted_data_rejected_without_overwrite(self):
        self.path.write_text('{"format_version":1,"format_version":1}')
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.store.snapshot('cat','guest')
        self.assertEqual(self.path.read_bytes(),before)

    def test_cli_manual_finish_and_save(self):
        log=Path(self.temp.name)/'cli.json'
        r=subprocess.run([sys.executable,'-S','-m','cat_cafe_sim.human_cat_demo','run','--rules','4',
                          '--actions','direct','finish','--relationships',str(self.path),'--output',str(log),'--save-result'],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.store.snapshot('cat-1','guest-1')['affinity'],.5)
        self.assertEqual(verify(log).result()['end_reason'],'manual')

    def test_log_cannot_overwrite_relation_store(self):
        ui=RelationshipPlaySession(self.config,self.store)
        ui.act('direct');ui.core.finish();ui.persist()
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):ui.save(self.path)
        self.assertEqual(self.path.read_bytes(),before)
