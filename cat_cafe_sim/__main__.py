import argparse
import csv
import json
from pathlib import Path

from cat_cafe_sim.core import SimulationCore
from cat_cafe_sim.core.config import Config, DEFAULT_CONFIG
from cat_cafe_sim.policies import FixedCatPolicy, RandomCatPolicy, FixedManagerPolicy
from cat_cafe_sim.replay import save, verify


def main():
    parser = argparse.ArgumentParser(description="猫カフェ: 固定・ランダム・学習済み猫による1日営業と再生検証")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path, help="省略時は既定設定。learnedではモデル内の設定")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--policy", choices=("fixed", "random", "learned"), default="fixed")
    run.add_argument("--model", type=Path, help="learned用の保存済みQモデルJSON")
    run.add_argument("--output", type=Path, default=Path("reports/day.json"))
    replay = sub.add_parser("replay")
    replay.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "replay":
        core = verify(args.path)
        print("再生一致: 全tickの状態・イベント・集計を確認しました。")
    else:
        if args.policy == "learned" and args.model is None:
            parser.error("--policy learned requires --model")
        if args.policy != "learned" and args.model is not None:
            parser.error("--model is only supported with --policy learned")
        try:
            if args.policy == "learned":
                # 固定・ランダム営業とログ再生には学習依存を読み込まない。
                from cat_cafe_sim.policies.learned import LearnedCatPolicy
                policy = LearnedCatPolicy.load(args.model)
                config = Config.load(args.config) if args.config else policy.model.config
                policy.validate_config(config)
            else:
                policy = FixedCatPolicy() if args.policy == "fixed" else RandomCatPolicy(args.seed)
                config = Config.load(args.config or DEFAULT_CONFIG)
        except ModuleNotFoundError as error:
            if error.name not in ("gymnasium", "numpy"):
                raise
            parser.error("learned requires dependencies: install requirements-env.txt")
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(str(error))
        manager = FixedManagerPolicy()
        core = SimulationCore(config, seed=args.seed, cat_policy=policy)
        while not core.closed:
            core.step(manager_policy=manager)
        save(core, args.output, manager.version)
        with args.output.with_suffix(".csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(core.summary()))
            writer.writeheader()
            writer.writerow({k: json.dumps(v) if isinstance(v, dict) else v for k, v in core.summary().items()})
    result = core.summary()
    if args.command == "run" and args.policy == "learned":
        result["policy_diagnostics"] = policy.metadata()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
