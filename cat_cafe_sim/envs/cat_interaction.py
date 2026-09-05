from dataclasses import replace

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from cat_cafe_sim.core import Command, SimulationCore
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.models import Visit
from .rewards import CatRewards


class CatInteractionEnv(gym.Env):
    """猫1匹・客1人の接客。満足/不満/閉店はterminated、外部上限はtruncated。"""

    metadata = {"render_modes": []}
    version = "cat-interaction-v2"

    def __init__(self, config=None, rewards=None, *, max_steps=None):
        self.config = config or Config.load()
        self.config.validate()
        self.rewards = rewards or CatRewards.load()
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError("max_steps must be a positive integer or None")
        self.max_steps = max_steps
        self.action_space = spaces.Discrete(7)
        self.observation_space = spaces.Dict({
            # 満足/体力/気力の順。非公開の好みは含まない。
            "resources": spaces.Box(0.0, 1.0, shape=(3,), dtype=np.float32),
            "previous_action": spaces.Discrete(8),  # 7 = 行動前
            "last_interaction_kind": spaces.Discrete(3),  # 0=play, 1=pet, 2=なし
            "interaction_streak": spaces.Discrete(self.config.opening_ticks + 1),
            "remaining_ticks": spaces.Discrete(self.config.opening_ticks + 1),
            "first_action": spaces.Discrete(2),
            "first_visit": spaces.Discrete(2),
            "first_meeting": spaces.Discrete(2),
        })
        self.core = None
        self._done = False

    def _visit(self):
        # resetでは時間を進めない。初回step内で来店→着席→1行動を共通coreが処理する。
        return self.core.visits.get("guest-1", Visit("guest-1", 0))

    def _observation(self):
        v = self._visit()
        c = self.core.cat
        return {
            "resources": np.array([v.satisfaction / self.config.satisfaction_target,
                                   c.stamina / self.config.max_stamina,
                                   c.spirit / self.config.max_spirit], dtype=np.float32),
            "previous_action": 7 if v.previous_action is None else v.previous_action,
            "last_interaction_kind": {None: 2, "play": 0, "pet": 1}[v.last_interaction_kind],
            "interaction_streak": v.interaction_streak,
            "remaining_ticks": self.config.opening_ticks - self.core.tick,
            "first_action": int(v.actions_taken == 0),
            "first_visit": int(v.first_visit),
            "first_meeting": int(v.first_meeting),
        }

    def _info(self, events):
        v = self._visit()
        departure = next((e for e in events if e["kind"] == "departure"), None)
        return {
            "action_mask": np.full(7, 0 if self._done else 1, dtype=np.int8),
            # 外部打ち切り後も、学習の将来価値計算には元の状態の有効行動を渡す。
            "bootstrap_action_mask": np.full(7, 0 if v.departure_reason else 1, dtype=np.int8),
            "reward_breakdown": self.rewards.breakdown(events),
            "departure_reason": v.departure_reason,
            "accounting": {key: departure[key] if departure else 0.0 for key in ("base_charge", "bonus", "bill")},
            "metrics": {"satisfaction": v.satisfaction, "seated_ticks": v.seated_ticks,
                        "spirit_spent": self.core.spirit_spent, "revenue": v.bill,
                        "perfect": v.perfect},
            "events": events,
        }

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        options = dict(options or {})
        if set(options) - {"preferences"}:
            raise ValueError("supported reset option: preferences")
        # 条件の指定は実験側の責務。観測・infoに好みの値は返さない。
        config = replace(self.config, arrival_ticks=(0,), queue_capacity=max(1, self.config.queue_capacity),
                         preferences=tuple(options.get("preferences", self.config.preferences)))
        core_seed = int(self.np_random.integers(0, 2**31))
        self.core = SimulationCore(config, seed=core_seed)
        self._done = False
        return self._observation(), self._info([])

    def step(self, action):
        if self.core is None or self._done:
            raise RuntimeError("reset() is required before stepping a new episode")
        # Gymの無効な行動は状態を変えず拒否。店長の無効コマンド規則とは別契約。
        if isinstance(action, (bool, np.bool_)) or not self.action_space.contains(action):
            raise ValueError("action must be an integer in [0, 6]")
        command = Command("assign", "guest-1") if self.core.tick == 0 else Command("wait")
        _, events = self.core.step(command, cat_action=int(action))
        terminated = self._visit().departure_reason is not None
        truncated = not terminated and self.max_steps is not None and self.core.tick >= self.max_steps
        self._done = terminated or truncated
        info = self._info(events)
        return self._observation(), float(sum(info["reward_breakdown"].values())), terminated, truncated, info
