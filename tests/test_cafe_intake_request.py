import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_intake_request import pending
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.cafe_saves import save_game, load_game
from cat_cafe_sim.storage.relationships import RelationshipStore


class IntakeRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def session(self):
        return create_game(self.directory / 'games')

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        loaded, _ = load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def waiting(self, s):
        for _ in range(3):
            s.day_off()
        self.assertTrue(pending(s.core))
        return s

    def test_new_game_scheduled_waiting_accepted_and_next_day_roundtrip(self):
        s = self.reload(self.session())
        s = self.reload(self.waiting(s))
        before = s.core.funds
        rule = s.core.intake_request['rules']
        key = rule['cat_id']
        s.resolve_intake_request('accept')
        self.assertEqual(len(s.core.cats), 6)
        self.assertEqual(s.core.funds, before - rule['candidate']['cost'])
        self.assertNotIn(key, s.core.working_cats)
        self.assertEqual(s.core.management['stress'][key], 0)
        self.assertEqual(s.core.cats[key].health_status, 'healthy')
        self.assertEqual(s.core.cat_features[key], rule['candidate']['features'])
        self.assertEqual(s.profiles[key]['name'], rule['candidate']['name'])
        self.assertEqual(s.core.summary()['recruitment_expenses'], 200)
        s = self.reload(s)
        snapshot = s.core.snapshot()
        with patch.object(s.store, '_write', side_effect=AssertionError('duplicate write')):
            s.resolve_intake_request('accept')
        self.assertEqual(s.core.snapshot(), snapshot)
        with self.assertRaises(ValueError):
            s.resolve_intake_request('decline')
        s.day_off()
        self.assertEqual(s.core.summary()['recruitment_expenses'], 0)
        self.assertEqual(s.core.day_results[-1]['summary']['recruitment_expenses'], 200)
        self.reload(s)

    def test_decline_has_no_charge_or_registration_and_does_not_repeat(self):
        s = self.waiting(self.session())
        funds, popularity = s.core.funds, s.core.management['popularity']
        with patch.object(s.store, '_write', side_effect=AssertionError('unexpected write')):
            s.resolve_intake_request('decline')
            s.resolve_intake_request('decline')
        self.assertEqual((s.core.funds, s.core.management['popularity']), (funds, popularity))
        self.assertEqual(len(s.core.cats), 5)
        s = self.reload(s)
        for _ in range(3):
            s.day_off()
        self.assertFalse(pending(s.core))
        self.reload(s)

    def test_pending_gates_progress_and_failed_write_can_retry(self):
        s = self.waiting(self.session())
        before = s.core.log()
        for action in (s.day_off, s.automatic_step, s.open_recruitment,
                       lambda: s.play_with_player(next(iter(s.core.cats)))):
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(s.core.log(), before)
        with patch.object(s.store, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                s.resolve_intake_request('accept')
        self.assertEqual(s.core.log(), before)
        s.resolve_intake_request('accept')
        self.reload(s)

    def test_low_funds_can_decline(self):
        from cat_cafe_sim.core.cafe_intake_request import rules
        legacy = CafeInteractionSession(store=RelationshipStore(self.directory/'low.json'))
        selected = rules(); selected['day'] = 1; selected['candidate']['cost'] = legacy.core.funds
        legacy.core.initialize_intake_request(selected)
        with self.assertRaises(ValueError):
            legacy.resolve_intake_request('accept')
        legacy.resolve_intake_request('decline')
        self.assertFalse(pending(legacy.core))

    def test_open_day_transition_replay_and_existing_candidates(self):
        s = self.session()
        s.open_recruitment()
        s.day_off(); s.day_off()
        while not s.core.closed:
            s.automatic_step()
        s.next_day()
        self.assertTrue(pending(s.core))
        s.resolve_intake_request('accept')
        s.open_recruitment()
        self.assertEqual(len(s.core.recruitment['candidates']), 6)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        self.reload(s)

    def test_return_and_intake_on_same_day_can_both_be_resolved(self):
        s = self.session()
        s.day_off(); s.day_off()
        s.dispatch(next(iter(s.core.cats)))
        s.day_off()
        self.assertTrue(pending(s.core))
        with self.assertRaises(ValueError):
            s.resolve_intake_request('accept')
        event_id = next(iter(s.core.activities['events']))
        s.resolve_activity(event_id)
        s.resolve_intake_request('accept')
        self.reload(s)

    def test_single_cat_core_preserves_added_roster_in_checkpoint_and_replay(self):
        from dataclasses import asdict, replace
        from cat_cafe_sim.core.cafe_interaction import CafeInteractionCore
        from cat_cafe_sim.core.cafe_health import HealthRules
        from cat_cafe_sim.core.cafe_intake_request import rules
        from cat_cafe_sim.core.config import Config
        core = CafeInteractionCore(replace(Config.load(), initial_funds=1000), compact=True)
        core.set_shifts(['cat-1'])
        core.enable_health(asdict(HealthRules.load()))
        selected = rules(); selected['day'] = 1
        core.initialize_intake_request(selected)
        core.resolve_intake_request('accept')
        self.assertEqual(len(core.cats), 2)
        self.assertEqual(restore(checkpoint(core, set())).snapshot(), core.snapshot())
        self.assertEqual(verify_cafe_interaction(core.log()).snapshot(), core.snapshot())

    def test_old_save_remains_without_request(self):
        s = CafeInteractionSession(store=RelationshipStore(self.directory/'old_relations.json'))
        path = self.directory/'old.json'
        save_game(s, path)
        s, _ = load_game(path)
        for _ in range(4):
            s.day_off()
        self.assertIsNone(s.core.intake_request)
        self.assertNotIn('intake_request', s.core.snapshot())

    def test_invalid_request_checkpoint_rejected_even_with_recomputed_digest(self):
        s = self.waiting(self.session())
        data = checkpoint(s.core, set())
        for change in (lambda d: d.update(status='accepted'), lambda d: d.update(presented_day=3),
                       lambda d: d.update(resolved_day=4), lambda d: d['rules'].update(cat_id=next(iter(s.core.cats)))):
            bad = copy.deepcopy(data)
            change(bad['state']['intake_request'])
            bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)
