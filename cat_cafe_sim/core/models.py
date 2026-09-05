from dataclasses import dataclass
import math
from numbers import Integral, Real


@dataclass(frozen=True)
class StartState:
    """履歴なしで接客を開始できる猫の資源と営業時計。"""

    stamina: float
    spirit: float
    tick: int = 0

    def validate(self, config):
        for name, maximum in (("stamina", config.max_stamina), ("spirit", config.max_spirit)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"initial {name} must be finite and in [0, {maximum}]")
        if self.stamina == 0:
            raise ValueError("initial stamina must be positive; start after the pre-service refill")
        if self.spirit == 0 and not config.allow_zero_spirit_after_refill:
            raise ValueError("initial spirit zero requires allow_zero_spirit_after_refill")
        if isinstance(self.tick, bool) or not isinstance(self.tick, Integral) or not 0 <= self.tick < config.opening_ticks:
            raise ValueError("initial tick must be an integer within opening hours")


@dataclass
class Cat:
    id: str = "cat-1"
    stamina: float = 100
    spirit: float = 100
    cannot_continue: bool = False
    fatigue: float = 0
    health_status: str = "healthy"
    recovery_days_remaining: int = 0


@dataclass
class Visit:
    id: str
    arrival_tick: int
    satisfaction: float = 0
    discontent: float = 0
    seated_ticks: int = 0
    seated_at: int | None = None
    actions_taken: int = 0
    previous_action: int | None = None
    last_interaction_kind: str | None = None
    interaction_streak: int = 0
    first_visit: bool = True
    first_meeting: bool = True
    departure_reason: str | None = None
    bill: float = 0
    perfect: bool = False


@dataclass
class Seat:
    id: str = "seat-1"
    customer_id: str | None = None
    cat_id: str | None = None
    equipment: str | None = None
