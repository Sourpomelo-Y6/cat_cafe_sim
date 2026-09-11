import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core.human_cat_interaction import HumanCatInteraction, save, verify
from cat_cafe_sim.core.human_cat_special import SpecialConfig, SpecialInteraction
from cat_cafe_sim.human_cat_gui import PlaySession, history_row
from cat_cafe_sim.evaluation.special_actions import compare_special


class SpecialTests(unittest.TestCase):
    def test_specification_examples(self):
        for t, e, action, expected in [
            (0, 0, 'direct', (12, 12, 95, 0, None)),
            (80, 0, 'connect', (0, 0, 100, 50, None)),
            (88, 88, 'direct', (98, 20, 95, 50, None)),
            (80, 80, 'connect', (10, 0, 100, 200, 'success')),
            (100, 80, 'connect', (30, 0, 100, 200, 'success')),
            (99, 70, 'direct', (100, 82, 95, 0, None)),
            (70, 99, 'direct', (82, 100, 95, 0, None)),
            (100, 100, 'connect', (30, 20, 100, 200, 'success'))]:
            with self.subTest(t=t, e=e):
                core = SpecialInteraction(tension=t, engagement=e)
                core.step(action)
                self.assertEqual(tuple(core.state[k] for k in ('tension', 'engagement', 'stamina', 'bonus_funds', 'end_reason')), expected)

    def test_invalid_and_forced_actions_are_atomic(self):
        for tension, action in ((79, 'connect'), (100, 'direct'), (0, [])):
            core = SpecialInteraction(tension=tension)
            before = core.log()
            with self.assertRaises(ValueError):
                core.step(action)
            self.assertEqual(core.log(), before)
        core = SpecialInteraction(tension=99)
        core.step('direct')
        self.assertEqual(core.valid_actions(), ('connect',))
        self.assertEqual(core.step('connect')['connect_source'], 'forced')

    def test_cat_optional_conditions_and_no_lookahead(self):
        for kwargs, expected in (({}, False), ({'tension': 80}, True), ({'stamina': 20}, True)):
            core = SpecialInteraction(engagement=80, **kwargs)
            self.assertEqual(core.cat_will_open(), expected)
        self.assertTrue(SpecialInteraction(SpecialConfig(ticks=1), engagement=80).cat_will_open())
        self.assertFalse(SpecialInteraction(SpecialConfig(ticks=1), engagement=79).cat_will_open())
        core = SpecialInteraction(tension=79, engagement=80)
        r = core.step('direct')
        self.assertEqual(r['cat_action'], 'normal')
        self.assertGreaterEqual(core.state['tension'], 80)
        self.assertTrue(core.cat_will_open())

    def test_reaction_tension_and_floor(self):
        for prefs, stamina, action, delta in [((1,1),100,'intense',20), ((1,1),100,'direct',12),
                ((.5,1),100,'direct',6), ((.4,1),100,'direct',-4), ((1,1),20,'direct',-6), ((0,1),100,'direct',-8)]:
            core=SpecialInteraction(SpecialConfig(preferences=prefs), stamina=stamina, tension=10)
            self.assertEqual(core.step(action)['tension_delta'], delta)
        core=SpecialInteraction(SpecialConfig(preferences=(0,1)))
        self.assertEqual(core.step('direct')['after']['tension'], 0)

    def test_pause_and_switch_do_not_generate_tension(self):
        for action in ('pause','switch'):
            core=SpecialInteraction(tension=20)
            while not core.state['end_reason']:
                core.step(action)
            self.assertEqual(core.state['tension'],20)
            self.assertEqual(core.state['bonus_funds'],0)

    def test_special_and_normal_not_double_counted(self):
        core=SpecialInteraction(tension=80, engagement=80)
        r=core.step('direct')
        self.assertEqual(r['normal_reaction'],'favorable')
        self.assertEqual(r['tension_effect'],10)
        self.assertEqual(core.state['tension'],90)
        self.assertEqual(core.state['previous_reaction'],'favorable')
        self.assertEqual(history_row(r)[2], '心を開く')
        self.assertEqual(r['engagement_spent'],80)
        self.assertEqual(r['engagement_gain'],12)

    def test_connect_keeps_boredom_and_breaks_combo(self):
        core=SpecialInteraction(tension=80)
        core.step('direct')
        core.step('pause')
        core.step('connect')
        self.assertEqual(core.state['interaction_streak'],1)
        self.assertIsNone(core.state['previous_reaction'])
        self.assertEqual(core.step('feint')['diagnostic']['base_gain'],10)

    def test_final_turn_reservation_expiry_and_execution(self):
        core=SpecialInteraction(SpecialConfig(ticks=1), tension=99)
        r=core.step('direct')
        self.assertEqual(core.state['end_reason'],'timeout')
        self.assertTrue(r['expired_reservations']['connect'])
        self.assertFalse(core.state['connect_pending'])
        self.assertEqual(core.state['bonus_funds'],0)
        core=SpecialInteraction(SpecialConfig(ticks=1), tension=100, engagement=100)
        core.step('connect')
        self.assertEqual(core.state['end_reason'],'success')
        self.assertEqual(core.state['bonus_funds'],200)

    def test_exhaustion_beats_success_but_keeps_executed_bonus(self):
        core=SpecialInteraction(SpecialConfig(direct_cost=100), tension=80, engagement=70)
        core.step('connect')
        core.step('direct')
        self.assertEqual(core.state['end_reason'],'exhausted')
        # Cat was below 80 at start; no open_up on this action.
        self.assertEqual(core.state['bonus_funds'],50)
        core=SpecialInteraction(SpecialConfig(direct_cost=100), tension=80, engagement=80)
        core.step('direct')
        self.assertEqual(core.state['bonus_funds'],50)
        self.assertEqual(core.state['end_reason'],'exhausted')

        core=SpecialInteraction(SpecialConfig(ticks=3, direct_cost=100), tension=80, engagement=70)
        core.step('connect')
        core.step('intense')
        core.step('direct')
        self.assertEqual(core.state['connect_count'],1)
        self.assertEqual(core.state['open_up_count'],1)
        self.assertEqual(core.state['end_reason'],'exhausted')
        self.assertEqual(core.state['bonus_funds'],100)

    def test_separate_specials_success_without_simultaneous_bonus(self):
        core=SpecialInteraction(tension=80, engagement=70)
        core.step('connect')
        core.step('direct')
        # Cat waits with interest82 and tension12; make it the last turn through pauses.
        while core.state['remaining_ticks'] > 1:
            core.step('pause')
        core.step('pause')
        self.assertEqual(core.state['end_reason'],'success')
        self.assertEqual(core.state['bonus_funds'],100)
        self.assertEqual(core.state['simultaneous_count'],0)
        before=core.log()
        with self.assertRaises(ValueError):core.step('pause')
        self.assertEqual(core.log(),before)

    def test_overflow_and_no_same_tick_chain(self):
        core=SpecialInteraction(tension=99, engagement=99)
        # Cat opens on start, so interest is consumed before ordinary gain.
        r=core.step('direct')
        self.assertEqual(r['tension_overflow'],9)
        self.assertEqual(core.state['connect_count'],0)
        self.assertTrue(core.state['connect_pending'])
        core=SpecialInteraction(tension=0, engagement=99)
        r=core.step('direct')
        self.assertEqual(r['engagement_overflow'],11)
        self.assertTrue(core.state['open_up_pending'])

    def test_configuration_and_initial_gauges(self):
        self.assertEqual(SpecialConfig.load(),SpecialConfig())
        for kwargs in ({'gauge_cost':81},{'optional_threshold':100},{'forced_threshold':101},
                       {'connect_bonus':-1},{'tension_neutral':float('nan')}):
            with self.assertRaises(ValueError):SpecialConfig(**kwargs)
        for value in (-1,101,float('nan'),True):
            with self.assertRaises(ValueError):SpecialInteraction(tension=value)

    def test_v1_v2_replay_and_tampered_version(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log.json'
            for core in (HumanCatInteraction(),SpecialInteraction(tension=80, engagement=80)):
                core.step('direct' if type(core) is HumanCatInteraction else 'connect')
                save(core,p)
                self.assertEqual(verify(p).log(),core.log())
            data=core.log()
            for modify in (lambda x:x['records'][0]['bonuses'].update(simultaneous=0),
                           lambda x:x.update(rule_version=1), lambda x:x.update(mode_id='other')):
                changed=copy.deepcopy(data);modify(changed);p.write_text(json.dumps(changed))
                with self.assertRaises((ValueError,TypeError)):verify(p)

    def test_ui_session_and_comparison(self):
        ui=PlaySession(SpecialConfig())
        self.assertIsInstance(ui.core,SpecialInteraction)
        ui.restart('1','1','20')
        self.assertEqual(ui.core.state['tension'],0)
        with tempfile.TemporaryDirectory() as d:
            rows=compare_special(SpecialConfig(),Path(d)/'compare.json')
            self.assertEqual(len(rows),32)
            for r in rows:
                self.assertEqual(verify(r['log']).summary()['bonus_funds'],r['bonus_funds'])
