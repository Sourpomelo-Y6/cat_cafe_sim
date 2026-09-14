import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.cafe_interaction import verify_cafe_interaction
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game, load_game


class CafeDayTests(unittest.TestCase):
    def session(self, seats):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path=Path(directory.name)/'day.json'
        return CafeInteractionSession(store=RelationshipStore(Path(directory.name)/'relations.json'),
            seat_count=seats,cafe_config=replace(Config.load(),opening_ticks=4,arrival_ticks=(0,)),
            interaction_config=replace(RelationshipConfig(),ticks=2))

    def close_day(self, session):
        while not session.core.closed:
            session.automatic_step()

    def test_two_days_replay_save_money_recovery_and_returning_guest(self):
        for seats in (1,2):
            with self.subTest(seats=seats):
                session=self.session(seats)
                self.close_day(session)
                first=session.core.day_result()
                money=session.core.funds
                relation=session.store.snapshot('cat-1','guest-1')
                save_game(session,self.path)
                session.next_day()
                self.assertEqual(session.core.day,2)
                self.assertEqual(session.core.funds,money)
                self.assertEqual(session.core.day_results,[first])
                self.assertEqual(session.core.summary()['revenue'],0)
                self.assertEqual(session.core.cat.stamina,session.core.config.max_stamina)
                self.assertFalse(session.core.cat.cannot_continue)
                with self.assertRaises(ValueError):session.next_day()
                session.automatic_step()
                self.assertFalse(session.core.visits['guest-1'].first_visit)
                session.automatic_step()
                active=next(iter(session.active_interactions.values()))
                self.assertEqual(active.initial_relationship['revision'],relation['revision'])
                save_game(session,self.path)
                loaded,_=load_game(self.path)
                self.assertEqual(loaded.core.snapshot(),session.core.snapshot())
                self.close_day(loaded)
                self.assertGreater(loaded.core.funds,money)
                self.assertEqual(loaded.core.day_result()['summary']['completed_interactions'],1)
                self.assertEqual(verify_cafe_interaction(loaded.core.log()).snapshot(),loaded.core.snapshot())

    def test_pending_results_block_next_day(self):
        session=self.session(2)
        with patch.object(session.store,'apply',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.close_day(session)
        with self.assertRaises(ValueError):session.next_day()
        session.persist()
        self.close_day(session)
        session.next_day()
        self.assertEqual(session.core.day,2)

    def test_comparison_history_survives_resume_and_does_not_mutate_state(self):
        from cat_cafe_sim.cafe_history import comparison_rows
        session=self.session(2)
        self.assertEqual(comparison_rows(session.core),[])
        self.close_day(session)
        first=comparison_rows(session.core)
        self.assertEqual(first[0]['cats']['cat-1']['interactions'],1)
        self.assertEqual(first[0]['cats']['cat-1']['affinity_delta'],
                         sum(row['change'] for row in first[0]['affinity_changes']))
        session.next_day()
        self.assertEqual(comparison_rows(session.core),first)
        self.close_day(session)
        before=session.core.log()
        rows=comparison_rows(session.core)
        self.assertEqual([row['day'] for row in rows],[1,2])
        self.assertEqual([row['cats']['cat-1']['interactions'] for row in rows],[1,1])
        self.assertEqual(sum(row['summary']['revenue'] for row in rows),session.core.funds)
        self.assertEqual(session.core.log(),before)
        save_game(session,self.path)
        loaded,_=load_game(self.path)
        self.assertEqual(comparison_rows(loaded.core),rows)
        rows[0]['cats']['cat-1']['stamina']=-1
        self.assertEqual(session.core.log(),before)
