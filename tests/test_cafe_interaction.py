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
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.models import StartState
from cat_cafe_sim.storage.relationships import RelationshipStore


class CafeInteractionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = RelationshipStore(Path(temp.name)/'relationships.json')

    def session(self, opening=40, stamina=100, **changes):
        config = replace(Config.load(), opening_ticks=opening, arrival_ticks=(0, 1), **changes)
        core = CafeInteractionCore(config, start_state=StartState(stamina,100))
        return CafeInteractionSession(core, self.store)

    def test_manual_end_returns_stamina_affinity_and_time_bill(self):
        session = self.session()
        session.step(); session.start('guest-1'); session.step('direct')
        self.assertEqual(session.core.tick, 2)
        self.assertEqual(session.core.cat.stamina, 95)
        session.finish()
        self.assertEqual(session.core.funds, 10)
        self.assertEqual(session.core.visits['guest-1'].departure_reason, 'interaction_manual')
        self.assertEqual(self.store.snapshot('cat-1','guest-1')['affinity'],.5)
        before = session.core.log(); session.finish(); session.persist()
        self.assertEqual(session.core.log(), before)
        session.start('guest-2')
        self.assertEqual(session.core.active.state['stamina'],95)
        self.assertEqual(session.core.active.state['affinity_start'],0)

    def test_zero_action_finish_has_no_fee_or_elapsed_time(self):
        session = self.session(); session.step(); session.start('guest-1'); session.finish()
        self.assertEqual((session.core.tick,session.core.funds,session.core.cat.stamina),(1,0,100))

    def test_special_bonus_added_once_without_legacy_success_bonus(self):
        session = self.session()
        session.interaction_config = replace(RelationshipConfig(),direct_gain=100,tension_enthusiastic=100)
        session.step();session.start('guest-1');session.step('direct');session.step('connect')
        result = session.core.active.summary()
        self.assertEqual(result['bonus_funds'],200)
        session.finish();session.finish()
        self.assertEqual(session.core.funds,220)
        self.assertEqual(session.core.summary()['revenue'],220)
        event = next(e for e in session.core.events if e['kind']=='departure')
        self.assertEqual((event['base_charge'],event['bonus'],event['bill']),(20,200,220))

    def test_time_passes_for_arrivals_and_wait_deadlines(self):
        session = self.session(max_wait_ticks=2)
        session.step();session.start('guest-1')
        session.step('direct');session.step('pause')
        self.assertEqual(session.core.visits['guest-2'].departure_reason,'wait_timeout')
        self.assertEqual(session.core.visits['guest-2'].bill,0)
        self.assertEqual(session.core.cat.stamina,97)

    def test_closing_caps_session_and_settles_once(self):
        session = self.session(opening=3)
        session.step();session.start('guest-1')
        self.assertEqual(session.core.active.config.ticks,2)
        session.step('direct');session.step('pause')
        self.assertTrue(session.core.closed)
        self.assertEqual(session.core.visits['guest-1'].departure_reason,'closing')
        self.assertEqual(session.core.funds,20)
        self.assertFalse(session.pending)
        self.assertEqual(len(session.core.outcomes),1)
        with self.assertRaises(RuntimeError):session.step()

    def test_exhaustion_at_closing_keeps_stamina_zero_and_spirit(self):
        session = self.session(opening=2,stamina=5)
        session.step();session.start('guest-1');session.step('direct')
        self.assertEqual(session.core.visits['guest-1'].departure_reason,'interaction_exhausted')
        self.assertEqual((session.core.cat.stamina, session.core.cat.spirit),(0,100))
        self.assertTrue(session.core.cat.cannot_continue)
        self.assertEqual(session.core.funds,10)

    def test_invalid_actions_and_selection_leave_state_unchanged(self):
        session = self.session();session.step()
        before = session.core.log()
        with self.assertRaises(ValueError):session.start('unknown')
        self.assertEqual(session.core.log(),before)
        session.start('guest-1');before=session.core.log()
        with self.assertRaises(ValueError):session.step('invalid')
        with self.assertRaises(ValueError):session.start('guest-1')
        self.assertEqual(session.core.log(),before)
        self.assertFalse(self.store.path.exists())

    def test_failed_save_blocks_advancement_and_retry_preserves_money(self):
        session = self.session();session.step();session.start('guest-1');session.step('direct')
        with patch.object(self.store,'_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):session.finish()
        self.assertTrue(session.pending)
        self.assertEqual(session.core.funds,10)
        before=session.core.log()
        with self.assertRaises(ValueError):session.step()
        with self.assertRaises(ValueError):session.start('guest-2')
        self.assertEqual(session.core.log(),before)
        session.persist();session.persist()
        self.assertFalse(session.pending)
        self.assertEqual(self.store.snapshot('cat-1','guest-1')['affinity'],.5)
        self.assertEqual(session.core.funds,10)

    def test_replay_is_read_only_and_detects_tampering(self):
        session=self.session();session.step();session.start('guest-1');session.step('direct');session.finish()
        path=self.store.path.with_name('log.json');session.save_log(path)
        before=self.store.path.read_bytes()
        data=json.loads(path.read_text())
        replay=verify_cafe_interaction(data)
        self.assertEqual(replay.summary(),session.core.summary())
        self.assertEqual(self.store.path.read_bytes(),before)
        broken=copy.deepcopy(data);broken['summary']['funds']+=1
        with self.assertRaises(ValueError):verify_cafe_interaction(broken)
        with self.assertRaises(ValueError):session.save_log(self.store.path)

    def test_next_day_reads_saved_affinity_and_cat_personality(self):
        from cat_cafe_sim.core.human_cat_types import load_presets
        personality=load_presets()['穏やかな甘えん坊']
        self.store.register_cat('cat-1','ミケ',personality)
        first=self.session();first.step();first.start('guest-1');first.step('direct');first.finish()
        affinity=self.store.snapshot('cat-1','guest-1')['affinity']
        second=self.session();second.step();second.start('guest-1')
        self.assertEqual(second.cat_name,'ミケ')
        self.assertEqual(second.core.active.config.personality,personality)
        self.assertEqual(second.core.active.state['affinity_start'],affinity)
        self.assertFalse(second.core.visits['guest-1'].first_meeting)

    def test_interaction_limit_departure_allows_next_customer(self):
        session=self.session()
        session.interaction_config=replace(RelationshipConfig(),ticks=1)
        session.step();session.start('guest-1');session.step('direct')
        self.assertFalse(session.core.closed)
        self.assertEqual(session.core.visits['guest-1'].departure_reason,'interaction_time_limit')
        session.start('guest-2')
        self.assertEqual(session.core.active.state['stamina'],95)
