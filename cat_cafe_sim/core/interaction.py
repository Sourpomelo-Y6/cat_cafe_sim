"""営業と接客環境で共有する、交流履歴と満足効果の計算。"""
from dataclasses import dataclass

from .config import Action, Config
from .models import Visit


@dataclass(frozen=True)
class InteractionEffect:
    satisfaction: float
    boredom_multiplier: float
    switch_bonus: float


def apply_interaction_history(visit: Visit, action: Action, config: Config) -> InteractionEffect:
    # 休みや速度変更では種類別の連続履歴をリセットしない。
    if action.kind == "rest":
        return InteractionEffect(0, 1, 0)
    switched = visit.last_interaction_kind is not None and visit.last_interaction_kind != action.kind
    qualified = switched and visit.interaction_streak >= config.switch_min_streak
    visit.interaction_streak = 1 if visit.last_interaction_kind != action.kind else visit.interaction_streak + 1
    visit.last_interaction_kind = action.kind
    multiplier = max(config.boredom_min_multiplier,
                     1 - config.boredom_decay * max(0, visit.interaction_streak - config.boredom_free_actions))
    preference = config.preferences[0 if action.kind == "play" else 1]
    base = action.satisfaction * preference
    # 嫌がる行動の負効果は飽きで軽減せず、好み0の客へボーナスだけを与えない。
    bonus = config.switch_bonus * preference if qualified and base > 0 else 0
    return InteractionEffect(base * multiplier + bonus if base > 0 else base,
                             multiplier if base > 0 else 1, bonus)
