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
from cat_cafe_sim.core.cafe_growth import (
    TYPE_GROUPS, MASTERY_GROUPS, begin_second_group_type_practice, description,
    interaction_terms, learned_types, rules, service, summary, type_mastery_choices,
    type_mastery_pending, second_group_type_mastery_pending,
)
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.policies.human_cat import AutomaticInteractionPolicy
from cat_cafe_sim.storage.cafe_saves import load_game, save_game
from cat_cafe_sim.storage.playtest_cats import add_playtest_cats
from cat_cafe_sim.storage.relationships import RelationshipStore


class SecondGroupTypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RelationshipStore(Path(self.temp.name)/'relationships.json')
        add_playtest_cats(self.store)
        self.path = Path(self.temp.name)/'game.json'

    def session(self, seats=2, legacy=False):
        s = CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), opening_ticks=40, max_wait_ticks=40, arrival_ticks=(0, 1, 2, 3, 4)),
            interaction_config=replace(RelationshipConfig(), ticks=4, confused_threshold=3, favorable_threshold=5))
        selected = dict(rules(), threshold=1, mastery_threshold=1, second_mastery_threshold=3,
                        type_mastery_threshold=3, second_type_mastery_threshold=3)
        if legacy:
            selected.pop('second_mastery_threshold')
        s.core.initialize_growth(selected)
        return s

    def prepare(self, seats=2):
        s = self.session(seats)
        key = next(iter(s.core.cats))
        s.step()
        s.start('guest-1', key, 'seat-1')
        for _ in range(4):
            s.step('direct')
        s.resolve_growth(key, 'service')
        s.resolve_growth_mastery(key, 'play')
        s.start('guest-2', key, 'seat-1')
        s.step('switch', 'brush')
        for _ in range(3):
            s.step('direct')
        s.resolve_growth_mastery(key, 'contact')
        return s, key

    def qualify(self, s, key):
        s.start('guest-3', key, 'seat-1')
        s.step('switch', 'brush')
        for _ in range(3):
            s.step('direct')

    def reload(self, s):
        save_game(s, self.path)
        loaded, _ = load_game(self.path)
        self.assertEqual(loaded.core.snapshot(), s.core.snapshot())
        return loaded

    def gain(self, s, key, actions, affinity=1):
        service(s.core, dict(cat_id=key, stamina_spent=0, affinity_delta=affinity, type_actions=actions))

    def test_actual_service_one_and_multiple_seats_pending_save_and_replay(self):
        for seats in (1, 2):
            s, key = self.prepare(seats)
            self.assertNotIn('second_group_type_practice', s.core.growth['cats'][key])
            self.qualify(s, key)
            self.assertEqual(second_group_type_mastery_pending(s.core), [key])
            self.assertEqual(type_mastery_choices(s.core, key), ('brush',))
            for action in (s.automatic_step, s.day_off, s.next_day):
                with self.assertRaisesRegex(ValueError, '得意な行動'):
                    action()
            with patch('cat_cafe_sim.core.cafe_growth.rules', side_effect=lambda data:rules(data)):
                s = self.reload(s)
            s.resolve_growth_type_mastery(key, 'brush')
            row = s.core.growth['cats'][key]
            self.assertIsNone(row['type_mastery'])  # First category's slot stays available.
            self.assertEqual(learned_types(row), ('brush',))
            self.assertIn('ブラッシング', summary(s.core, key))
            self.assertIn('2つ目の分類（触れ合い）の得意な行動', description(s.core, key))
            self.assertIn('接客実績：遊び', description(s.core, key))
            self.assertEqual(dict(cat_details(s, key)['basic'])['2つ目の分類の得意な行動'], 'ブラッシング')
            self.assertIn('2つ目の分類の得意な行動の選択', str(cat_events(s.core, key)))
            s.start('guest-4', key, 'seat-1')
            s = self.reload(s)
            active = s.active_interactions['seat-1']
            self.assertEqual(active.config.second_group_type_mastery, 'brush')
            self.assertEqual(active.config.type_mastery_engagement_multiplier, 1.05)
            for _ in range(4):
                s.step('switch', 'brush') if s.active_interactions['seat-1'].state['mode'] != 'brush' else s.step('direct')
            self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
            self.assertEqual(sum(e['kind']=='growth_second_group_type_mastery_selected' for e in s.core.events), 1)

    def test_only_post_selection_successful_normal_actions_count(self):
        s, key = self.prepare()
        row = s.core.growth['cats'][key]
        before = copy.deepcopy(row)
        begin_second_group_type_practice(s.core, key)
        self.assertEqual(sum(row['second_group_type_practice']['actions'].values()), 0)
        self.assertEqual(row['second_mastery_groups'], before['second_mastery_groups'])
        self.gain(s, key, {'teaser':2, 'voice':20, 'switch':30, 'connect':30, 'pause':30})
        self.gain(s, key, {'brush':30}, 0)
        self.gain(s, key, {'pet':30}, -1)
        self.assertEqual(sum(row['second_group_type_practice']['actions'].values()), 0)
        self.gain(s, key, {'brush':2})
        self.assertEqual(second_group_type_mastery_pending(s.core), [])
        self.gain(s, key, {'pet':1})
        self.assertEqual(type_mastery_choices(s.core, key), ('pet', 'brush'))
        self.gain(s, key, {'brush':1})
        self.assertEqual(sum(e['kind']=='growth_second_group_type_mastery_ready' for e in s.core.events), 1)
        s.resolve_growth_type_mastery(key, 'pet')
        self.gain(s, key, {'brush':30})
        self.assertEqual(second_group_type_mastery_pending(s.core), [])
        with self.assertRaises(ValueError):
            s.resolve_growth_type_mastery(key, 'brush')

    def test_all_distinct_group_pairs_and_all_eight_action_candidates(self):
        representatives = {'play':'teaser', 'contact':'brush', 'quiet':'voice'}
        for first in MASTERY_GROUPS:
            for second in MASTERY_GROUPS:
                if first == second:
                    continue
                s = self.session()
                key = next(iter(s.core.cats))
                self.gain(s, key, {representatives[first]:1})
                s.resolve_growth(key, 'service')
                s.resolve_growth_mastery(key, first)
                self.gain(s, key, {representatives[second]:3})
                s.resolve_growth_mastery(key, second)
                begin_second_group_type_practice(s.core, key)
                actions = {kind:3 for kind, group in TYPE_GROUPS.items() if group==second}
                self.gain(s, key, actions)
                self.assertEqual(set(type_mastery_choices(s.core, key)), set(actions))
                s.resolve_growth_type_mastery(key, next(iter(actions)))
                self.assertEqual(len(learned_types(s.core.growth['cats'][key])), 1)

    def test_first_two_slots_remain_and_simultaneous_choices_are_ordered(self):
        s, key = self.prepare()
        begin_second_group_type_practice(s.core, key)
        self.gain(s, key, {'teaser':3, 'brush':3})
        self.assertEqual(type_mastery_pending(s.core), [key])
        self.assertEqual(type_mastery_choices(s.core, key), ('teaser',))
        s.resolve_growth_type_mastery(key, 'teaser')
        self.gain(s, key, {'ball':3})
        self.assertEqual(type_mastery_choices(s.core, key), ('ball',))
        s.resolve_growth_type_mastery(key, 'ball')
        self.assertEqual(type_mastery_choices(s.core, key), ('brush',))
        s.resolve_growth_type_mastery(key, 'brush')
        self.assertEqual(learned_types(s.core.growth['cats'][key]), ('teaser', 'ball', 'brush'))
        self.assertEqual(type_mastery_pending(s.core), [])
        with self.assertRaises(ValueError):
            s.resolve_growth_type_mastery(key, 'brush')

    def test_effects_multiply_once_and_leave_other_actions_unchanged(self):
        for kind, group in TYPE_GROUPS.items():
            first = 'contact' if group=='play' else 'play'
            base = replace(RelationshipConfig(), mastery_group=first, second_mastery_group=group,
                mastery_engagement_multiplier=1.1, equipment_group=group, equipment_engagement_multiplier=1.35)
            config = replace(base, second_group_type_mastery=kind, type_mastery_engagement_multiplier=1.05)
            for mode in TYPE_GROUPS:
                plain = RelationshipInteraction(base)
                skilled = RelationshipInteraction(config)
                if mode != 'teaser':
                    plain.step('switch', mode)
                    skilled.step('switch', mode)
                a = plain.step('direct')
                b = skilled.step('direct')
                self.assertAlmostEqual(b['engagement_delta'], a['engagement_delta']*(1.05 if mode==kind else 1))
                self.assertEqual(b['stamina_spent'], a['stamina_spent'])
                self.assertEqual(b['tension_delta'], a['tension_delta'])
                self.assertNotIn('type_mastery_multiplier', skilled.step('pause')['diagnostic'])
                skilled.finish()
                self.assertEqual(verify_relationship(skilled.log()).result(), skilled.result())
            special = RelationshipInteraction(config, tension=100)
            self.assertNotIn('type_mastery_multiplier', special.step('connect')['diagnostic'])

    def test_policy_customer_priority_and_boredom_with_three_learned_types(self):
        policy = AutomaticInteractionPolicy()
        for first_types in ({}, dict(type_mastery='teaser', second_type_mastery='ball')):
            base = replace(RelationshipConfig(), mastery_group='play', second_mastery_group='contact',
                mastery_engagement_multiplier=1.1, second_group_type_mastery='brush',
                type_mastery_engagement_multiplier=1.05, **first_types)
            for flag, expected in ((None, 'play'), ('contact_service', 'contact'), ('quiet_service', 'quiet')):
                config = replace(base, **({flag:True} if flag else {}))
                active = RelationshipInteraction(config)
                action, target = policy.choose(active.observation(), active.valid_actions(), config)
                chosen = target if action=='switch' else active.state['mode']
                self.assertEqual(TYPE_GROUPS[chosen], expected)
                if flag=='contact_service':
                    self.assertEqual(chosen, 'brush')
                if action=='switch':
                    active.step(action, target)
                active.step('direct'); active.step('direct')
                action, target = policy.choose(active.observation(), active.valid_actions(), config)
                self.assertEqual(action, 'switch')
                self.assertNotEqual(TYPE_GROUPS[target], expected)
            low = RelationshipInteraction(base, stamina=10)
            self.assertEqual(policy.choose(low.observation(), low.valid_actions(), base), ('pause', None))

    def test_old_save_old_log_and_inflight_service_are_preserved(self):
        s, key = self.prepare()
        source = s.core.log()
        self.assertNotIn('second_group_type_practice', s.core.growth['cats'][key])
        self.assertEqual(verify_cafe_interaction(source).snapshot(), s.core.snapshot())
        s = self.reload(s)
        self.assertNotIn('second_group_type_practice', s.core.growth['cats'][key])
        # An older in-flight service has no opt-in operation and finishes unchanged.
        terms = interaction_terms(s.core, key)
        config = replace(s.interaction_config, mastery_group=terms['group'], second_mastery_group=terms['second_group'], mastery_engagement_multiplier=terms['multiplier'])
        interaction = self.store.begin(config, key, 'guest-3', stamina=s.core.cats[key].stamina)
        s.core.start(interaction, 'seat-1')
        s = self.reload(s)
        s.step('switch', 'brush')
        for _ in range(3):
            s.step('direct')
        self.assertNotIn('second_group_type_practice', s.core.growth['cats'][key])
        s.start('guest-4', key, 'seat-1')
        self.assertEqual(sum(s.core.growth['cats'][key]['second_group_type_practice']['actions'].values()), 0)
        s = self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())
        legacy = self.session(legacy=True)
        other = next(iter(legacy.core.cats))
        with self.assertRaises(ValueError):
            begin_second_group_type_practice(legacy.core, other)
        self.assertNotIn('second_group_type_practice', legacy.core.growth['cats'][other])
        old = RelationshipInteraction(replace(RelationshipConfig(), mastery_group='play', mastery_engagement_multiplier=1.1))
        old.step('direct'); old.finish()
        self.assertNotIn('second_group_type_mastery', old.log()['config']['rules'])
        self.assertEqual(verify_relationship(old.log()).result(), old.result())

    def test_failed_start_does_not_enable_practice_and_pending_write_retries_once(self):
        s, key = self.prepare()
        before = s.core.log()
        with self.assertRaises(ValueError):
            s.start('unknown', key, 'seat-1')
        self.assertEqual(s.core.log(), before)
        s.start('guest-3', key, 'seat-1')
        s.step('switch', 'brush'); s.step('direct'); s.step('direct')
        with patch.object(s.store, 'apply', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                s.step('direct')
        with self.assertRaises(ValueError):
            s.resolve_growth_type_mastery(key, 'brush')
        s = self.reload(s)
        s.persist()
        s.resolve_growth_type_mastery(key, 'brush')
        s = self.reload(s)
        row = s.core.growth['cats'][key]['second_group_type_practice']
        self.assertEqual(row['actions']['brush'], 3)
        self.assertEqual(sum(e['kind']=='growth_second_group_type_mastery_ready' for e in s.core.events), 1)
        self.assertEqual(sum(e['kind']=='growth_second_group_type_mastery_selected' for e in s.core.events), 1)

    def test_corrupt_records_and_active_interaction_terms_rejected(self):
        s, key = self.prepare()
        self.qualify(s, key)
        s.resolve_growth_type_mastery(key, 'brush')
        source = checkpoint(s.core, set())
        for changes in (dict(started_day=0), dict(selected_day=True), dict(type_mastery='teaser'),
                        dict(type_mastery='pet'), dict(actions=dict.fromkeys(TYPE_GROUPS, True)),
                        dict(actions=dict.fromkeys(TYPE_GROUPS, 0)), dict(extra=True)):
            bad = copy.deepcopy(source)
            bad['state']['growth']['cats'][key]['second_group_type_practice'].update(changes)
            bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)
        for changes in (dict(second_group_type_mastery='brush'),
                        dict(mastery_group='play', second_mastery_group='contact', mastery_engagement_multiplier=1.1,
                             second_group_type_mastery='teaser', type_mastery_engagement_multiplier=1.05)):
            with self.assertRaises(ValueError):
                replace(RelationshipConfig(), **changes)
        s.start('guest-4', key, 'seat-1')
        bad = checkpoint(s.core, set())
        bad['state']['interactions']['seat-1']['config']['rules'].pop('second_group_type_mastery')
        bad['state']['interactions']['seat-1']['config']['rules'].pop('type_mastery_engagement_multiplier')
        bad['digest'] = digest({k:v for k,v in bad.items() if k!='digest'})
        with self.assertRaises(ValueError):
            restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI')=='1', 'requires a display')
class SecondGroupTypeGuiTests(unittest.TestCase):
    setUp = SecondGroupTypeTests.setUp
    session = SecondGroupTypeTests.session
    prepare = SecondGroupTypeTests.prepare
    qualify = SecondGroupTypeTests.qualify

    def test_attention_selection_details_and_minimum_size(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_interaction_gui import CafeInteractionWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        s, key = self.prepare()
        self.qualify(s, key)
        app = CafeInteractionWindow(root, s)
        self.assertIn('2つ目の分類の個別行動', app.notice.get())
        self.assertTrue(app.run_button.instate(['disabled']))
        app.attention_button.invoke()
        dialog = app.growth_window
        dialog.window.geometry('540x300'); root.update()
        self.assertEqual(set(dialog.choice_buttons), {'brush'})
        button = dialog.choice_buttons['brush']
        self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), dialog.window.winfo_rootx()+dialog.window.winfo_width())
        button.invoke()
        self.assertIn('ブラッシング', app.roster.set(key, 'growth'))
        self.assertIn('2つ目の分類（触れ合い）の得意な行動', app.details.get())
        self.assertFalse(second_group_type_mastery_pending(s.core))

    def test_close_keeps_pending_and_four_play_actions_fit(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_cat_growth_gui import CafeCatGrowthWindow
        root = tk.Tk()
        self.addCleanup(root.destroy)
        s = self.session()
        key = next(iter(s.core.cats))
        service(s.core, dict(cat_id=key, stamina_spent=0, affinity_delta=1, type_actions={'brush':1}))
        s.resolve_growth(key, 'service'); s.resolve_growth_mastery(key, 'contact')
        service(s.core, dict(cat_id=key, stamina_spent=0, affinity_delta=1, type_actions={'teaser':3}))
        s.resolve_growth_mastery(key, 'play')
        begin_second_group_type_practice(s.core, key)
        service(s.core, dict(cat_id=key, stamina_spent=0, affinity_delta=1,
                            type_actions={kind:3 for kind, group in TYPE_GROUPS.items() if group=='play'}))
        window = CafeCatGrowthWindow(root, s, lambda:None)
        window.window.geometry('540x300'); root.update()
        self.assertEqual(set(window.choice_buttons), {'teaser', 'ball', 'plush', 'tunnel'})
        for button in window.choice_buttons.values():
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), window.window.winfo_rooty()+window.window.winfo_height())
        window.close()
        self.assertEqual(second_group_type_mastery_pending(s.core), [key])
