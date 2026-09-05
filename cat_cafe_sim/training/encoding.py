from bisect import bisect_left
from dataclasses import asdict, dataclass
import math
import struct
from numbers import Integral


@dataclass(frozen=True)
class StateEncoder:
    resource_edges: tuple[float, ...]
    time_edges: tuple[int, ...]
    streak_cap: int
    opening_ticks: int
    version: str = "cat-state-v1"
    stamina_edges: tuple[float, ...] | None = None

    def __post_init__(self):
        if self.version not in ("cat-state-v1", "cat-state-v2-stamina"):
            raise ValueError("unsupported state encoding")
        if (self.version == "cat-state-v1") != (self.stamina_edges is None):
            raise ValueError("state version does not match stamina bin specification")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               or not 0 < x < 1 for x in self.resource_edges):
            raise ValueError("resource edges must lie strictly between zero and one")
        if tuple(sorted(set(self.resource_edges))) != self.resource_edges:
            raise ValueError("resource edges must be strictly increasing")
        if self.stamina_edges is not None:
            if (any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                    or not 0 < x < 1 for x in self.stamina_edges)
                    or tuple(sorted(set(self.stamina_edges))) != self.stamina_edges):
                raise ValueError("stamina edges must be strictly increasing within (0, 1)")
            rounded = tuple(self._float32(x) for x in self.stamina_edges)
            if len(set(rounded)) != len(rounded) or any(not 0 < x < 1 for x in rounded):
                raise ValueError("stamina edges must remain distinct within (0, 1) in float32")
        if any(type(x) is not int or x < 1 for x in self.time_edges):
            raise ValueError("time edges must be positive integers")
        if tuple(sorted(set(self.time_edges))) != self.time_edges:
            raise ValueError("time edges must be strictly increasing")
        if type(self.opening_ticks) is not int or self.opening_ticks < 1:
            raise ValueError("opening_ticks must be positive")
        if type(self.streak_cap) is not int or not 1 <= self.streak_cap <= self.opening_ticks:
            raise ValueError("invalid history cap")

    @classmethod
    def for_config(cls, config, resource_edges, time_edges, stamina_edges=None):
        config.validate()
        # この回数以上は飽きが下限に達し、切り替え資格も変化しない。
        saturation = (config.boredom_free_actions + math.ceil(
            (1 - config.boredom_min_multiplier) / config.boredom_decay)
            if config.boredom_decay else 1)
        cap = min(config.opening_ticks, max(1, saturation, config.switch_min_streak))
        return cls(tuple(resource_edges), tuple(time_edges), cap, config.opening_ticks,
                   version="cat-state-v1" if stamina_edges is None else "cat-state-v2-stamina",
                   stamina_edges=tuple(stamina_edges) if stamina_edges is not None else None)

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "resource_edges": tuple(data["resource_edges"]),
                      "time_edges": tuple(data["time_edges"]),
                      "stamina_edges": tuple(data["stamina_edges"]) if data.get("stamina_edges") is not None else None})

    @property
    def dimensions(self):
        # 各資源は0と最大値を独立区間にする。履歴は未交流＋2種類×回数。
        resource_count = len(self.resource_edges) + 3
        stamina_count = resource_count if self.stamina_edges is None else len(self.stamina_edges) + 3
        return (resource_count, stamina_count, resource_count, 1 + 2 * self.streak_cap, len(self.time_edges) + 2)

    def summary(self):
        count = math.prod(self.dimensions)
        return {"dimensions": list(self.dimensions), "state_upper_bound": count,
                "q_value_upper_bound": count * 7, "dense_float64_bytes": count * 7 * 8}

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def _float32(value):
        return struct.unpack('f', struct.pack('f', value))[0]

    def _resource_bin(self, value, edges=None):
        edges = self.resource_edges if edges is None else edges
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("normalized resources must be in [0, 1]")
        if value == 0:
            return 0
        if value == 1:
            return len(edges) + 2
        return 1 + bisect_left(edges, value)

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
        bins = [self._resource_bin(x) for x in resources]
        if self.stamina_edges is not None:
            # 学習環境のfloat32観測と境界を同じ精度にする。旧区間の挙動は保持する。
            bins[1] = self._resource_bin(self._float32(float(resources[1])),
                                         tuple(self._float32(x) for x in self.stamina_edges))
        return tuple(bins) + (history, time)
