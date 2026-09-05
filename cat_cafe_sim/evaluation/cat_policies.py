from dataclasses import asdict
import statistics
from itertools import product

from cat_cafe_sim.envs import CatInteractionEnv
from cat_cafe_sim.policies import FixedCatPolicy, RandomCatPolicy


def evaluate(model, *, split="validation"):
    if split not in ("validation", "test"):
        raise ValueError("evaluation split must be validation or test")
    preferences_list = getattr(model.settings, f"{split}_preferences")
    seeds = getattr(model.settings, f"{split}_seeds")
    model.settings.validate_starts(model.config)
    profiles = getattr(model.settings, f"{split}_starts")
    starts = [(p.name, options) for p in profiles for options in p.cases()] if profiles else [("default", {})]
    results = []
    for preferences in preferences_list:
        for seed, (profile, options) in product(seeds, starts):
            for name in ("random", "fixed", "q_learning"):
                env = CatInteractionEnv(model.config, model.rewards)
                observation, info = env.reset(seed=seed, options={"preferences": preferences, **options})
                initial = dict(info["initial_state"])
                baseline = RandomCatPolicy(seed) if name == "random" else FixedCatPolicy()
                actions = []
                rewards = dict.fromkeys(asdict(model.rewards), 0.0)
                unknown = 0
                while True:
                    if name == "q_learning":
                        state = model.agent.encoder.encode(observation)
                        unknown += state not in model.agent.table
                        action = model.agent.act(state, info["action_mask"])
                    else:
                        action = baseline.choose(observation)
                    observation, _, terminated, truncated, info = env.step(action)
                    actions.append(action)
                    for key, value in info["reward_breakdown"].items():
                        rewards[key] += value
                    if terminated or truncated:
                        break
                results.append({"policy": name, "preferences": list(preferences), "seed": seed,
                                "start_profile": profile, "initial_state": initial,
                                "departure_reason": info["departure_reason"], **info["metrics"],
                                "reward": sum(rewards.values()), "reward_breakdown": rewards,
                                "unknown_states": unknown, "actions": actions})
                env.close()
    summary = {}
    for name in ("random", "fixed", "q_learning"):
        rows = [row for row in results if row["policy"] == name]
        summary[name] = {
            "episodes": len(rows),
            "success_rate": statistics.mean(r["departure_reason"] == "success" for r in rows),
            "failure_rate": statistics.mean(r["departure_reason"] == "failure" for r in rows),
            **{f"mean_{key}": statistics.mean(r[key] for r in rows)
               for key in ("reward", "satisfaction", "seated_ticks", "spirit_spent", "revenue")},
            "reward_stddev": statistics.pstdev(r["reward"] for r in rows),
            "unknown_state_rate": sum(r["unknown_states"] for r in rows) / sum(len(r["actions"]) for r in rows),
            "action_counts": [sum(r["actions"].count(i) for r in rows) for i in range(7)],
        }
    return {"split": split, "exploration": False, "learning": False,
            "summary": summary, "episodes": results}
