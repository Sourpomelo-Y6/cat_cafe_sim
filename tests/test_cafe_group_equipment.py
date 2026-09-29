import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_cafe_seat_equipment as fixtures
from cat_cafe_sim.core.cafe_seat_equipment import catalog, definition, effects, owned, expenses, description
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, digest, restore
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction, verify_relationship
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.cafe_saves import save_game


def grouped():
    return [row for row in catalog() if 'group' in row]


class GroupEquipmentTests(unittest.TestCase):
    setUp = fixtures.SeatEquipmentTests.setUp
    session = fixtures.SeatEquipmentTests.session
    reload = fixtures.SeatEquipmentTests.reload

    def test_catalog_preserves_old_rules_and_rejects_wrong_group_definitions(self):
        self.assertEqual(catalog()[:2], [dict(id='toys', name='おもちゃセット', cost=300, engagement=1.2, tension=1),
                                       dict(id='cushion', name='くつろぎクッション', cost=300, engagement=1, tension=1.2)])
        self.assertEqual({row['group'] for row in grouped()}, {'play', 'contact', 'quiet'})
        for change in (dict(group='unknown'), dict(group='contact'), dict(engagement=1), dict(tension=1.2), dict(cost=True)):
            with self.assertRaises(ValueError): definition(dict(grouped()[0], **change))
        for row in (dict(catalog()[0], group='play'), {k:v for k,v in grouped()[0].items() if k!='group'}):
            with self.assertRaises(ValueError): definition(row)

    def test_each_equipment_boosts_only_matching_types_without_changing_other_effects(self):
        base = RelationshipConfig()
        for row in grouped():
            enhanced = replace(base, equipment_group=row['group'], equipment_engagement_multiplier=row['engagement'])
            for kind in base.types:
                a = RelationshipInteraction(base); b = RelationshipInteraction(enhanced)
                if kind.id != 'teaser':
                    a.step('switch', kind.id); b.step('switch', kind.id)
                first, second = a.step('direct'), b.step('direct')
                matched = kind.group == row['group']
                self.assertAlmostEqual(second['engagement_gain'], first['engagement_gain'] * (1.35 if matched else 1))
                self.assertEqual(second['tension_effect'], first['tension_effect'])
                self.assertEqual(second['stamina_spent'], first['stamina_spent'])
                self.assertEqual(second['affinity_breakdown'], first['affinity_breakdown'])
                self.assertEqual(second['normal_reaction'], first['normal_reaction'])
                self.assertEqual(second['diagnostic'].get('equipment_group'), row['group'] if matched else None)
                self.assertEqual(verify_relationship(b.log()).observation(), b.observation())

    def test_zero_gain_special_actions_and_mastery_multiplication(self):
        for group in ('play', 'contact', 'quiet'):
            base = RelationshipConfig(mastery_group=group, mastery_engagement_multiplier=1.1)
            enhanced = replace(base, equipment_group=group, equipment_engagement_multiplier=1.35)
            kind = next(row.id for row in base.types if row.group==group)
            a = RelationshipInteraction(base); b = RelationshipInteraction(enhanced)
            if kind != 'teaser': a.step('switch',kind); b.step('switch',kind)
            first, second = a.step('direct'), b.step('direct')
            self.assertAlmostEqual(second['engagement_gain'], first['engagement_gain']*1.35)
            self.assertEqual(second['diagnostic']['mastery_multiplier'], 1.1)
            for action, gauges in (('pause',{}),('connect',dict(tension=100)),('direct',dict(engagement=100))):
                first = RelationshipInteraction(base, **gauges).step(action)
                second = RelationshipInteraction(enhanced, **gauges).step(action)
                self.assertEqual(second['tension_effect'], first['tension_effect'])
            empty = replace(enhanced, personality=Personality(type_preferences=(0,)*8))
            record = RelationshipInteraction(empty).step('direct')
            self.assertEqual(record['engagement_gain'], 0)
            self.assertNotIn('equipment_multiplier', record['diagnostic'])

    def test_group_settings_validate_and_legacy_config_and_logs_omit_new_field(self):
        old = RelationshipConfig(equipment_engagement_multiplier=1.2)
        self.assertNotIn('equipment_group', old.to_dict()['rules'])
        self.assertEqual(RelationshipConfig.from_dict(old.to_dict()), old)
        legacy = RelationshipInteraction(old); legacy.step('direct')
        self.assertNotIn('equipment_group', legacy.log()['config']['rules'])
        self.assertEqual(verify_relationship(legacy.log()).observation(), legacy.observation())
        for values in (dict(equipment_group='unknown'), dict(equipment_group='play'),
                       dict(equipment_group='play', equipment_engagement_multiplier=1.35, equipment_tension_multiplier=1.2)):
            with self.assertRaises(ValueError): RelationshipConfig(**values)

    def test_purchase_install_active_resume_and_replay_in_single_and_multiple_seats(self):
        for seats in (1,2):
            for row in grouped():
                s = self.session(seats, funds=2000)
                s.purchase_seat_equipment('seat-1', row)
                self.assertIn(row['name'], description(s.core, 'seat-1'))
                self.assertEqual(s.core.funds, 1550)
                s.step(); s.start('guest-1', next(iter(s.core.cats)), 'seat-1')
                self.assertEqual(s.active_interactions['seat-1'].config.equipment_group, row['group'])
                self.assertEqual(s.active_interactions['seat-1'].config.equipment_engagement_multiplier, 1.35)
                with patch('cat_cafe_sim.core.cafe_seat_equipment.catalog', side_effect=AssertionError('reload config')):
                    s = self.reload(s)
                    while not s.core.closed: s.automatic_step()
                    self.reload(s)
                    self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(), s.core.snapshot())

    def test_move_replace_remove_expansion_finance_and_failed_save_keep_rules(self):
        s = self.session(funds=2500)
        s.purchase_seat_equipment('seat-1', grouped()[0])
        s.purchase_seat_equipment('seat-1', grouped()[1])
        s.equip_seat('seat-2', 'equipment-1')
        self.assertEqual(effects(s.core,'seat-2')['equipment_group'], 'play')
        self.assertEqual(effects(s.core,'seat-1')['equipment_group'], 'contact')
        s.equip_seat('seat-1')
        self.assertEqual(effects(s.core,'seat-1')['equipment_group'], '')
        s.expand_seats(dict(cost=100)); s.equip_seat('seat-3', 'equipment-2')
        before = s.core.snapshot()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write', side_effect=OSError('full')):
            with self.assertRaises(OSError): save_game(s,self.path)
        self.assertEqual(s.core.snapshot(), before)
        s = self.reload(s); s.day_off()
        self.assertEqual(s.core.day_results[0]['summary']['seat_equipment_expenses'], 900)
        self.assertEqual(expenses(s.core), 900)
        self.assertEqual(len(owned(s.core)), 2)
        self.reload(s)

    def test_automatic_service_combines_equipment_with_acquired_mastery(self):
        from cat_cafe_sim.core.cafe_growth import rules
        s = self.session(funds=2000)
        s.core.initialize_growth(dict(rules(), threshold=1, mastery_threshold=1))
        s.purchase_seat_equipment('seat-1', grouped()[0])
        key = next(iter(s.core.cats))
        s.step(); s.start('guest-1',key,'seat-1')
        s.step('direct'); s.step('direct')
        s.resolve_growth(key,'service'); s.resolve_growth_mastery(key,'play')
        s.start('guest-2',key,'seat-1'); s.automatic_step()
        record = next(event['record'] for event in reversed(s.core.events) if event['kind']=='human_cat_action')
        self.assertEqual(record['diagnostic']['equipment_group'],'play')
        self.assertEqual(record['diagnostic']['equipment_multiplier'],1.35)
        self.assertEqual(record['diagnostic']['mastery_multiplier'],1.1)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_new_price_boundary_and_player_interaction_has_no_group_equipment(self):
        s = self.session(funds=450); before = s.core.snapshot()
        with self.assertRaises(ValueError): s.purchase_seat_equipment('seat-1', grouped()[0])
        self.assertEqual(s.core.snapshot(), before)
        s = self.session(funds=451); s.purchase_seat_equipment('seat-1', grouped()[0])
        self.assertEqual(s.core.funds, 1)
        s.play_with_player(next(iter(s.core.cats)))
        from cat_cafe_sim.core.cafe_player import current
        self.assertEqual(current(s.core).config.equipment_group, '')
        self.assertEqual(current(s.core).config.equipment_engagement_multiplier, 1)
        s.player_command(finish=True); self.reload(s)

    def test_corrupt_active_group_and_purchase_group_are_rejected(self):
        s = self.session(); s.purchase_seat_equipment('seat-1', grouped()[0])
        s.step(); s.start('guest-1', next(iter(s.core.cats)), 'seat-1')
        original = checkpoint(s.core,set())
        for mutate in (
                lambda state: state['interactions']['seat-1']['config']['rules'].update(equipment_group='contact'),
                lambda state: state['interactions']['seat-1']['config']['rules'].pop('equipment_group'),
                lambda state: state['equipment_store']['purchases'][0]['rules'].update(group='quiet'),
                lambda state: state['equipment_store']['purchases'][0]['rules'].update(engagement=1.5)):
            bad = copy.deepcopy(original); mutate(bad['state'])
            bad['digest'] = digest({key:value for key,value in bad.items() if key!='digest'})
            with self.assertRaises(ValueError): restore(bad)


@unittest.skipUnless(os.environ.get('CAT_CAFE_TEST_GUI') == '1', 'set CAT_CAFE_TEST_GUI=1 on a desktop')
class GroupEquipmentWindowTests(unittest.TestCase):
    setUp = fixtures.SeatEquipmentTests.setUp
    session = fixtures.SeatEquipmentTests.session

    def test_group_catalog_effects_purchase_cancel_move_and_minimum_layout(self):
        import tkinter as tk
        from cat_cafe_sim.cafe_seat_equipment_gui import CafeSeatEquipmentWindow
        root = tk.Tk(); self.addCleanup(root.destroy)
        s = self.session(funds=2000)
        window = CafeSeatEquipmentWindow(root,s,lambda:None)
        self.assertEqual(len(window.kind_selector['values']),5)
        for row, label in zip(grouped(), ('遊び','触れ合い','静かな交流')):
            window.kind.set(row['name']); window.refresh()
            self.assertIn(label+'の通常行動のみ',window.detail.get())
            self.assertIn('1.35',window.detail.get())
            self.assertIn('購入後の資金 1550',window.detail.get())
        window.window.geometry('620x460'); root.update()
        before = s.core.snapshot()
        with patch('tkinter.messagebox.askyesno',return_value=False): window.purchase_button.invoke()
        self.assertEqual(s.core.snapshot(),before)
        with patch('tkinter.messagebox.askyesno',return_value=True): window.purchase_button.invoke()
        self.assertIn('静かな交流',window.layout.get())
        window.seat.set('seat-2'); window.equip_button.invoke()
        self.assertEqual(effects(s.core,'seat-2')['equipment_group'],'quiet')
        window.remove_button.invoke()
        self.assertEqual(effects(s.core,'seat-2')['equipment_group'],'')
        for button in (window.purchase_button,window.equip_button,window.remove_button):
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),window.window.winfo_rooty()+window.window.winfo_height())


if __name__ == '__main__': unittest.main()
