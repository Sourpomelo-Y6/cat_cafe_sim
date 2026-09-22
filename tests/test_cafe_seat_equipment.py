import copy
import unittest
from dataclasses import replace
from unittest.mock import patch
import test_cafe_patron as fixtures
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.cafe_seat_equipment import catalog, owned, effects, expenses
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig, RelationshipInteraction
from cat_cafe_sim.core.config import Config


class SeatEquipmentTests(unittest.TestCase):
    setUp=fixtures.PatronTests.setUp
    reload=fixtures.PatronTests.reload

    def session(self, seats=2, funds=1000):
        return CafeInteractionSession(store=self.store, seat_count=seats,
            cafe_config=replace(Config.load(), initial_funds=funds, opening_ticks=5, arrival_ticks=(0,0)),
            interaction_config=replace(RelationshipConfig(), ticks=2))

    def test_purchase_move_remove_expand_expenses_and_resume(self):
        s=self.session()
        s.enable_management()
        s.purchase_seat_equipment('seat-1',catalog()[0])
        s.purchase_seat_equipment('seat-1',catalog()[1])
        self.assertEqual(s.core.funds,400)
        self.assertEqual(len(owned(s.core)),2)
        s.equip_seat('seat-2','equipment-2')
        self.assertIsNone(s.core.seats['seat-1'].equipment)
        s.equip_seat('seat-1','equipment-1')
        s.expand_seats(dict(cost=100))
        self.assertIsNone(s.core.seats['seat-3'].equipment)
        s.equip_seat('seat-3','equipment-1')
        s.purchase_rest_space(dict(cost=100,recovery_bonus=10))
        self.assertEqual(s.core.funds,200)
        s=self.reload(s)
        s.day_off()
        summary=s.core.day_results[0]['summary']
        self.assertEqual(summary['seat_equipment_expenses'],600)
        self.assertEqual(summary['equipment_expenses'],100)
        self.assertEqual(summary['expansion_expenses'],100)
        self.assertEqual(expenses(s.core,2),0)
        s.equip_seat('seat-3')
        self.assertEqual(len(owned(s.core)),2)
        s=self.reload(s)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        with patch('cat_cafe_sim.core.cafe_seat_equipment.catalog',side_effect=AssertionError('設定の再読込')):
            self.reload(s)

    def test_effects_normal_special_and_default_serialization(self):
        config=RelationshipConfig()
        for key in ('equipment_engagement_multiplier','equipment_tension_multiplier'):
            self.assertNotIn(key,config.to_dict()['rules'])
        enhanced=replace(config,equipment_engagement_multiplier=1.2,equipment_tension_multiplier=1.2,customer_tension_multiplier=1.25)
        baseline=RelationshipInteraction(config)
        boosted=RelationshipInteraction(enhanced)
        a,b=baseline.step('direct'),boosted.step('direct')
        self.assertAlmostEqual(b['engagement_gain'],a['engagement_gain']*1.2)
        self.assertAlmostEqual(b['tension_effect'],a['tension_effect']*1.5)
        self.assertEqual(b['stamina_spent'],a['stamina_spent'])
        self.assertEqual(b['affinity_breakdown'],a['affinity_breakdown'])
        self.assertEqual(boosted._tension_effect(-5,False),-5)
        self.assertEqual(boosted._tension_effect(20,True),20)
        for action, gauges in (('pause',{}),('connect',dict(tension=100)),('direct',dict(engagement=100))):
            a=RelationshipInteraction(config,**gauges).step(action)
            b=RelationshipInteraction(enhanced,**gauges).step(action)
            self.assertEqual(a['tension_effect'],b['tension_effect'])
        for field in ('equipment_engagement_multiplier','equipment_tension_multiplier'):
            for value in (0,3,True,float('inf')):
                with self.assertRaises(ValueError):
                    replace(config,**{field:value})

    def test_single_and_multi_assignment_active_save_and_replay(self):
        for count in (1,2):
            s=self.session(count)
            s.purchase_seat_equipment('seat-1',catalog()[0])
            if count==2:
                s.purchase_seat_equipment('seat-2',catalog()[1])
            s.step()
            keys=list(s.core.cats)
            s.start('guest-1',keys[0])
            if count==2:
                s.start('guest-2',keys[1])
            for seat,interaction in s.active_interactions.items():
                for field,value in effects(s.core,seat).items():
                    self.assertEqual(getattr(interaction.config,field),value)
            s=self.reload(s)
            before=s.core.snapshot()
            for action in (lambda:s.equip_seat('seat-1'),lambda:s.purchase_seat_equipment('seat-1',catalog()[0])):
                with self.assertRaises(ValueError):
                    action()
                self.assertEqual(s.core.snapshot(),before)
            while not s.core.closed:
                s.automatic_step()
            s=self.reload(s)
            self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_invalid_and_unaffordable_operations_are_atomic_legacy_unchanged(self):
        s=self.session(funds=300)
        before=s.core.snapshot()
        for seat in ('seat-1','unknown'):
            with self.assertRaises(ValueError):
                s.purchase_seat_equipment(seat,catalog()[0])
            self.assertEqual(s.core.snapshot(),before)
        self.assertNotIn('equipment_store',s.core.snapshot())
        self.assertIsNone(self.reload(s).core.equipment_store)
        with self.assertRaises(ValueError):
            s.equip_seat('seat-1','equipment-1')
        s=self.session(funds=301)
        s.purchase_seat_equipment('seat-1',catalog()[0])
        self.assertEqual(s.core.funds,1)
        self.reload(s)

    def test_corrupt_inventory_assignment_cost_and_interaction_rejected(self):
        s=self.session()
        s.purchase_seat_equipment('seat-1',catalog()[0])
        s.purchase_seat_equipment('seat-2',catalog()[1])
        s.step()
        s.start('guest-1',next(iter(s.core.cats)),'seat-1')
        source=checkpoint(s.core,set())
        for mode in ('duplicate','unowned','cost','day','effect'):
            bad=copy.deepcopy(source)
            if mode=='duplicate':
                bad['state']['seats']['seat-2']['equipment']='equipment-1'
            elif mode=='unowned':
                bad['state']['seats']['seat-1']['equipment']='equipment-99'
            elif mode=='cost':
                bad['state']['equipment_store']['purchases'][0]['rules']['cost']=1
            elif mode=='day':
                bad['state']['equipment_store']['purchases'][0]['day']=2
            else:
                bad['state']['equipment_store']['purchases'][0]['rules']['engagement']=1.5
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):
                restore(bad)

    def test_pending_player_exchange_and_failed_save_do_not_repurchase(self):
        from cat_cafe_sim.storage.cafe_saves import save_game
        s=self.session()
        s.play_with_player(next(iter(s.core.cats)))
        before=s.core.snapshot()
        with self.assertRaises(ValueError):
            s.purchase_seat_equipment('seat-1',catalog()[0])
        self.assertEqual(s.core.snapshot(),before)
        s.player_command(finish=True)
        s.purchase_seat_equipment('seat-1',catalog()[0])
        before=s.core.snapshot()
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):
                save_game(s,self.path)
        self.assertEqual(s.core.snapshot(),before)
        s=self.reload(s)
        self.assertEqual(s.core.funds,700)
        self.assertEqual(len(owned(s.core)),1)
        s.play_with_player(next(iter(s.core.cats)))
        from cat_cafe_sim.core.cafe_player import current
        self.assertEqual(current(s.core).config.equipment_engagement_multiplier,1)
