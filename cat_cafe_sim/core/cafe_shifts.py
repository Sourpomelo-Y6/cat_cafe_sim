"""通常営業の出勤・休養に使う暫定の疲労係数。"""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class ShiftRules:
    max_fatigue: float = 100
    fatigue_per_service_tick: float = 1
    rest_day_recovery: float = 20

    def __post_init__(self):
        for value in asdict(self).values():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('疲労の設定は有限の非負数で指定してください。')
        if self.max_fatigue <= 0:
            raise ValueError('疲労上限は正数で指定してください。')

    @classmethod
    def load(cls):
        path = Path(__file__).resolve().parents[2] / 'config' / 'cafe_shifts.json'
        return cls(**json.loads(path.read_text(encoding='utf-8')))


def fatigue_rest_schedule(cats, rest_count=2):
    """健康な猫を疲労降順・ID順で休ませ、出勤予定のIDを返す。状態は変更しない。"""
    healthy = sorted(key for key, cat in cats.items() if cat.health_status == 'healthy')
    resting = set(sorted(healthy, key=lambda key: (-cats[key].fatigue, key))[:rest_count])
    return [key for key in healthy if key not in resting]
