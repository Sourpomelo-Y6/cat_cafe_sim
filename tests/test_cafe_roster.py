import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore, verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.models import StartState
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import load_presets
from cat_cafe_sim.storage.relationships import RelationshipStore


class CafeRosterTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=RelationshipStore(Path(directory.name)/'relationships.json')
        presets=load_presets()
        self.store.register_cat('cat-a','ミケ',presets['穏やかな甘えん坊'])
        self.store.register_cat('cat-b','タマ',presets['活発な探検家'])
        self.config=replace(Config.load(),arrival_ticks=(0,1,2))

    def session(self, **kwargs):
        return CafeInteractionSession(store=self.store,cafe_config=self.config,**kwargs)

    def test_participation_includes_cats_without_relationships_and_subset(self):
        before=self.store.path.read_bytes()
        self.assertEqual(list(self.session().core.cats),['cat-a','cat-b'])
        self.assertEqual(list(self.session(cat_ids=['cat-b']).core.cats),['cat-b'])
        self.assertEqual(self.store.path.read_bytes(),before)
        for ids in ([],['unknown'],['cat-a','cat-a']):
            with self.assertRaises(ValueError):self.session(cat_ids=ids)

    def test_switching_cats_preserves_each_stamina_and_personality(self):
        session=self.session()
        session.step();session.start('guest-1','cat-b');session.step('direct');session.finish()
        self.assertEqual(session.core.cats['cat-a'].stamina,100)
        self.assertEqual(session.core.cats['cat-b'].stamina,95)
        session.start('guest-2','cat-a');session.step('direct');session.finish()
        session.start('guest-3','cat-b')
        self.assertEqual(session.core.active.state['stamina'],95)
        self.assertEqual(session.core.active.config.personality,load_presets()['活発な探検家'])
        self.assertEqual(session.core.seat.cat_id,'cat-b')
        self.assertEqual(session.core.summary()['cat_stamina'],{'cat-a':95,'cat-b':95})
        before=session.core.log()
        with self.assertRaises(ValueError):session.start('guest-3','cat-a')
        self.assertEqual(session.core.log(),before)

    def test_auto_selects_highest_stamina_then_id(self):
        session=self.session(interaction_config=replace(RelationshipConfig(),ticks=1))
        session.automatic_step();session.automatic_step();session.automatic_step()
        assigned=[e['cat_id'] for e in session.core.events if e['kind']=='assigned']
        self.assertEqual(assigned,['cat-a','cat-b'])
        self.assertEqual(session.core.cats['cat-a'].stamina,95)
        self.assertEqual(session.core.cats['cat-b'].stamina,95)
        session.automatic_step()
        self.assertEqual([e['cat_id'] for e in session.core.events if e['kind']=='assigned'],['cat-a','cat-b','cat-a'])

    def test_exhausted_cat_does_not_block_healthy_cat(self):
        core=CafeInteractionCore(self.config,cat_ids=['cat-a','cat-b'],start_state=StartState(5,100))
        session=CafeInteractionSession(core,self.store)
        session.step();session.start('guest-1','cat-a');session.step('direct')
        self.assertTrue(core.cats['cat-a'].cannot_continue)
        self.assertEqual([cat.id for cat in session.available_cats()],['cat-b'])
        before=core.log()
        with self.assertRaises(ValueError):session.start('guest-2','cat-a')
        self.assertEqual(core.log(),before)
        session.start('guest-2','cat-b')
        self.assertEqual(core.seat.cat_id,'cat-b')
        self.assertEqual(core.cats['cat-a'].stamina,0)

    def test_options_show_pair_specific_affinity_and_no_read_writes(self):
        interaction=self.store.begin(RelationshipConfig(),'cat-b','guest-1')
        interaction.step('direct');interaction.finish();self.store.apply(interaction)
        session=self.session();before=self.store.path.read_bytes()
        options={row['cat_id']:row for row in session.cat_choices('guest-1')}
        self.assertEqual(options['cat-a']['affinity'],0)
        self.assertGreater(options['cat-b']['affinity'],0)
        self.assertEqual(options['cat-b']['name'],'タマ')
        self.assertEqual(options['cat-b']['personality'],'活発な探検家')
        self.assertEqual([row['affinity'] for row in session.cat_choices('guest-2')],[0,0])
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_roster_replay_and_legacy_replay(self):
        session=self.session(interaction_config=replace(RelationshipConfig(),ticks=1))
        while not session.core.closed:session.automatic_step()
        data=json.loads(json.dumps(session.core.log()))
        before=self.store.path.read_bytes()
        replay=verify_cafe_interaction(data)
        self.assertEqual(replay.snapshot(),session.core.snapshot())
        self.assertEqual(self.store.path.read_bytes(),before)
        data['cat_ids']=['cat-a']
        with self.assertRaises(ValueError):verify_cafe_interaction(data)
        old=CafeInteractionSession(CafeInteractionCore(self.config),self.store)
        old.step();old.start('guest-1');old.step('direct');old.finish()
        self.assertEqual(old.core.log()['format_version'],1)
        self.assertEqual(verify_cafe_interaction(old.core.log()).summary(),old.core.summary())

    def test_failed_save_retains_both_cats_and_blocks_switch(self):
        session=self.session();session.step();session.start('guest-1','cat-b');session.step('direct')
        with patch.object(self.store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):session.finish()
        before=session.core.log()
        with self.assertRaises(ValueError):session.start('guest-2','cat-a')
        self.assertEqual(session.core.log(),before)
        session.persist();session.persist()
        self.assertEqual(session.core.funds,10)
        self.assertEqual(session.core.cats['cat-b'].stamina,95)
        self.assertEqual(session.core.cats['cat-a'].stamina,100)
