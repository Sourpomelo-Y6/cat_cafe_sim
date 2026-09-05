from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from .encoding import StateEncoder
from .start_profiles import StartProfile

DEFAULT_TRAINING = Path(__file__).resolve().parents[2] / "config" / "cat_training.json"


@dataclass(frozen=True)
class TrainingSettings:
    episodes: int
    learning_rate: float
    discount: float
    epsilon_start: float
    epsilon_end: float
    epsilon_decay_fraction: float
    seed: int
    scenario_seed: int
    resource_edges: tuple[float, ...]
    time_edges: tuple[int, ...]
    max_states: int
    train_preferences: tuple[tuple[float, float], ...]
    validation_preferences: tuple[tuple[float, float], ...]
    test_preferences: tuple[tuple[float, float], ...]
    validation_seeds: tuple[int, ...]
    test_seeds: tuple[int, ...]
    train_starts: tuple[StartProfile, ...] = ()
    validation_starts: tuple[StartProfile, ...] = ()
    test_starts: tuple[StartProfile, ...] = ()

    def __post_init__(self):
        for key in ("episodes", "max_states", "seed", "scenario_seed"):
            value = getattr(self, key)
            if type(value) is not int or value < (1 if key in ("episodes", "max_states") else 0):
                raise ValueError(f"invalid {key}")
        for key in ("learning_rate", "discount", "epsilon_start", "epsilon_end", "epsilon_decay_fraction"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be in [0, 1]")
        if self.learning_rate == 0 or self.epsilon_decay_fraction == 0 or self.epsilon_end > self.epsilon_start:
            raise ValueError("invalid learning rate or epsilon schedule")
        StateEncoder(self.resource_edges, self.time_edges, 1, 1)
        preferences = []
        for split in ("train", "validation", "test"):
            conditions = getattr(self, f"{split}_preferences")
            if not conditions or any(len(pair) != 2 or any(
                    isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0
                    for x in pair) for pair in conditions):
                raise ValueError(f"invalid {split} preferences")
            if len(set(conditions)) != len(conditions):
                raise ValueError("duplicate preference conditions")
            preferences.append(set(conditions))
        if any(preferences[i] & preferences[j] for i, j in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("preference splits must be disjoint")
        for seeds in (self.validation_seeds, self.test_seeds):
            if not seeds or any(type(s) is not int or s < 0 for s in seeds) or len(set(seeds)) != len(seeds):
                raise ValueError("invalid evaluation seeds")
            if any(self.scenario_seed <= s < self.scenario_seed + self.episodes for s in seeds):
                raise ValueError("training and evaluation seed ranges overlap")
        if set(self.validation_seeds) & set(self.test_seeds):
            raise ValueError("validation and test seeds overlap")
        groups = (self.train_starts, self.validation_starts, self.test_starts)
        if any(groups) and not all(groups):
            raise ValueError("provide start profiles for all three splits")
        cases = []
        for profiles in groups:
            if len({p.name for p in profiles}) != len(profiles):
                raise ValueError("duplicate start profile names")
            if profiles and not math.isfinite(sum(p.weight for p in profiles)):
                raise ValueError("profile weight total must be finite")
            cases.append({tuple(case.values()) for p in profiles for case in p.cases()})
        if any(cases[i] & cases[j] for i, j in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("start-state splits must be disjoint")

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        for key in ("resource_edges", "time_edges", "validation_seeds", "test_seeds"):
            data[key] = tuple(data[key])
        for key in ("train_preferences", "validation_preferences", "test_preferences"):
            data[key] = tuple(tuple(pair) for pair in data[key])
        for key in ("train_starts", "validation_starts", "test_starts"):
            data[key] = tuple(StartProfile.from_dict(p) for p in data.get(key, ()))
        return cls(**data)

    def validate_starts(self, config):
        for profiles in (self.train_starts, self.validation_starts, self.test_starts):
            for profile in profiles:
                profile.validate_config(config)

    @classmethod
    def load(cls, path=DEFAULT_TRAINING):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self):
        return asdict(self)

    def epsilon(self, episode):
        if type(episode) is not int or not 0 <= episode < self.episodes:
            raise ValueError("episode index out of range")
        decay = max(1, int((self.episodes - 1) * self.epsilon_decay_fraction))
        fraction = min(1.0, episode / decay)
        return self.epsilon_start + fraction * (self.epsilon_end - self.epsilon_start)
