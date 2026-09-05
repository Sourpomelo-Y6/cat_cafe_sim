from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from cat_cafe_sim.core import Command, SimulationCore
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.policies import FixedManagerPolicy, RandomCatPolicy
from cat_cafe_sim.replay import save, verify


def config(**kwargs):
    return replace(Config.load(), **kwargs)


def assigned(core, action=1):
    return core.step(Command("assign", "guest-1"), cat_action=action)


class SimulationTests(unittest.TestCase):
    def test_success_exhaustion_and_closing_priority(self):
        core = SimulationCore(config(opening_ticks=1, arrival_ticks=(0,), max_stamina=15,
                                     satisfaction_target=20))
        assigned(core)
        visit = core.visits["guest-1"]
        self.assertEqual(visit.departure_reason, "success")
        self.assertTrue(visit.perfect)
        self.assertEqual(visit.bill, 210)
        self.assertEqual(core.cat.stamina, 0)
        self.assertEqual(core.cat.spirit, 100)
        self.assertEqual(len([e for e in core.events if e["kind"] == "departure"]), 1)
        funds = core.funds
        with self.assertRaises(RuntimeError):
            core.step()
        self.assertEqual(core.funds, funds)

    def test_refill_boundaries(self):
        for spirit, allow, stamina, remaining, failure in [
            (29, False, 0, 29, True), (30, False, 15, 0, True),
            (30, True, 15, 0, False), (31, False, 15, 1, False)
        ]:
            with self.subTest(spirit=spirit, allow=allow):
                core = SimulationCore(config(max_stamina=15, max_spirit=spirit,
                                             allow_zero_spirit_after_refill=allow))
                assigned(core)
                self.assertEqual(core.cat.stamina, stamina)
                self.assertEqual(core.cat.spirit, remaining)
                self.assertEqual(core.cat.cannot_continue, failure)
                self.assertEqual(core.visits["guest-1"].departure_reason, "failure" if failure else None)

    def test_next_customer_refills_before_action(self):
        core = SimulationCore(config(arrival_ticks=(0, 1), max_stamina=15, satisfaction_target=20))
        assigned(core)
        self.assertEqual(core.spirit_spent, 0)
        core.step(Command("assign", "guest-2"), cat_action=1)
        self.assertEqual(core.spirit_spent, 30)
        self.assertEqual(core.summary()["successes"], 2)

    def test_next_customer_not_seated_if_refill_fails(self):
        core = SimulationCore(config(arrival_ticks=(0, 1), max_stamina=15, max_spirit=30,
                                     satisfaction_target=20))
        assigned(core)
        core.step(Command("assign", "guest-2"), cat_action=1)
        self.assertIsNone(core.visits["guest-2"].seated_at)
        self.assertTrue(core.cat.cannot_continue)
        self.assertIn("guest-2", core.queue)

    def test_rest_only_restores_stamina(self):
        core = SimulationCore()
        assigned(core)
        core.cat.fatigue = 25
        core.step(cat_action=6)
        self.assertEqual((core.cat.stamina, core.cat.spirit, core.cat.fatigue), (93, 100, 25))
        self.assertEqual(core.visits["guest-1"].satisfaction, 20)

    def test_waiting_not_billed_and_closing_not_discontent(self):
        core = SimulationCore(config(opening_ticks=3, arrival_ticks=(0, 1)))
        core.step()
        assigned(core, 6)
        core.step(cat_action=6)
        self.assertEqual(core.visits["guest-1"].bill, 20)
        self.assertEqual(core.visits["guest-2"].bill, 0)
        self.assertTrue(all(v.discontent == 0 for v in core.visits.values()))
        self.assertEqual(core.funds, 20)

    def test_queue_capacity_and_wait_deadline(self):
        core = SimulationCore(config(arrival_ticks=(0, 0), queue_capacity=1, max_wait_ticks=2))
        core.step()
        self.assertEqual(core.visits["guest-2"].departure_reason, "queue_full")
        core.step()
        self.assertEqual(core.visits["guest-1"].departure_reason, "wait_timeout")
        self.assertEqual(core.funds, 0)
        self.assertEqual(core.queue, [])

    def test_invalid_commands_and_double_assignment(self):
        core = SimulationCore(config(arrival_ticks=(0, 0)))
        assigned(core)
        core.step(Command("assign", "guest-2"), cat_action=6)
        self.assertEqual(core.seat.customer_id, "guest-1")
        self.assertEqual(core.queue, ["guest-2"])
        self.assertEqual(core.tick, 2)
        self.assertTrue(any(e.get("reason") == "seat_occupied" for e in core.events))
        core.step(Command("bad"), cat_action=6)
        self.assertEqual(core.tick, 3)

    def test_unknown_ids_and_sick_cat_rejected(self):
        core = SimulationCore()
        core.step(Command("assign", "guest-1", cat_id="unknown"))
        self.assertIsNone(core.seat.customer_id)
        core.cat.health_status = "sick"
        core.step(Command("assign", "guest-1"))
        self.assertIsNone(core.seat.customer_id)

    def test_negative_satisfaction_clamped_and_logged_signed(self):
        base = config()
        actions = list(base.actions)
        actions[0] = replace(actions[0], satisfaction=-50)
        core = SimulationCore(replace(base, actions=tuple(actions)))
        assigned(core)
        core.step(cat_action=0)
        self.assertEqual(core.visits["guest-1"].satisfaction, 0)
        self.assertEqual([e for e in core.events if e["kind"] == "action"][-1]["satisfaction_delta"], -20)

    def test_seed_replay_and_accounting_invariants(self):
        for seed in range(10):
            cores = [SimulationCore(seed=seed, cat_policy=RandomCatPolicy(seed)) for _ in range(2)]
            for core in cores:
                while not core.closed:
                    core.step(manager_policy=FixedManagerPolicy())
                    self.assertGreaterEqual(core.cat.stamina, 0)
                    self.assertLessEqual(core.cat.stamina, core.config.max_stamina)
                    self.assertGreaterEqual(core.cat.spirit, 0)
                    self.assertEqual(core.funds, core.config.initial_funds + sum(v.bill for v in core.visits.values()))
            self.assertEqual(cores[0].records, cores[1].records)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "replay.json"
                save(cores[0], path)
                self.assertEqual(verify(path).snapshot(), cores[0].snapshot())
                payload = json.loads(path.read_text())
                payload["records"][0]["state"]["funds"] += 1
                path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    verify(path)

    def test_observation_excludes_private_information(self):
        core = SimulationCore()
        core.step()
        observation = json.dumps(core.observation())
        for private in ("preferences", "arrival_ticks", "rng", "schedule"):
            self.assertNotIn(private, observation)

    def test_invalid_cat_action_is_rest_and_replays(self):
        core = SimulationCore(config(opening_ticks=1, arrival_ticks=(0,)))
        assigned(core, -1)
        self.assertEqual(core.visits["guest-1"].satisfaction, 0)
        self.assertTrue(any(e["kind"] == "invalid_cat_action" for e in core.events))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            save(core, path)
            self.assertEqual(verify(path).records, core.records)

    def test_invalid_config(self):
        for kwargs in ({"refill_cost": 0}, {"max_stamina": -1}, {"opening_ticks": 0},
                       {"arrival_ticks": (100,)}, {"arrival_ticks": (2, 1)},
                       {"time_price": float("nan")}, {"queue_capacity": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SimulationCore(config(**kwargs))


if __name__ == "__main__":
    unittest.main()
