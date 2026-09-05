import json
from pathlib import Path

from cat_cafe_sim import __version__
from cat_cafe_sim.core import Command, SimulationCore
from cat_cafe_sim.core.config import Config


def save(core, path, manager_version="manual-v1"):
    payload = {"format_version": 1, "simulator_version": __version__,
               "config": core.config.to_dict(), "seed": core.seed,
               "cat_policy_version": core.cat_policy.version,
               "manager_policy_version": manager_version,
               "records": core.records, "summary": core.summary()}
    metadata = getattr(core.cat_policy, "metadata", None)
    if metadata is not None:
        payload["cat_policy_metadata"] = metadata()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload["format_version"] != 1 or payload["simulator_version"] != __version__:
        raise ValueError("unsupported replay version")
    core = SimulationCore(Config.from_dict(payload["config"]), seed=payload["seed"])
    for index, record in enumerate(payload["records"]):
        core.step(Command(**record["command"]), cat_action=record["cat_action"])
        if core.records[-1] != record:
            raise ValueError(f"replay mismatch at tick {index}")
    if core.summary() != payload["summary"]:
        raise ValueError("replay summary mismatch")
    return core
