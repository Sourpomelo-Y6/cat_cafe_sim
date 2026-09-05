"""接客環境と営業中の学習済み猫で共通の観測変換。"""
import numpy as np


def cat_observation(raw, config):
    return {
        # Gym環境と同じfloat32で丸めてから離散化する。
        "resources": np.array([raw["satisfaction"] / config.satisfaction_target,
                               raw["stamina"] / config.max_stamina,
                               raw["spirit"] / config.max_spirit], dtype=np.float32),
        "previous_action": 7 if raw["previous_action"] is None else raw["previous_action"],
        "last_interaction_kind": {None: 2, "play": 0, "pet": 1}[raw["last_interaction_kind"]],
        "interaction_streak": raw["interaction_streak"],
        "remaining_ticks": raw["remaining_ticks"],
        "first_action": int(raw["first_action"]),
        "first_visit": int(raw["first_visit"]),
        "first_meeting": int(raw["first_meeting"]),
    }
