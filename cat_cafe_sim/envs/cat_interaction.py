from dataclasses import replace
from collections.abc import Mapping
from numbers import Integral

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from cat_cafe_sim.core import Command, SimulationCore, StartState
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.models import Visit
from .rewards import CatRewards
from .observations import cat_observation


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
        self._elapsed_steps = 0

    def _visit(self):
        # resetでは時間を進めない。初回step内で来店→着席→1行動を共通coreが処理する。
        return self.core.visits.get("guest-1", Visit("guest-1", self.core.start_state.tick))

    def _observation(self):
        v = self._visit()
        c = self.core.cat
        return cat_observation({
            "satisfaction": v.satisfaction, "stamina": c.stamina, "spirit": c.spirit,
            "previous_action": v.previous_action, "last_interaction_kind": v.last_interaction_kind,
            "interaction_streak": v.interaction_streak,
            "remaining_ticks": self.config.opening_ticks - self.core.tick,
            "first_action": v.actions_taken == 0, "first_visit": v.first_visit,
            "first_meeting": v.first_meeting,
        }, self.config)

    def _info(self, events):
        v = self._visit()
        departure = next((e for e in events if e["kind"] == "departure"), None)
        return {
            "initial_state": {"stamina": self.core.start_state.stamina,
                              "spirit": self.core.start_state.spirit,
                              "remaining_ticks": self.config.opening_ticks - self.core.start_state.tick},
            "elapsed_steps": self._elapsed_steps,
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
        if options is not None and not isinstance(options, Mapping):
            raise ValueError("reset options must be a mapping")
        options = dict(options or {})
        if set(options) - {"preferences", "stamina", "spirit", "remaining_ticks"}:
            raise ValueError("supported reset options: preferences, stamina, spirit, remaining_ticks")
        remaining = options.get("remaining_ticks", self.config.opening_ticks)
        if isinstance(remaining, bool) or not isinstance(remaining, Integral) or not 1 <= remaining <= self.config.opening_ticks:
            raise ValueError("remaining_ticks must be an integer in [1, opening_ticks]")
        initial = StartState(options.get("stamina", self.config.max_stamina),
                             options.get("spirit", self.config.max_spirit),
                             self.config.opening_ticks - int(remaining))
        initial.validate(self.config)
        # 条件の指定は実験側の責務。観測・infoに好みの値は返さない。
        config = replace(self.config, arrival_ticks=(initial.tick,), queue_capacity=max(1, self.config.queue_capacity),
                         preferences=tuple(options.get("preferences", self.config.preferences)))
        config.validate()
        # 不正な開始条件で、進行中の接客や乱数状態を変更しない。
        super().reset(seed=seed)
        core_seed = int(self.np_random.integers(0, 2**31))
        self.core = SimulationCore(config, seed=core_seed, start_state=initial)
        self._done = False
        self._elapsed_steps = 0
        return self._observation(), self._info([])

    def step(self, action):
        if self.core is None or self._done:
            raise RuntimeError("reset() is required before stepping a new episode")
        # Gymの無効な行動は状態を変えず拒否。店長の無効コマンド規則とは別契約。
        if isinstance(action, (bool, np.bool_)) or not self.action_space.contains(action):
            raise ValueError("action must be an integer in [0, 6]")
        command = Command("assign", "guest-1") if self._elapsed_steps == 0 else Command("wait")
        _, events = self.core.step(command, cat_action=int(action))
        self._elapsed_steps += 1
        terminated = self._visit().departure_reason is not None
        truncated = not terminated and self.max_steps is not None and self._elapsed_steps >= self.max_steps
        self._done = terminated or truncated
        info = self._info(events)
        return self._observation(), float(sum(info["reward_breakdown"].values())), terminated, truncated, info
