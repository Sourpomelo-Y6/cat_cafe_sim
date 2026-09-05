import argparse
import csv
import json
from pathlib import Path

from cat_cafe_sim.core import SimulationCore
from cat_cafe_sim.core.config import Config, DEFAULT_CONFIG
from cat_cafe_sim.policies import FixedCatPolicy, RandomCatPolicy, FixedManagerPolicy
from cat_cafe_sim.replay import save, verify


def main():
    parser = argparse.ArgumentParser(description="猫カフェ Phase 1: UIなしの1日営業と再生検証")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--policy", choices=("fixed", "random"), default="fixed")
    run.add_argument("--output", type=Path, default=Path("reports/day.json"))
    replay = sub.add_parser("replay")
    replay.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "replay":
        core = verify(args.path)
        print("再生一致: 全tickの状態・イベント・集計を確認しました。")
    else:
        policy = FixedCatPolicy() if args.policy == "fixed" else RandomCatPolicy(args.seed)
        manager = FixedManagerPolicy()
        core = SimulationCore(Config.load(args.config), seed=args.seed, cat_policy=policy)
        while not core.closed:
            core.step(manager_policy=manager)
        save(core, args.output, manager.version)
        with args.output.with_suffix(".csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(core.summary()))
            writer.writeheader()
            writer.writerow({k: json.dumps(v) if isinstance(v, dict) else v for k, v in core.summary().items()})
    print(json.dumps(core.summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
