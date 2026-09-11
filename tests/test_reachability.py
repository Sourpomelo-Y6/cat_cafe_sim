from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cat_cafe_sim.core.human_cat_types import TypesConfig, TypesInteraction, Personality
from cat_cafe_sim.core.human_cat_interaction import save, verify
from cat_cafe_sim.evaluation.reachability import search, fork, commands, retain, diagnose


class ReachabilityTests(unittest.TestCase):
    def test_all_legal_commands_and_reserved_action(self):
        core=TypesInteraction()
        actions=list(commands(core))
        self.assertEqual(len([a for a in actions if a[0]=='switch']),7)
        self.assertNotIn(('switch','teaser'),actions)
        core.step('switch','pet')
        self.assertNotIn(('intense',None),list(commands(core)))
        forced=TypesInteraction(tension=100)
        self.assertEqual(list(commands(forced)),[('connect',None)])

    def test_fork_leaves_parent_and_sibling_unchanged(self):
        core=TypesInteraction();core.step('direct')
        before=core.log()
        a,b=fork(core),fork(core)
        a.step('switch','ball');a.step('direct')
        self.assertEqual(core.log(),before)
        self.assertEqual(b.log(),before)
        self.assertIs(a.config,core.config)

    def test_forced_success_is_replayable_and_does_not_mutate_input(self):
        core=TypesInteraction(tension=100,engagement=100)
        before=core.log()
        result=search(core,width=8)
        self.assertTrue(result['found'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['depth'],1)
        self.assertEqual(result['witness'].state['bonus_funds'],200)
        self.assertEqual(core.log(),before)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'witness.json'
            save(result['witness'],path)
            self.assertEqual(verify(path).log(),result['witness'].log())

    def test_short_tree_exhaustion_and_truncated_search_distinguished(self):
        result=search(TypesInteraction(TypesConfig(ticks=1)),width=1)
        self.assertFalse(result['found'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['reason'],'tree_exhausted')
        result=search(TypesInteraction(),width=1,max_expansions=1)
        self.assertFalse(result['found'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['reason'],'expansion_limit')
        self.assertEqual(result['expanded'],1)
        result=search(TypesInteraction(TypesConfig(ticks=2)),width=1)
        self.assertGreater(result['pruned'],0)
        self.assertFalse(result['complete'])

    def test_success_not_lost_when_limit_hits_in_same_layer(self):
        # connect is before pause in this test enumeration; another command triggers budget limit.
        core=TypesInteraction(tension=80,engagement=80)
        with patch('cat_cafe_sim.evaluation.reachability.commands',return_value=iter([('connect',None),('pause',None)])):
            result=search(core,max_expansions=1)
        self.assertTrue(result['found'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['witness'].state['end_reason'],'success')

    def test_reproducibility_and_terminal_input(self):
        core=TypesInteraction(TypesConfig(ticks=3))
        left=search(core,width=8);right=search(core,width=8)
        self.assertEqual(left.pop('witness').log(),right.pop('witness').log())
        self.assertEqual(left,right)
        terminal=TypesInteraction(tension=100,engagement=100);terminal.step('connect')
        self.assertTrue(search(terminal)['found'])
        terminal=TypesInteraction(TypesConfig(ticks=1));terminal.step('pause')
        self.assertFalse(search(terminal)['found'])
        for kwargs in ({'width':0},{'width':True},{'max_expansions':0}):
            with self.assertRaises(ValueError):search(core,**kwargs)

    def test_report_separates_oracle_and_reactive_and_replays_prefixes(self):
        with tempfile.TemporaryDirectory() as directory, patch('cat_cafe_sim.evaluation.reachability.load_presets',return_value={'test':Personality()}):
            data=diagnose(TypesConfig(ticks=2),Path(directory)/'diagnosis.json',width=2)
            self.assertEqual(len(data['rows']),2)
            for row in data['rows']:
                for name in ('search','reactive'):
                    log=verify(row[name]['log'])
                    self.assertEqual(log.summary(),row[name]['summary'])
                self.assertEqual(row['reactive']['summary']['end_reason'],'timeout')


class ReactiveCandidateTests(unittest.TestCase):
    def test_candidate_changes_only_direct_after_listless(self):
        from cat_cafe_sim.evaluation.interaction_types import choose
        from cat_cafe_sim.evaluation.reactive_adapt import choose_adapt
        core=TypesInteraction(stamina=20)
        core.step('pause')
        observation=core.observation()
        self.assertEqual(choose('responsive',observation),('direct',None))
        self.assertEqual(choose_adapt(observation),('adapt',None))
        for state in (TypesInteraction().observation(),TypesInteraction(stamina=20).observation(),
                      TypesInteraction(tension=100).observation()):
            self.assertEqual(choose_adapt(state),choose('responsive',state))
        core.step('adapt')
        self.assertEqual(choose_adapt(core.observation()),choose('responsive',core.observation()))

    def test_reserved_cases_disjoint_and_results_replay(self):
        import json
        from cat_cafe_sim.core.human_cat_types import load_presets
        from cat_cafe_sim.evaluation.reactive_adapt import compare
        cases_path=Path('config/type_reactive_evaluation.json')
        cases=json.loads(cases_path.read_text())
        self.assertTrue(set(cases['start_stamina']).isdisjoint((100,20)))
        known=list(load_presets().values())
        self.assertTrue(all(Personality.from_dict(p) not in known for p in cases['personalities'].values()))
        with tempfile.TemporaryDirectory() as directory:
            result=compare(TypesConfig(ticks=2),cases_path,Path(directory)/'result.json')
            self.assertEqual(len(result['rows']),32)
            for row in result['rows']:
                self.assertEqual(verify(row['log']).summary()['bonus_funds'],row['bonus_funds'])
