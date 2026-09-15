import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.cafe_history import comparison_rows
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.multi_seat_cafe import MultiSeatCafeCore
from cat_cafe_sim.core.cafe_checkpoint import digest, snapshot, is_receipt
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore, RelationshipConflict
from cat_cafe_sim.storage.cafe_saves import save_game, load_game, convert_game


class CompactCafeSaveTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.store=RelationshipStore(self.root/'relations.json')
        for key in ('cat-1','b'):self.store.register_cat(key,key,Personality())
        self.path=self.root/'save.json'
        self.config=replace(Config.load(),opening_ticks=4,arrival_ticks=(0,0))

    def session(self, core=None):
        return CafeInteractionSession(core=core,store=self.store,
            **({} if core else {'cafe_config':self.config}),
            interaction_config=replace(RelationshipConfig(),ticks=2))

    def close_day(self, session):
        while not session.core.closed:session.automatic_step()

    def legacy_file(self, session):
        data=dict(kind='cafe-save',format_version=1,core=session.core.log(),
                  interaction_config=session.interaction_config.to_dict(),relationship_path=str(self.store.path),
                  relationships=self.store._read(),policy_version=session.policy.version,auto_assign=True)
        path=self.root/'legacy.json'
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2))
        return path

    def test_new_format_has_receipts_no_operation_history_and_no_replay_on_load(self):
        session=self.session();self.close_day(session)
        self.assertTrue(all(is_receipt(value) for value in session.core.outcomes.values()))
        self.assertTrue(all('state' not in row for row in session.core.operations))
        with (patch('cat_cafe_sim.core.cafe_replay.apply_operation',side_effect=AssertionError('no replay')),
             patch('cat_cafe_sim.core.cafe_checkpoint.verify_relationship',side_effect=AssertionError('no completed replay'))):
            save_game(session,self.path)
            loaded,_=load_game(self.path)
        data=json.loads(self.path.read_text())
        self.assertEqual(data['format_version'],2)
        self.assertNotIn('operations',data['core'])
        self.assertEqual(data['core']['resume']['pending'],{})
        self.assertLess(self.path.stat().st_size,100_000)
        self.assertEqual(loaded.core.snapshot(),session.core.snapshot())
        self.assertEqual(loaded.core.operations,[])
        loaded.next_day();loaded.automatic_step()
        self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(),loaded.core.snapshot())

    def test_all_rest_growth_is_linear_and_past_comparisons_survive(self):
        session=self.session();self.close_day(session)
        session.next_day();session.set_shifts([])
        for day in range(2,31):
            self.close_day(session)
            if day==15:
                save_game(session,self.path);half=self.path.stat().st_size
            if day!=30:session.next_day()
        before=comparison_rows(session.core)
        save_game(session,self.path)
        self.assertLess(self.path.stat().st_size,half*2.5)
        self.assertLess(self.path.stat().st_size,200_000)
        loaded,_=load_game(self.path)
        self.assertEqual(comparison_rows(loaded.core),before)
        self.assertEqual(before[0]['cats']['cat-1']['interactions'],1)
        self.assertEqual(before[-1]['summary']['revenue'],0)

    def test_only_unapplied_outcomes_keep_full_records(self):
        session=self.session();session.automatic_step();session.automatic_step()
        apply=self.store.apply
        calls=[]
        def fail(core):
            calls.append(core.cat_id)
            if len(calls)==2:raise OSError('disk full')
            return apply(core)
        with patch.object(self.store,'apply',side_effect=fail):
            with self.assertRaises(OSError):session.automatic_step()
        save_game(session,self.path)
        data=json.loads(self.path.read_text())
        self.assertEqual(set(data['core']['resume']['pending']),session.pending)
        self.assertEqual(len(data['core']['resume']['pending']),1)
        self.assertTrue(all(is_receipt(value) for value in data['core']['state']['outcomes'].values()))
        loaded,_=load_game(self.path);loaded.persist();loaded.persist()
        self.assertFalse(loaded.pending)
        self.assertEqual(len(self.store._read()['applied']),2)

    def test_legacy_versions_migrate_without_changing_sources_or_relations(self):
        for version in (1,2,3):
            with self.subTest(version=version):
                cls=MultiSeatCafeCore if version==3 else CafeInteractionCore
                core=cls(self.config,cat_ids=None if version==1 else ['cat-1','b'])
                session=self.session(core);self.close_day(session)
                session.next_day();session.automatic_step()
                source=self.legacy_file(session)
                old=source.read_bytes();relations=self.store.path.read_bytes()
                loaded,_=load_game(source)
                self.assertEqual(loaded.core.snapshot(),snapshot(core))
                self.assertEqual(loaded.core.operations,[])
                target=self.root/f'converted-{version}.json'
                convert_game(source,target)
                self.assertEqual(source.read_bytes(),old)
                self.assertEqual(self.store.path.read_bytes(),relations)
                self.assertLess(target.stat().st_size,len(old)*.25)
                resumed,_=load_game(target)
                self.assertEqual(resumed.core.snapshot(),loaded.core.snapshot())
                self.close_day(resumed)
                self.assertEqual(verify_cafe_interaction(resumed.core.log()).snapshot(),resumed.core.snapshot())

    def test_legacy_reader_checks_every_operation_even_when_keys_reordered(self):
        session=self.session(CafeInteractionCore(self.config));self.close_day(session)
        source=self.legacy_file(session)
        data=json.loads(source.read_text())
        data['core']=dict(reversed(list(data['core'].items())))
        source.write_text(json.dumps(data))
        self.assertEqual(load_game(source)[0].core.summary(),session.core.summary())
        data['core']['operations'][0]['state']['funds']+=1
        source.write_text(json.dumps(data))
        with self.assertRaises(ValueError):convert_game(source,self.root/'bad.json')
        self.assertFalse((self.root/'bad.json').exists())
        source.write_text('{"format_version":1,"format_version":2}')
        with self.assertRaises(ValueError):load_game(source)

    def test_stale_conversion_keeps_stale_detection_and_prevents_overwrite(self):
        session=self.session(CafeInteractionCore(self.config))
        session.automatic_step()
        source=self.legacy_file(session)
        self.close_day(session)
        old=source.read_bytes();relations=self.store.path.read_bytes()
        convert_game(source,self.path)
        with self.assertRaises(RelationshipConflict):load_game(self.path)
        with self.assertRaises(ValueError):convert_game(source,self.path)
        with self.assertRaises(ValueError):convert_game(source,source)
        with self.assertRaises(ValueError):convert_game(source,self.store.path)
        self.assertEqual(source.read_bytes(),old)
        self.assertEqual(self.store.path.read_bytes(),relations)

    def test_corrupt_checkpoint_and_unrecorded_configuration_are_rejected(self):
        session=self.session();session.automatic_step();save_game(session,self.path)
        data=json.loads(self.path.read_text())
        for sign in (False,True):
            bad=copy.deepcopy(data)
            bad['core']['state']['cats']['cat-1']['stamina']=-1
            if sign:bad['core']['digest']=digest({key:value for key,value in bad['core'].items() if key!='digest'})
            self.path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):load_game(self.path)
        session.core.config=replace(session.core.config,time_price=999)
        with self.assertRaises(ValueError):save_game(session,self.root/'bad.json')
