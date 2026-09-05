"""疎なQ表。評価時には未知状態の参照でも表・乱数状態を変更しない。"""
import math
from numbers import Integral
import random


class QLearningAgent:
    action_count = 7
    version = "tabular-q-v1"

    def __init__(self, encoder, *, learning_rate=0.15, discount=0.95, seed=0):
        for name, value in (("learning_rate", learning_rate), ("discount", discount)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if learning_rate == 0:
            raise ValueError("learning_rate must be positive")
        self.encoder = encoder
        self.learning_rate = learning_rate
        self.discount = discount
        self.rng = random.Random(seed)
        self.table = {}
        self.updates = 0

    def validate_state(self, state):
        if not isinstance(state, tuple) or len(state) != len(self.encoder.dimensions):
            raise ValueError("invalid state shape")
        if any(isinstance(x, bool) or not isinstance(x, Integral) or not 0 <= x < bound
               for x, bound in zip(state, self.encoder.dimensions)):
            raise ValueError("state index out of bounds")

    def values(self, state):
        self.validate_state(state)
        return tuple(self.table.get(state, (0.0,) * self.action_count))

    @staticmethod
    def valid_actions(mask):
        if len(mask) != 7 or any(x not in (0, 1) for x in mask):
            raise ValueError("action mask must contain seven binary values")
        actions = [i for i, valid in enumerate(mask) if valid]
        if not actions:
            raise ValueError("no valid action")
        return actions

    def act(self, state, mask, *, epsilon=0.0, random_ties=False):
        if not math.isfinite(epsilon) or not 0 <= epsilon <= 1:
            raise ValueError("epsilon must be in [0, 1]")
        values = self.values(state)
        valid = self.valid_actions(mask)
        if epsilon > 0 and self.rng.random() < epsilon:
            return self.rng.choice(valid)
        best = max(values[a] for a in valid)
        ties = [a for a in valid if values[a] == best]
        return self.rng.choice(ties) if random_ties else ties[0]

    def update(self, state, action, reward, next_state, *, terminated, truncated, next_mask):
        self.validate_state(state)
        self.validate_state(next_state)
        if isinstance(action, bool) or not isinstance(action, Integral) or not 0 <= action < 7:
            raise ValueError("invalid action")
        if not math.isfinite(reward):
            raise ValueError("reward must be finite")
        if type(terminated) is not bool or type(truncated) is not bool:
            raise ValueError("termination flags must be boolean")
        # 外部打ち切りではブートストラップを残す。本来の終了だけが将来価値0。
        future = 0.0 if terminated else max(self.values(next_state)[a] for a in self.valid_actions(next_mask))
        old = self.values(state)[action]
        updated = old + self.learning_rate * (reward + self.discount * future - old)
        if not math.isfinite(updated):
            raise ValueError("non-finite Q update")
        row = self.table.setdefault(state, [0.0] * self.action_count)
        row[action] = updated
        self.updates += 1
        return updated
