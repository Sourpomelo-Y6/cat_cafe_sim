"""通常営業の病気・療養ルールと、猫ごとに独立した発症抽選。"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random


@dataclass(frozen=True)
class HealthRules:
    safe_fatigue: float = 60
    probability_per_fatigue: float = 0.02
    max_probability: float = 0.5
    recovery_days: int = 2

    def __post_init__(self):
        for value in (self.safe_fatigue, self.probability_per_fatigue, self.max_probability):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('病気の係数は有限の非負数で指定してください。')
        if self.max_probability > 1:
            raise ValueError('発症確率の上限は1以下で指定してください。')
        if type(self.recovery_days) is not int or self.recovery_days < 1:
            raise ValueError('療養日数は1以上の整数で指定してください。')

    def probability(self, fatigue):
        return min(self.max_probability, max(0, fatigue-self.safe_fatigue)*self.probability_per_fatigue)

    @classmethod
    def load(cls):
        path = Path(__file__).resolve().parents[2] / 'config' / 'cafe_health.json'
        return cls(**json.loads(path.read_text(encoding='utf-8')))


def health_draw(seed, day, cat_id):
    key = json.dumps(['cafe-health-v1', seed, day, cat_id], ensure_ascii=True)
    return random.Random(key).random()
