import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_patron import destinations, rules, progression_rules, pending
from cat_cafe_sim.core.cafe_patron_members import IDS, terms, description
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class PatronMemberTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sequence = 0

    def game(self, legacy=False, easy=False):
        self.sequence += 1
        selected = starting_conditions('patron')
        selected['management']['starting_funds'] = 10000
        selected['store_events']['probability'] = 0
        selected.pop('intake_request')
        if legacy:
            selected['patron'].pop('members')
        if easy:
            selected['patron']['target'] = 25
            for row in selected['patron']['members']:
                row['target'] = row['gain']
        return create_game(Path(self.temp.name)/str(self.sequence), selected)

    def reload(self, s):
        save_game(s, s.checkpoint_path)
        restored, _ = load_game(s.checkpoint_path)
        self.assertEqual(restored.core.snapshot(), s.core.snapshot())
        return restored

    def growth(self, s):
        from cat_cafe_sim.core.cafe_growth import pending
        while pending(s.core):
            s.resolve_growth(sorted(pending(s.core))[0], 'service')

    def visit(self, s, member_id, cat='cat-sora'):
        self.growth(s)
        trip = next(r for r in destinations(s.core) if r['id']==member_id)
        s.dispatch(cat, trip)
        event = list(s.core.activities['events'].values())[-1]
        while event['status']=='travelling':
            self.growth(s)
            s.day_off()
        s.resolve_activity(event['id'])
        return event

    def test_new_three_members_and_readonly_preview(self):
        s = self.game()
        before = copy.deepcopy(s.core.snapshot())
        stored = s.store.path.read_bytes()
        self.assertEqual(len(destinations(s.core)), 3)
        self.assertTrue(terms(s.core, 'cat-sora', IDS[0])['matched'])
        self.assertEqual(terms(s.core, 'cat-sora', IDS[0])['gain'], 20)
        self.assertEqual(terms(s.core, 'cat-mike', IDS[0])['gain'], 2)
        self.assertEqual(terms(s.core, 'cat-sora', IDS[1])['gain'], 0)
        self.assertIn('満足度＋0', description(s.core, 'cat-sora', IDS[1]))
        from cat_cafe_sim.cafe_dispatch_comparison import comparison_rows
        self.assertIn('満足度＋20', next(r for r in comparison_rows(s,'cat-sora') if r['destination']['id']==IDS[0])['detail'])
        self.assertEqual(s.core.snapshot(), before)
        self.assertEqual(s.store.path.read_bytes(), stored)

    def test_mood_changes_after_receive_and_departure_condition_is_saved(self):
        s = self.game()
        s.dispatch('cat-sora', destinations(s.core)[1])
        event = list(s.core.activities['events'].values())[-1]
        initial = copy.deepcopy(event['patron_match'])
        self.assertEqual(initial['condition'], {'feature':'white'})
        while event['status']=='travelling':
            s.day_off()
        self.assertEqual(terms(s.core,'cat-sora',IDS[0])['condition'], {'feature':'white'})
        s = self.reload(s)
        event = s.core.activities['events'][event['id']]
        s.resolve_activity(event['id'])
        self.assertEqual(s.core.patron['members'][IDS[0]], 20)
        self.assertEqual(event['patron_match'], initial)
        self.assertEqual(terms(s.core,'cat-sora',IDS[0])['condition'], {'feature':'black'})
        s.resolve_activity(event['id'])
        self.assertEqual(s.core.patron['members'][IDS[0]], 20)
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_mismatch_two_and_strict_zero_do_not_finish_goal(self):
        s = self.game()
        self.visit(s, IDS[0], 'cat-mike')
        self.assertEqual(s.core.patron['members'][IDS[0]], 2)
        self.visit(s, IDS[1], 'cat-sora')
        self.assertEqual(s.core.patron['members'][IDS[1]], 0)
        self.assertFalse(pending(s.core))
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_strict_and_requires_feature_and_service_development(self):
        s = self.game()
        self.assertFalse(terms(s.core,'cat-sora',IDS[1])['matched'])
        for _ in range(20):
            self.growth(s)
            s.day_off()
        self.growth(s)
        self.assertEqual(s.core.growth['cats']['cat-sora']['specialization'],'service')
        self.assertEqual(terms(s.core,'cat-sora',IDS[1])['gain'],25)
        self.assertEqual(terms(s.core,'cat-mike',IDS[1])['gain'],0)
        self.visit(s, IDS[1])
        self.assertEqual(s.core.patron['members'][IDS[1]],25)
        self.reload(s)

    def test_legacy_keeps_one_member_and_saved_configuration(self):
        s = self.game(legacy=True)
        self.assertEqual(len(destinations(s.core)),1)
        self.assertNotIn('members',s.core.patron)
        with patch('cat_cafe_sim.core.cafe_patron.progression_rules', side_effect=AssertionError('設定再読込')):
            self.visit(s,'patron_visit')
            self.reload(s)
        self.assertEqual(s.core.patron['satisfaction'],30)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_all_three_are_required_and_clear_result_uses_total_targets(self):
        s = self.game(easy=True)
        self.visit(s, 'patron_visit')
        self.assertFalse(pending(s.core))
        self.visit(s, IDS[0])
        self.assertFalse(pending(s.core))
        for _ in range(20):
            self.growth(s)
            s.day_off()
        self.growth(s)
        self.visit(s, IDS[1])
        self.assertTrue(pending(s.core))
        self.assertEqual(s.core.clear_results['patron']['target'],70)
        self.assertEqual(s.core.clear_results['patron']['value'],70)
        self.reload(s)
        s.continue_patron()
        s.day_off()
        self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_active_member_and_same_day_second_departure_are_blocked(self):
        s = self.game()
        destination = destinations(s.core)[1]
        s.dispatch('cat-sora',destination)
        before = copy.deepcopy(s.core.snapshot())
        with self.assertRaises(ValueError):s.dispatch('cat-mugi',destination)
        self.assertEqual(s.core.snapshot(),before)

    def test_tampered_gain_condition_and_satisfaction_are_rejected(self):
        s = self.game()
        event = self.visit(s, IDS[0])
        source = checkpoint(s.core, set())
        for change in (
            lambda d:d['state']['patron']['members'].update({IDS[0]:100}),
            lambda d:d['state']['activities']['events'][event['id']]['patron_match'].update(gain=100),
            lambda d:d['state']['activities']['events'][event['id']]['patron_match'].update(condition_index=1),
            lambda d:d['state']['patron'].update(status='cleared',resolved_day=s.core.day)):
            bad = copy.deepcopy(source)
            change(bad)
            bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)

    def test_invalid_rules_and_mood_cycles(self):
        for value in (None, [], {}, True):
            selected = progression_rules(); selected['members']=value
            with self.assertRaises(ValueError):rules(selected)
        s = self.game()
        for cat, feature in [('cat-sora','white'),('cat-mugi','black'),('cat-kohaku','long_hair')]:
            self.assertEqual(terms(s.core,cat,IDS[0])['condition'],{'feature':feature})
            self.visit(s,IDS[0],cat)
        self.assertEqual(terms(s.core,'cat-sora',IDS[0])['condition'],{'feature':'white'})

    @unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1','requires desktop')
    def test_gui_shows_members_and_zero_gain(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_patron_gui import CafePatronWindow
        from cat_cafe_sim.cafe_activity_gui import CafeActivityWindow
        root=tk.Tk();self.addCleanup(root.destroy)
        s=self.game()
        before=copy.deepcopy(s.core.snapshot())
        goal=CafePatronWindow(root,s,lambda:None);self.addCleanup(goal.window.destroy)
        root.update()
        self.assertIn('不一致＋0',goal.details.get())
        self.assertIn('全員',goal.details.get())
        activity=CafeActivityWindow(root,s,lambda:None);self.addCleanup(activity.window.destroy)
        idx=next(i for i,r in enumerate(activity.destinations) if r['id']==IDS[1])
        activity.destination_choice.current(idx);activity.select_destination()
        self.assertIn('満足度＋0',activity.cats.set('cat-sora','参加条件'))
        self.assertEqual(s.core.snapshot(),before)

    def test_popularity_challenge_keeps_all_member_progress_and_expiry_is_independent(self):
        s = self.game()
        self.visit(s, IDS[0])
        before = copy.deepcopy(s.core.patron)
        from cat_cafe_sim.core.cafe_popularity_challenge import rules
        selected = rules(s.core); selected['goal']['days']=1
        s.start_popularity_challenge(selected)
        self.assertEqual(s.core.patron,before)
        s.day_off()
        self.assertEqual(s.core.goal['status'],'expired')
        self.assertEqual(s.core.patron,before)
        s = self.reload(s)
        s.continue_goal()
        self.assertEqual(s.core.patron,before)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
