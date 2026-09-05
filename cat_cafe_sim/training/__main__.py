import argparse
import csv
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

from cat_cafe_sim import __version__
from cat_cafe_sim.core.config import Config, DEFAULT_CONFIG
from cat_cafe_sim.envs import CatInteractionEnv
from cat_cafe_sim.envs.rewards import CatRewards, DEFAULT_REWARDS
from cat_cafe_sim.evaluation.cat_policies import evaluate
from .encoding import StateEncoder
from .model import CatModel
from .runner import train
from .settings import TrainingSettings, DEFAULT_TRAINING


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def evaluation_report(model, model_path, split):
    return {"simulator_version": __version__, "environment_version": CatInteractionEnv.version,
            "runtime": {"python": platform.python_version(), "gymnasium": version("gymnasium"), "numpy": version("numpy")},
            "model_sha256": hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
            "game_config": model.config.to_dict(), "rewards": asdict(model.rewards),
            "training": model.settings.to_dict(), "encoder": model.agent.encoder.to_dict(),
            "state_space": model.agent.encoder.summary(), "known_states": len(model.agent.table),
            **evaluate(model, split=split)}


def main():
    parser = argparse.ArgumentParser(description="猫方策の状態数確認・Q学習・未使用条件の比較")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "train"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        command.add_argument("--training", type=Path, default=DEFAULT_TRAINING)
        if name == "train":
            command.add_argument("--rewards", type=Path, default=DEFAULT_REWARDS)
            command.add_argument("--episodes", type=int)
            command.add_argument("--seed", type=int)
            command.add_argument("--model", type=Path)
            command.add_argument("--report-prefix", type=Path)
    comparison = sub.add_parser("evaluate")
    comparison.add_argument("--model", type=Path, default=Path("models/cat_q.json"))
    comparison.add_argument("--split", choices=("validation", "test"), default="validation")
    comparison.add_argument("--output", type=Path, default=Path("reports/cat_q_evaluation.json"))
    args = parser.parse_args()
    if args.command == "evaluate":
        model = CatModel.load(args.model)
        report = evaluation_report(model, args.model, args.split)
        write_json(args.output, report)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        return
    config, settings = Config.load(args.config), TrainingSettings.load(args.training)
    if args.command == "train":
        overrides = {key: getattr(args, key) for key in ("episodes", "seed") if getattr(args, key) is not None}
        settings = replace(settings, **overrides)
        stem = (f"cat_q_stamina_seed{settings.seed}" if settings.stamina_edges is not None
                else f"cat_q_mixed_seed{settings.seed}" if settings.train_starts else "cat_q")
        args.model = args.model or Path("models") / f"{stem}.json"
        args.report_prefix = args.report_prefix or Path("reports") / stem
    settings.validate_starts(config)
    encoder = StateEncoder.for_config(config, settings.resource_edges, settings.time_edges, settings.stamina_edges)
    print(json.dumps(encoder.summary(), indent=2), flush=True)
    if encoder.summary()["state_upper_bound"] > settings.max_states:
        parser.error("state budget exceeded; reduce bins before training")
    if args.command == "inspect":
        return

    def progress(row):
        if row["episode"] % 100 == 0 or row["episode"] == settings.episodes:
            print(f"episode={row['episode']}/{settings.episodes} epsilon={row['epsilon']:.3f} "
                  f"reward={row['reward']:.2f} states={row['known_states']}", flush=True)

    model, rows = train(config, CatRewards.load(args.rewards), settings, progress=progress)
    model.save(args.model)
    csv_path = Path(str(args.report_prefix) + ".training.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    loaded = CatModel.load(args.model)
    original = evaluate(model, split="validation")
    report = evaluation_report(loaded, args.model, "validation")
    if original["episodes"] != report["episodes"]:
        raise RuntimeError("saved model did not reproduce evaluation trajectories")
    report["reload_verified"] = True
    write_json(str(args.report_prefix) + ".validation.json", report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved: {args.model}, {csv_path}; reload trajectories matched.")


if __name__ == "__main__":
    main()
