"""開始条件の離散候補と混合比。好み・方策探索とは別の乱数で選ぶ。"""
from dataclasses import dataclass
from itertools import product
import math

from cat_cafe_sim.core import StartState


@dataclass(frozen=True)
class StartProfile:
    name: str
    weight: float
    stamina: tuple[float, ...]
    spirit: tuple[float, ...]
    remaining_ticks: tuple[int, ...]

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("start profile name is required")
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)) or not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("profile weight must be finite and positive")
        for name in ("stamina", "spirit", "remaining_ticks"):
            values = getattr(self, name)
            if not values or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                 or not math.isfinite(v) or v < 0 for v in values):
                raise ValueError(f"invalid profile {name}")
            if len(set(values)) != len(values):
                raise ValueError("duplicate start values")
        if any(v == 0 for v in self.stamina):
            raise ValueError("initial stamina must be positive")
        if any(type(v) is not int or v < 1 for v in self.remaining_ticks):
            raise ValueError("remaining ticks must be positive integers")

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, **{k: tuple(data[k]) for k in ("stamina", "spirit", "remaining_ticks")}})

    def cases(self):
        for stamina, spirit, remaining in product(self.stamina, self.spirit, self.remaining_ticks):
            yield {"stamina": stamina, "spirit": spirit, "remaining_ticks": remaining}

    def validate_config(self, config):
        for case in self.cases():
            StartState(case["stamina"], case["spirit"], config.opening_ticks - case["remaining_ticks"]).validate(config)

    def sample(self, rng):
        return {key: rng.choice(getattr(self, key)) for key in ("stamina", "spirit", "remaining_ticks")}


def choose_start(profiles, rng):
    if not profiles:
        return "default", {}
    profile = rng.choices(profiles, weights=[p.weight for p in profiles], k=1)[0]
    return profile.name, profile.sample(rng)
