from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.json"


@dataclass(frozen=True)
class Action:
    name: str
    kind: str
    satisfaction: float
    stamina_cost: float


@dataclass(frozen=True)
class Config:
    opening_ticks: int
    max_stamina: float
    max_spirit: float
    refill_cost: float
    allow_zero_spirit_after_refill: bool
    rest_recovery: float
    satisfaction_target: float
    time_price: float
    success_bonus: float
    perfect_multiplier: float
    initial_funds: float
    queue_capacity: int
    max_wait_ticks: int
    failure_discontent: float
    waiting_discontent: float
    arrival_ticks: tuple[int, ...]
    preferences: tuple[float, float]
    actions: tuple[Action, ...]
    boredom_free_actions: int = 1
    boredom_decay: float = 0.15
    boredom_min_multiplier: float = 0.4
    switch_min_streak: int = 2
    switch_bonus: float = 4

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["actions"] = tuple(Action(**a) for a in data["actions"])
        data["arrival_ticks"] = tuple(data["arrival_ticks"])
        data["preferences"] = tuple(data["preferences"])
        result = cls(**data)
        result.validate()
        return result

    @classmethod
    def load(cls, path=DEFAULT_CONFIG):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self):
        return asdict(self)

    def validate(self):
        for name in ("opening_ticks", "queue_capacity", "max_wait_ticks"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name != "queue_capacity" else 0):
                raise ValueError(f"{name} must be a valid integer")
        for name in ("boredom_free_actions", "switch_min_streak"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("max_stamina", "max_spirit", "refill_cost", "rest_recovery",
                     "satisfaction_target", "time_price", "success_bonus", "perfect_multiplier",
                     "initial_funds", "failure_discontent", "waiting_discontent",
                     "boredom_decay", "boredom_min_multiplier", "switch_bonus"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.boredom_decay > 1 or self.boredom_min_multiplier > 1:
            raise ValueError("boredom coefficients must be at most one")
        if min(self.max_stamina, self.max_spirit, self.refill_cost, self.satisfaction_target) <= 0:
            raise ValueError("resource maxima, target and refill cost must be positive")
        if type(self.allow_zero_spirit_after_refill) is not bool:
            raise ValueError("refill rule must be boolean")
        if any(type(t) is not int or not 0 <= t < self.opening_ticks for t in self.arrival_ticks):
            raise ValueError("arrivals must fall within opening hours")
        if tuple(sorted(self.arrival_ticks)) != self.arrival_ticks:
            raise ValueError("arrival_ticks must be sorted")
        if len(self.preferences) != 2 or any(not math.isfinite(p) or p < 0 for p in self.preferences):
            raise ValueError("two nonnegative preferences required")
        if len(self.actions) != 7 or [a.kind for a in self.actions] != ["play"] * 3 + ["pet"] * 3 + ["rest"]:
            raise ValueError("expected six interactions and rest")
        for a in self.actions:
            if not math.isfinite(a.satisfaction) or not math.isfinite(a.stamina_cost) or a.stamina_cost < 0:
                raise ValueError("invalid action values")
        if self.actions[6].satisfaction != 0 or self.actions[6].stamina_cost != 0:
            raise ValueError("rest must only recover stamina")
