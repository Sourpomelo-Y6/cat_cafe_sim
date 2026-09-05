from dataclasses import asdict, dataclass
import random

from .config import Config
from .models import Cat, Seat, Visit
from .interaction import apply_interaction_history
from cat_cafe_sim.policies import FixedCatPolicy


@dataclass(frozen=True)
class Command:
    kind: str = "wait"
    customer_id: str | None = None
    cat_id: str = "cat-1"
    seat_id: str = "seat-1"


class SimulationCore:
    """1日、1匹、1席。stepは来客→操作→接客→期限/閉店の順に1tick進む。"""

    def __init__(self, config=None, seed=0, cat_policy=None):
        self.config = config or Config.load()
        self.config.validate()
        self.seed = seed
        self.cat_policy = cat_policy or FixedCatPolicy()
        self.arrival_rng = random.Random(f"{seed}:arrival")
        self.health_rng = random.Random(f"{seed}:health")
        # Phase 1の来店は固定。将来の乱数来店も営業前に生成する。
        self._schedule = tuple(self.config.arrival_ticks)
        self.cat = Cat(stamina=self.config.max_stamina, spirit=self.config.max_spirit)
        self.seat = Seat()
        self.visits = {}
        self.queue = []
        self.tick = 0
        self.day = 1
        self.closed = False
        self.funds = self.config.initial_funds
        self.events = []
        self.records = []
        self.spirit_spent = 0
        self.service_ticks = 0
        self._tick_events = []

    def _emit(self, kind, **data):
        event = {"tick": self.tick, "kind": kind, **data}
        self.events.append(event)
        self._tick_events.append(event)

    def observation(self):
        # 予定時刻、好み、乱数状態を公開しない。
        return {"day": self.day, "tick": self.tick, "remaining_ticks": self.config.opening_ticks - self.tick,
                "funds": self.funds, "closed": self.closed, "cat": asdict(self.cat),
                "seat": asdict(self.seat), "queue": list(self.queue),
                "customers": [asdict(v) for v in self.visits.values() if v.departure_reason is None]}

    def snapshot(self):
        return {**self.observation(), "visits": [asdict(v) for v in self.visits.values()],
                "spirit_spent": self.spirit_spent, "service_ticks": self.service_ticks}

    def _arrive(self):
        for i, arrival in enumerate(self._schedule):
            if arrival != self.tick:
                continue
            visit = Visit(f"guest-{i + 1}", arrival)
            self.visits[visit.id] = visit
            self._emit("arrival", customer_id=visit.id)
            if len(self.queue) >= self.config.queue_capacity:
                self._depart(visit, "queue_full")
            else:
                self.queue.append(visit.id)

    def _refill(self):
        c = self.cat
        if c.cannot_continue:
            return False
        if c.stamina > 0:
            return True
        if c.spirit < self.config.refill_cost:
            c.cannot_continue = True
        else:
            c.spirit -= self.config.refill_cost
            self.spirit_spent += self.config.refill_cost
            c.stamina = self.config.max_stamina
            c.cannot_continue = c.spirit == 0 and not self.config.allow_zero_spirit_after_refill
            self._emit("refill", spirit_spent=self.config.refill_cost, stamina=c.stamina, spirit=c.spirit)
        if c.cannot_continue:
            self._emit("cannot_continue", spirit=c.spirit)
        return not c.cannot_continue

    def _apply(self, command):
        if command.kind == "wait":
            return
        reason = None
        if command.kind != "assign":
            reason = "unknown_command"
        elif command.cat_id != self.cat.id or command.seat_id != self.seat.id:
            reason = "unknown_cat_or_seat"
        elif self.seat.customer_id is not None:
            reason = "seat_occupied"
        elif command.customer_id not in self.queue:
            reason = "customer_not_waiting"
        elif self.cat.health_status != "healthy" or self.cat.cannot_continue:
            reason = "cat_unavailable"
        if reason:
            self._emit("invalid_command", reason=reason, command=asdict(command))
            return
        # 前の成功で体力0のままなら、次の着席前に回復判定する。
        if not self._refill():
            self._emit("invalid_command", reason="cat_cannot_refill", command=asdict(command))
            return
        self.queue.remove(command.customer_id)
        self.seat.customer_id = command.customer_id
        self.seat.cat_id = self.cat.id
        self.visits[command.customer_id].seated_at = self.tick
        self._emit("assigned", customer_id=command.customer_id, cat_id=self.cat.id, seat_id=self.seat.id)

    def _depart(self, visit, reason, perfect=False):
        if visit.departure_reason is not None:
            return
        visit.departure_reason = reason
        visit.perfect = perfect
        if reason == "failure":
            visit.discontent += self.config.failure_discontent
        elif reason in ("queue_full", "wait_timeout"):
            visit.discontent += self.config.waiting_discontent
        base = visit.seated_ticks * self.config.time_price
        bonus = self.config.success_bonus * (self.config.perfect_multiplier if perfect else 1) if reason == "success" else 0
        visit.bill = base + bonus
        self.funds += visit.bill
        if visit.id in self.queue:
            self.queue.remove(visit.id)
        if self.seat.customer_id == visit.id:
            self.seat.customer_id = self.seat.cat_id = None
        self._emit("departure", customer_id=visit.id, reason=reason, satisfaction=visit.satisfaction,
                   discontent=visit.discontent, perfect=perfect, base_charge=base, bonus=bonus, bill=visit.bill)

    def _interact(self, action_override):
        if self.seat.customer_id is None:
            return None
        v = self.visits[self.seat.customer_id]
        obs = {"satisfaction": v.satisfaction, "stamina": self.cat.stamina, "spirit": self.cat.spirit,
               "previous_action": v.previous_action, "first_action": v.actions_taken == 0,
               "first_visit": v.first_visit, "first_meeting": v.first_meeting,
               "last_interaction_kind": v.last_interaction_kind, "interaction_streak": v.interaction_streak,
               "remaining_ticks": self.config.opening_ticks - self.tick}
        action_id = self.cat_policy.choose(obs) if action_override is None else action_override
        requested_action = action_id
        if type(action_id) is not int or not 0 <= action_id < 7:
            self._emit("invalid_cat_action", action=action_id)
            action_id = 6
        action = self.config.actions[action_id]
        before = v.satisfaction
        stamina_before = self.cat.stamina
        effect = apply_interaction_history(v, action, self.config)
        if action.kind == "rest":
            self.cat.stamina = min(self.config.max_stamina, self.cat.stamina + self.config.rest_recovery)
        else:
            v.satisfaction = min(self.config.satisfaction_target, max(0, v.satisfaction + effect.satisfaction))
            self.cat.stamina = max(0, self.cat.stamina - action.stamina_cost)
        v.seated_ticks += 1
        v.actions_taken += 1
        v.previous_action = action_id
        self.service_ticks += 1
        self._emit("action", customer_id=v.id, action=action_id, name=action.name,
                   satisfaction_delta=v.satisfaction - before, stamina_before=stamina_before,
                   stamina_spent=max(0, stamina_before - self.cat.stamina),
                   boredom_multiplier=effect.boredom_multiplier, switch_bonus=effect.switch_bonus,
                   last_interaction_kind=v.last_interaction_kind, interaction_streak=v.interaction_streak,
                   stamina=self.cat.stamina, spirit=self.cat.spirit)
        if v.satisfaction >= self.config.satisfaction_target:
            self._depart(v, "success", perfect=self.cat.stamina == 0)
        elif self.cat.stamina == 0 and not self._refill():
            self._depart(v, "failure")
        return requested_action

    def step(self, command=None, *, manager_policy=None, cat_action=None):
        if self.closed:
            raise RuntimeError("営業は終了しています")
        if command is not None and manager_policy is not None:
            raise ValueError("specify command or manager_policy, not both")
        self._tick_events = []
        self._arrive()
        command = manager_policy.choose(self.observation()) if manager_policy else (command or Command())
        self._apply(command)
        action = self._interact(cat_action)
        for customer_id in list(self.queue):
            v = self.visits[customer_id]
            if self.tick - v.arrival_tick + 1 >= self.config.max_wait_ticks:
                self._depart(v, "wait_timeout")
        if self.tick + 1 >= self.config.opening_ticks:
            for v in self.visits.values():
                if v.departure_reason is None:
                    self._depart(v, "closing")
            self.closed = True
            self._emit("closed", revenue=self.funds - self.config.initial_funds)
        self.tick += 1
        record = {"command": asdict(command), "cat_action": action,
                  "events": list(self._tick_events), "state": self.snapshot()}
        self.records.append(record)
        return self.observation(), list(self._tick_events)

    def summary(self):
        visits = list(self.visits.values())
        successes = sum(v.departure_reason == "success" for v in visits)
        return {"seed": self.seed, "ticks": self.tick, "arrivals": len(visits),
                "successes": successes, "success_rate": successes / len(visits) if visits else 0,
                "perfect_successes": sum(v.perfect for v in visits),
                "failures": sum(v.departure_reason == "failure" for v in visits),
                "unserved": sum(v.seated_at is None for v in visits),
                "revenue": sum(v.bill for v in visits), "funds": self.funds,
                "spirit_spent": self.spirit_spent, "service_ticks": self.service_ticks,
                "action_counts": {str(i): sum(e["kind"] == "action" and e["action"] == i for e in self.events) for i in range(7)}}
