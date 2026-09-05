"""推論モデルのJSON保存。pickleや外部コードの実行は使わない。"""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from cat_cafe_sim import __version__
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.envs import CatInteractionEnv
from cat_cafe_sim.envs.rewards import CatRewards
from .encoding import StateEncoder
from .q_learning import QLearningAgent
from .settings import TrainingSettings


@dataclass
class CatModel:
    agent: QLearningAgent
    config: Config
    rewards: CatRewards
    settings: TrainingSettings

    def save(self, path):
        payload = {
            "format_version": 1, "policy_version": self.agent.version,
            "simulator_version": __version__, "environment_version": CatInteractionEnv.version,
            "game_config": self.config.to_dict(), "rewards": asdict(self.rewards),
            "training": self.settings.to_dict(), "encoder": self.agent.encoder.to_dict(),
            "learning_rate": self.agent.learning_rate, "discount": self.agent.discount,
            "updates": self.agent.updates,
            "q_rows": [{"state": list(state), "values": list(values)}
                       for state, values in sorted(self.agent.table.items())],
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # JSONのNaN/Infinityは保存しない。読込時にも構造と整合性を検証する。
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (data["format_version"] != 1 or data["policy_version"] != QLearningAgent.version
                or data["simulator_version"] != __version__ or data["environment_version"] != CatInteractionEnv.version):
            raise ValueError("unsupported model version")
        config = Config.from_dict(data["game_config"])
        rewards = CatRewards(**data["rewards"])
        settings = TrainingSettings.from_dict(data["training"])
        encoder = StateEncoder.from_dict(data["encoder"])
        expected = StateEncoder.for_config(config, settings.resource_edges, settings.time_edges)
        if encoder != expected or encoder.summary()["state_upper_bound"] > settings.max_states:
            raise ValueError("model encoder does not match configuration or state budget")
        if data["learning_rate"] != settings.learning_rate or data["discount"] != settings.discount:
            raise ValueError("model hyperparameters do not match training settings")
        agent = QLearningAgent(encoder, learning_rate=data["learning_rate"], discount=data["discount"], seed=settings.seed)
        if type(data["updates"]) is not int or data["updates"] < 0:
            raise ValueError("invalid update count")
        agent.updates = data["updates"]
        for row in data["q_rows"]:
            state = tuple(row["state"])
            agent.validate_state(state)
            values = row["values"]
            if state in agent.table or len(values) != 7 or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError("invalid or duplicate Q row")
            agent.table[state] = list(values)
        return cls(agent, config, rewards, settings)
