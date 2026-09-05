"""固定・旧Qモデル・新Qモデルを同じ営業条件で比較してログを保存する。"""
import argparse
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import statistics

from cat_cafe_sim import __version__
from cat_cafe_sim.core import SimulationCore
from cat_cafe_sim.policies import FixedCatPolicy, FixedManagerPolicy
from cat_cafe_sim.policies.learned import LearnedCatPolicy
from cat_cafe_sim.replay import save, verify

DEFAULT_CASES = Path(__file__).resolve().parents[2] / "config" / "cafe_evaluation.json"


def load_models(old_paths, new_paths):
    models = {}
    for group, paths in (("old", old_paths), ("new", new_paths)):
        if not paths:
            raise ValueError("both old and new model paths are required")
        for path in paths:
            policy = LearnedCatPolicy.load(path)
            label = f"{group}_seed{policy.model.settings.seed}"
            if label in models:
                raise ValueError("duplicate model seed within a group")
            models[label] = policy
    return models


def validate_cases(manifest, models):
    if set(manifest) != {"validation", "test"}:
        raise ValueError("validation and test day splits are required")
    cases, seeds_by_split = {}, {}
    base = next(iter(models.values())).model.config
    # 比較対象のゲームルール・報酬は同じ。方策の学習条件だけを比較する。
    rewards = next(iter(models.values())).model.rewards
    for policy in models.values():
        if policy.model.config != base or policy.model.rewards != rewards:
            raise ValueError("models must share game and reward settings")
    for split in ("validation", "test"):
        entry = manifest[split]
        seeds = entry["seeds"]
        if not seeds or any(type(s) is not int or s < 0 for s in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError("invalid day seeds")
        seeds_by_split[split] = set(seeds)
        scenarios = entry["scenarios"]
        if not scenarios or len({s["name"] for s in scenarios}) != len(scenarios):
            raise ValueError("invalid or duplicate day scenario names")
        cases[split] = set()
        for scenario in scenarios:
            if not re.fullmatch(r"[a-z0-9_]+", scenario["name"]):
                raise ValueError("scenario name must use lowercase letters, digits or underscores")
            preferences = tuple(scenario["preferences"])
            config = replace(base, preferences=preferences, arrival_ticks=tuple(scenario["arrival_ticks"]))
            config.validate()
            cases[split].add(preferences)
            for policy in models.values():
                policy.validate_config(config)
                settings = policy.model.settings
                forbidden = set(settings.train_preferences)
                if split == "test":
                    forbidden |= set(settings.validation_preferences)
                if preferences in forbidden:
                    raise ValueError("day evaluation preferences overlap training/tuning conditions")
        for policy in models.values():
            settings = policy.model.settings
            forbidden_seeds = set(settings.validation_seeds) | set(settings.test_seeds)
            if seeds_by_split[split] & forbidden_seeds or any(
                    settings.scenario_seed <= seed < settings.scenario_seed + settings.episodes for seed in seeds):
                raise ValueError("day seeds overlap interaction experiment seeds")
    if cases["validation"] & cases["test"] or seeds_by_split["validation"] & seeds_by_split["test"]:
        raise ValueError("day validation and test splits overlap")


def compare_days(models, manifest, *, split="test", log_dir=None):
    if split not in ("validation", "test"):
        raise ValueError("invalid day split")
    validate_cases(manifest, models)
    base = next(iter(models.values())).model.config
    results = []
    for scenario in manifest[split]["scenarios"]:
        config = replace(base, preferences=tuple(scenario["preferences"]), arrival_ticks=tuple(scenario["arrival_ticks"]))
        for seed in manifest[split]["seeds"]:
            for label in ("fixed", *models):
                policy = FixedCatPolicy() if label == "fixed" else LearnedCatPolicy(
                    models[label].model, model_sha256=models[label].model_sha256)
                core = SimulationCore(config, seed=seed, cat_policy=policy)
                while not core.closed:
                    core.step(manager_policy=FixedManagerPolicy())
                diagnostics = policy.diagnostics() if label != "fixed" else None
                log_path = None
                if log_dir is not None:
                    log_path = Path(log_dir) / f"{scenario['name']}_{seed}_{label}.json"
                    save(core, log_path, FixedManagerPolicy.version)
                    verify(log_path)
                results.append({"policy": label, "scenario": scenario["name"], **core.summary(),
                                "end_stamina": core.cat.stamina, "end_spirit": core.cat.spirit,
                                "discontent": sum(v.discontent for v in core.visits.values()),
                                "diagnostics": diagnostics, "replay": str(log_path) if log_path else None,
                                "actions": [e["action"] for e in core.events if e["kind"] == "action"]})
    summary = {}
    for label in ("fixed", *models):
        rows = [r for r in results if r["policy"] == label]
        decisions = sum(r["diagnostics"]["decisions"] for r in rows) if label != "fixed" else 0
        summary[label] = {"days": len(rows),
            **{f"mean_{key}": statistics.mean(r[key] for r in rows)
               for key in ("successes", "unserved", "failures", "revenue", "spirit_spent", "discontent")},
            "revenue_stddev": statistics.pstdev(r["revenue"] for r in rows),
            "unknown_state_rate": (sum(r["diagnostics"]["unknown_states"] for r in rows) / decisions
                                   if decisions else None)}
    paired = {}
    for label in models:
        if label.startswith("new_") and label.replace("new_", "old_", 1) in models:
            old_label = label.replace("new_", "old_", 1)
            paired[label] = {key: summary[label][key] - summary[old_label][key]
                             for key in ("mean_successes", "mean_unserved", "mean_revenue", "mean_spirit_spent")}
    return {"simulator_version": __version__, "split": split, "learning": False, "exploration": False,
            "manifest": manifest, "game_config": base.to_dict(), "rewards": asdict(next(iter(models.values())).model.rewards),
            "models": {label: {"sha256": p.model_sha256, "training": p.model.settings.to_dict(),
                                "known_states": len(p.model.agent.table)} for label, p in models.items()},
            "summary": summary, "paired_new_minus_old": paired, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-model", type=Path, nargs="+", required=True)
    parser.add_argument("--new-model", type=Path, nargs="+", required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--output", type=Path, default=Path("reports/mixed_day_comparison.json"))
    args = parser.parse_args()
    models = load_models(args.old_model, args.new_model)
    manifest = json.loads(args.cases.read_text(encoding="utf-8"))
    report = compare_days(models, manifest, split=args.split, log_dir=args.output.with_suffix(""))
    report["runtime"] = {name: version(name) for name in ("gymnasium", "numpy")}
    report["manifest_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    lines = [f"# 営業比較 ({args.split})", "",
             "同じ客条件・来店時刻・営業seedで比較。学習・探索は停止。各日のログは再生一致を確認済み。", "",
             "| 方策 | 日数 | 満足退店/日 | 未対応/日 | 不満退店/日 | 売上/日 | 気力消費/日 | 未知状態率 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for label, row in report["summary"].items():
        unknown = "—" if row["unknown_state_rate"] is None else f"{row['unknown_state_rate']:.1%}"
        lines.append(f"| {label} | {row['days']} | {row['mean_successes']:.2f} | {row['mean_unserved']:.2f} | "
                     f"{row['mean_failures']:.2f} | {row['mean_revenue']:.2f} | {row['mean_spirit_spent']:.2f} | {unknown} |")
    lines.extend(["", "不満退店は接客不能による退店を示し、待機中の不満は含まない。", "",
                  "現在の環境・方策は決定的なので、同じシナリオのseed反復を独立した客条件として扱わない。",
                  "モデルの識別情報、条件、各日の指標・行動列・再生ログのパスは同名JSONに保存。", ""])
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
