"""固定行動列による接客ルールの診断。学習や最終バランス評価ではない。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

import gymnasium
import numpy as np

from cat_cafe_sim import __version__
from cat_cafe_sim.core.config import Config, DEFAULT_CONFIG
from .cat_interaction import CatInteractionEnv
from .rewards import CatRewards, DEFAULT_REWARDS


PATTERNS = {
    "play_repeat": [1],
    "alternating": [1, 4],
    "two_each": [1, 1, 4, 4],
    "speed_cycle": [0, 1, 2],
    "rest_only": [6],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--rewards", type=Path, default=DEFAULT_REWARDS)
    parser.add_argument("--output", type=Path, default=Path("reports/interaction_baselines.json"))
    args = parser.parse_args()
    config, rewards = Config.load(args.config), CatRewards.load(args.rewards)
    results = []
    for preferences in ((1, 1), (1.5, 0.5), (0, 2)):
        for name, actions in PATTERNS.items():
            env = CatInteractionEnv(config, rewards)
            env.reset(seed=args.seed, options={"preferences": preferences})
            total_reward = 0.0
            totals = dict.fromkeys(asdict(rewards), 0.0)
            for index in range(config.opening_ticks):
                _, reward, terminated, truncated, info = env.step(actions[index % len(actions)])
                total_reward += reward
                for key, value in info["reward_breakdown"].items():
                    totals[key] += value
                if terminated or truncated:
                    break
            results.append({"preferences": preferences, "pattern": name, "actions": actions,
                            "departure_reason": info["departure_reason"], **info["metrics"],
                            "reward": total_reward, "reward_breakdown": totals})
            print(f"{preferences} {name}: {info['departure_reason']}, "
                  f"ticks={info['metrics']['seated_ticks']}, revenue={info['metrics']['revenue']}, "
                  f"reward={total_reward:.2f}")
            env.close()
    payload = {"simulator_version": __version__, "gymnasium_version": gymnasium.__version__,
               "numpy_version": np.__version__, "seed": args.seed, "config": config.to_dict(),
               "rewards": asdict(rewards), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
