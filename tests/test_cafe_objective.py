import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cat_cafe_sim.cafe_new_game import create_game, starting_conditions
from cat_cafe_sim.cafe_objective import progress, description
from cat_cafe_sim.core.cafe_objective import MODES
from cat_cafe_sim.core.cafe_goal import pending as goal_pending
from cat_cafe_sim.core.cafe_checkpoint import checkpoint, restore, digest
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class ObjectiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'games'

    def game(self, mode):
        return create_game(self.directory, starting_conditions(mode))

    def reload(self,s):
        save_game(s,s.checkpoint_path)
        restored,_=load_game(s.checkpoint_path)
        self.assertEqual(restored.core.snapshot(),s.core.snapshot())
        return restored

    def test_each_choice_initializes_selected_goal_and_roundtrips(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                s=self.game(mode);s=self.reload(s)
                self.assertEqual(s.core.objective,mode)
                self.assertEqual(bool(s.core.goal.get('tracking_only')),mode!='popularity')
                self.assertEqual(s.core.patron is not None,mode=='patron')
                self.assertEqual(s.core.bond_goal is not None,mode=='bond')
                self.assertEqual(s.core.funds,1000)
                self.assertFalse(goal_pending(s.core))
                self.assertTrue(description(starting_conditions(mode),mode))
                self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())

    def test_free_game_has_popularity_growth_and_no_deadline_stop(self):
        s=self.game('free')
        while not s.core.closed:s.automatic_step()
        self.assertGreater(s.core.management['popularity'],100)
        self.assertNotIn('goal_status',s.core.summary())
        s.next_day()
        while s.core.day<=12:
            if s.core.intake_request['status']=='waiting':s.resolve_intake_request('decline')
            s.day_off()
        self.assertFalse(goal_pending(s.core))
        self.assertIn('期限なし',progress(s.core))
        self.assertEqual(verify_cafe_interaction(s.core.log()).snapshot(),s.core.snapshot())
        self.reload(s)

    def test_patron_and_bond_clear_and_continue(self):
        selected=starting_conditions('patron')
        selected['patron'].pop('members', None)
        selected['patron']['target']=selected['patron']['gain']
        s=create_game(self.directory,selected)
        key=next(iter(s.core.cats));s.dispatch(key,s.core.patron['rules']['destination'])
        s.day_off();s.day_off();s.resolve_activity(f'dispatch-1-{key}')
        self.assertEqual(s.core.patron['status'],'cleared')
        s=self.reload(s);s.continue_patron();s.day_off();self.reload(s)
        selected=starting_conditions('bond');selected['bond']=dict(target=1,affinity=.5)
        s=create_game(self.directory,selected)
        s.play_with_player('cat-mugi');s.player_command('direct');s.player_command(finish=True)
        self.assertEqual(s.core.bond_goal['status'],'cleared')
        s=self.reload(s);s.continue_bond_goal();s.day_off();self.reload(s)

    def test_legacy_conditions_and_corrupt_choice(self):
        selected=starting_conditions();selected.pop('objective')
        s=create_game(self.directory,selected);s=self.reload(s)
        self.assertIsNone(s.core.objective)
        self.assertNotIn('objective',s.core.snapshot())
        s=self.game('free');data=checkpoint(s.core,set())
        for mode in ('invalid','popularity','patron','bond'):
            bad=copy.deepcopy(data);bad['state']['objective']=mode
            bad['digest']=digest({k:v for k,v in bad.items() if k!='digest'})
            with self.assertRaises(ValueError):restore(bad)

    def test_failed_creation_does_not_change_previous_game(self):
        s=self.game('popularity')
        files={p:p.read_bytes() for p in s.checkpoint_path.parent.iterdir()}
        with patch('cat_cafe_sim.cafe_new_game.save_game',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.game('free')
        self.assertEqual(files,{p:p.read_bytes() for p in files})
        self.assertEqual(len(list(self.directory.iterdir())),1)

    def test_free_mode_still_ends_when_popularity_is_lost(self):
        selected=starting_conditions('free')
        selected['management'].update(runaway_threshold=1,return_stress=0,popularity_loss=300)
        s=create_game(self.directory,selected)
        while not s.core.closed:s.automatic_step()
        self.assertEqual(s.core.management['game_over']['reason'],'popularity')
        self.assertFalse(goal_pending(s.core))
        self.reload(s)
        with self.assertRaises(ValueError):s.day_off()
