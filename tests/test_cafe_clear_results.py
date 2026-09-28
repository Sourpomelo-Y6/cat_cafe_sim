import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.core.cafe_clear_results import capture
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ClearResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'games'

    def create(self,mode):
        conditions=starting_conditions(mode);conditions.pop('intake_request')
        if mode=='popularity':
            conditions['goal'].update(target=105,stages=[dict(target=110,days=10),dict(target=115,days=10)])
        elif mode=='patron':conditions['patron']['target']=conditions['patron']['gain']
        elif mode=='bond':conditions['bond']=dict(target=1,affinity=.5)
        return create_game(self.directory,conditions)

    def reload(self,s):
        save_game(s,s.checkpoint_path)
        loaded,_=load_game(s.checkpoint_path)
        self.assertEqual(loaded.core.snapshot(),s.core.snapshot())
        return loaded

    def achieve_bond(self,s):
        s.play_with_player('cat-mugi');s.player_command('direct');s.player_command(finish=True)

    def test_popularity_only_final_stage_and_frozen_after_continuation(self):
        s=self.create('popularity')
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.clear_results,{})
        s.advance_goal();s.next_day();s.day_off()
        self.assertEqual(s.core.clear_results,{})
        from cat_cafe_sim.core.cafe_reservation import waiting
        if waiting(s.core):s.resolve_reservation('decline')
        s.advance_goal();s.day_off()
        row=copy.deepcopy(s.core.clear_results['popularity'])
        self.assertEqual(row['day'],3)
        self.assertEqual(row['target'],115)
        self.assertGreaterEqual(row['value'],115)
        self.assertEqual(row['revenue'],sum(d['summary']['revenue'] for d in s.core.day_results))
        self.assertEqual(row['funds'],s.core.funds)
        self.assertEqual(row['cats'],5)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        s=self.reload(s);s.continue_goal();s.open_recruitment()
        s.recruit_cat(next(iter(s.core.recruitment['candidates'])))
        self.assertEqual(s.core.clear_results['popularity'],row)
        s.day_off();self.reload(s)

    def test_patron_reward_included_and_multiple_goal_records(self):
        s=self.create('patron');key=next(iter(s.core.cats))
        s.dispatch(key,s.core.patron['rules']['destination']);s.day_off();s.day_off()
        s.resolve_activity(f'dispatch-1-{key}')
        row=copy.deepcopy(s.core.clear_results['patron'])
        self.assertEqual(row['funds'],s.core.funds)
        self.assertGreater(row['funds'],1000)
        self.assertEqual(row['value'],25)
        self.assertEqual(row['revenue'],0)
        s.continue_patron();s.enable_bond_goal(dict(target=1,affinity=.5))
        self.achieve_bond(s)
        self.assertEqual(set(s.core.clear_results),{'patron','bond'})
        self.assertEqual(s.core.clear_results['patron'],row)
        self.reload(s)

    def test_bond_capture_repeat_and_save_failure(self):
        s=self.create('bond');self.achieve_bond(s)
        row=copy.deepcopy(s.core.clear_results['bond'])
        self.assertEqual(row['value'],1)
        self.assertEqual(row['cats'],5)
        before=s.core.log();capture(s.core,'bond');self.assertEqual(s.core.log(),before)
        with patch('cat_cafe_sim.storage.cafe_saves.RelationshipStore._write',side_effect=OSError('full')):
            with self.assertRaises(OSError):save_game(s,s.checkpoint_path)
        s=self.reload(s);s.continue_bond_goal();s.day_off()
        self.assertEqual(s.core.clear_results['bond'],row)
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_no_clear_on_failure_or_game_over_and_corrupt_records(self):
        s=self.create('popularity')
        for _ in range(10):s.day_off()
        self.assertEqual(s.core.goal['status'],'expired')
        self.assertEqual(s.core.clear_results,{})
        self.reload(s)
        s=self.create('bond');self.achieve_bond(s)
        data=checkpoint(s.core,set())
        for mutate in (lambda d:d.clear(),lambda d:d['bond'].update(day=99),
                       lambda d:d['bond'].update(value=0),lambda d:d['bond'].update(funds=-1),
                       lambda d:d['bond'].update(cats=100)):
            bad=copy.deepcopy(data);mutate(bad['state']['clear_results'])
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)

    def test_legacy_replay_does_not_backfill_past_results(self):
        from cat_cafe_sim.cafe_interaction import CafeInteractionSession
        from cat_cafe_sim.storage.relationships import RelationshipStore
        s=CafeInteractionSession(store=RelationshipStore(Path(self.temp.name)/'old.json'))
        s.enable_management();s.enable_bond_goal(dict(target=1,affinity=.5))
        key=next(iter(s.core.cats));s.play_with_player(key);s.player_command('direct');s.player_command(finish=True)
        self.assertEqual(s.core.bond_goal['status'],'cleared')
        self.assertIsNone(s.core.clear_results)
        self.assertNotIn('clear_results',s.core.snapshot())
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
