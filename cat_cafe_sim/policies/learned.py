"""保存済みQ方策を営業coreの猫インターフェースへ接続する。"""
from dataclasses import asdict
import hashlib
from pathlib import Path

from cat_cafe_sim.envs.observations import cat_observation
from cat_cafe_sim.training.model import CatModel


class LearnedCatPolicy:
    version = "tabular-q-cafe-v1"
    # 来店条件はモデルの入力契約・接客ルールを変えない。
    scenario_fields = frozenset({"arrival_ticks", "preferences", "queue_capacity",
                                 "max_wait_ticks", "initial_funds"})

    def __init__(self, model, *, model_sha256=None):
        self.model = model
        self.model_sha256 = model_sha256
        self.decisions = 0
        self.unknown_states = 0

    @classmethod
    def load(cls, path):
        path = Path(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(CatModel.load(path), model_sha256=digest)

    def validate_config(self, config):
        config.validate()
        trained = asdict(self.model.config)
        incompatible = []
        for key, value in asdict(config).items():
            if key in self.scenario_fields:
                continue
            if key == "opening_ticks":
                if value > trained[key]:
                    incompatible.append(key)
            elif value != trained[key]:
                incompatible.append(key)
        if incompatible:
            raise ValueError("model and cafe configuration mismatch: " + ", ".join(sorted(incompatible)))

    def choose(self, observation):
        # 満足・履歴はcoreの当該来店から受け取り、客をまたぐ私的な履歴を持たない。
        state = self.model.agent.encoder.encode(cat_observation(observation, self.model.config))
        action = self.model.agent.act(state, [1] * 7)
        self.decisions += 1
        self.unknown_states += state not in self.model.agent.table
        return action

    def diagnostics(self):
        return {"decisions": self.decisions, "unknown_states": self.unknown_states,
                "unknown_state_rate": self.unknown_states / self.decisions if self.decisions else 0.0}

    def metadata(self):
        return {"model_sha256": self.model_sha256, "policy_version": self.model.agent.version,
                "encoder_version": self.model.agent.encoder.version,
                "training_seed": self.model.settings.seed,
                "exploration": False, "learning": False, **self.diagnostics()}
