"""ゲーム内料金・満足ルールから独立した、猫学習用の報酬係数。"""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

DEFAULT_REWARDS = Path(__file__).resolve().parents[2] / "config" / "cat_rewards.json"


@dataclass(frozen=True)
class CatRewards:
    satisfaction: float
    success: float
    perfect: float
    stamina: float
    spirit: float
    discontent: float
    failure: float
    time: float

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")

    @classmethod
    def load(cls, path=DEFAULT_REWARDS):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def breakdown(self, events):
        result = dict.fromkeys(asdict(self), 0.0)
        for event in events:
            if event["kind"] == "action":
                result["satisfaction"] += self.satisfaction * event["satisfaction_delta"]
                result["stamina"] -= self.stamina * event["stamina_spent"]
                result["time"] -= self.time
            elif event["kind"] == "refill":
                result["spirit"] -= self.spirit * event["spirit_spent"]
            elif event["kind"] == "departure":
                result["success"] += self.success * (event["reason"] == "success")
                result["perfect"] += self.perfect * event["perfect"]
                result["discontent"] -= self.discontent * event["discontent"]
                result["failure"] -= self.failure * (event["reason"] == "failure")
        return result
