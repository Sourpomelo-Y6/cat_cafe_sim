from bisect import bisect_left
from dataclasses import asdict, dataclass
import math
from numbers import Integral


@dataclass(frozen=True)
class StateEncoder:
    resource_edges: tuple[float, ...]
    time_edges: tuple[int, ...]
    streak_cap: int
    opening_ticks: int
    version: str = "cat-state-v1"

    def __post_init__(self):
        if self.version != "cat-state-v1":
            raise ValueError("unsupported state encoding")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               or not 0 < x < 1 for x in self.resource_edges):
            raise ValueError("resource edges must lie strictly between zero and one")
        if tuple(sorted(set(self.resource_edges))) != self.resource_edges:
            raise ValueError("resource edges must be strictly increasing")
        if any(type(x) is not int or x < 1 for x in self.time_edges):
            raise ValueError("time edges must be positive integers")
        if tuple(sorted(set(self.time_edges))) != self.time_edges:
            raise ValueError("time edges must be strictly increasing")
        if type(self.opening_ticks) is not int or self.opening_ticks < 1:
            raise ValueError("opening_ticks must be positive")
        if type(self.streak_cap) is not int or not 1 <= self.streak_cap <= self.opening_ticks:
            raise ValueError("invalid history cap")

    @classmethod
    def for_config(cls, config, resource_edges, time_edges):
        config.validate()
        # この回数以上は飽きが下限に達し、切り替え資格も変化しない。
        saturation = (config.boredom_free_actions + math.ceil(
            (1 - config.boredom_min_multiplier) / config.boredom_decay)
            if config.boredom_decay else 1)
        cap = min(config.opening_ticks, max(1, saturation, config.switch_min_streak))
        return cls(tuple(resource_edges), tuple(time_edges), cap, config.opening_ticks)

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "resource_edges": tuple(data["resource_edges"]),
                      "time_edges": tuple(data["time_edges"])})

    @property
    def dimensions(self):
        # 各資源は0と最大値を独立区間にする。履歴は未交流＋2種類×回数。
        resource_count = len(self.resource_edges) + 3
        return (resource_count,) * 3 + (1 + 2 * self.streak_cap, len(self.time_edges) + 2)

    def summary(self):
        count = math.prod(self.dimensions)
        return {"dimensions": list(self.dimensions), "state_upper_bound": count,
                "q_value_upper_bound": count * 7, "dense_float64_bytes": count * 7 * 8}

    def to_dict(self):
        return asdict(self)

    def _resource_bin(self, value):
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("normalized resources must be in [0, 1]")
        if value == 0:
            return 0
        if value == 1:
            return len(self.resource_edges) + 2
        return 1 + bisect_left(self.resource_edges, value)

    def encode(self, observation):
        resources = observation["resources"]
        if len(resources) != 3:
            raise ValueError("three resources required")
        kind, streak, remaining = (observation[k] for k in
                                  ("last_interaction_kind", "interaction_streak", "remaining_ticks"))
        if any(isinstance(x, bool) or not isinstance(x, Integral) for x in (kind, streak, remaining)):
            raise ValueError("history and clock must be integers")
        if kind not in (0, 1, 2) or not 0 <= streak <= self.opening_ticks or not 0 <= remaining <= self.opening_ticks:
            raise ValueError("history or clock out of bounds")
        if (kind == 2) != (streak == 0):
            raise ValueError("inconsistent interaction history")
        history = 0 if kind == 2 else 1 + int(kind) * self.streak_cap + min(int(streak), self.streak_cap) - 1
        time = 0 if remaining == 0 else 1 + bisect_left(self.time_edges, int(remaining))
        return tuple(self._resource_bin(x) for x in resources) + (history, time)
