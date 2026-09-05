from dataclasses import dataclass


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
