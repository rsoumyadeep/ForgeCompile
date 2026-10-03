"""EXP-008: do learned pass schedules make *native* code faster or smaller, and at what overhead?

EXP-005/006 score policies on the interpreter cost model. This experiment
measures what the brief actually asks about, on the hand-written benchmark
kernels (none of them seen in training or model selection):

1. For each benchmark and policy, decide the pass schedule on the small
   instance (``ml.policies.schedule``, budget 12) and record the decision time.
2. Compile the large instance with that exact pass list at LLVM -O0 (D-028) and
   time it with the Phase 6 protocol (``benchmarking.runner.run_suite``):
   correctness gate, warm-up, interleaved seeded rounds, medians.
3. Record native median time, ``.text`` bytes, ForgeCompile pass time, decision
   time and the native compile time. ``llvm-O2`` (no ForgeCompile passes) is
   included as an external reference point, not as a competitor.

Policies: fc-O0 (no passes), O1, O2, frequency, the supervised model (EXP-004
selection rule), oracle-greedy, and each DQN checkpoint given with ``--dqn`` (chosen by
*validation* score, never by test results), plus its no-retry variant with ``--noretry``.

Usage::

    uv run python experiments/EXP-008-native-policies/run.py --repeats 10 --workers 8
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from forgecompile.benchmarking.measure import BenchConfig
from forgecompile.benchmarking.runner import run_suite
from forgecompile.benchmarking.suite import load_suite
from forgecompile.driver import build_ir
from forgecompile.ml.data_pipeline import DatasetConfig, build_dataset
from forgecompile.ml.dataset import CostEvaluator
from forgecompile.ml.features import FEATURE_NAMES
from forgecompile.ml.models import select_model
from forgecompile.ml.policies import (
    FixedPipelinePolicy,
    ModelPolicy,
    OraclePolicy,
    Policy,
    frequency_order,
    schedule,
)
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.rl.dqn import DQNAgent, DQNPolicy
from forgecompile.rl.env import ENV_ACTIONS
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MAX_STEPS = 12
REFERENCE = "fc-O0"


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4, help="dataset workers (cached)")
    parser.add_argument("--benchmarks", help="comma-separated subset (sanity runs)")
    parser.add_argument(
        "--dqn",
        type=Path,
        nargs="*",
        default=[REPO / "experiments" / "EXP-006-rl-scheduling" / "checkpoints" / "dqn_seed0.npz"],
        help="DQN checkpoints (.npz); default: EXP-006 seed 0 (best validation score)",
    )
    parser.add_argument(
        "--noretry", action="store_true", help="also evaluate each DQN with the no-retry wrapper"
    )
    parser.add_argument("--sanity", action="store_true", help="separate id, no curated output")
    args = parser.parse_args()

    dataset_config = DatasetConfig()
    checkpoints = [p.resolve() for p in args.dqn]
    benchmarks = load_suite(names=args.benchmarks.split(",") if args.benchmarks else None)
    run = ExperimentRun.create(
        "EXP-008-native-policies" + ("-sanity" if args.sanity else ""),
        {
            "dataset": dataset_config.__dict__,
            "repeats": args.repeats,
            "max_steps": MAX_STEPS,
            "llvm_opt": 0,
            "benchmarks": [b.name for b in benchmarks],
            "dqn_checkpoints": [str(p.relative_to(REPO)) for p in checkpoints],
            "dqn_noretry": args.noretry,
        },
        seed=args.seed,
        repo_dir=REPO,
    )
    with run:
        data = build_dataset(dataset_config, workers=args.workers)
        model, _ = select_model(data["train"], data["val"], args.seed)
        order = frequency_order(data["train"])
        evaluator = CostEvaluator("cost")
        obs_size = len(FEATURE_NAMES) + 1 + len(ENV_ACTIONS)
        agents = {
            f"{p.parent.parent.name.split('-')[1]}:{p.stem}": DQNAgent.load(
                p, obs_size, len(ENV_ACTIONS)
            )
            for p in checkpoints
        }  # names like "006:dqn_seed0"

        def policies() -> list[Policy]:
            out: list[Policy] = [
                FixedPipelinePolicy(REFERENCE, []),
                FixedPipelinePolicy("O1", PRESETS["O1"]),
                FixedPipelinePolicy("O2", PRESETS["O2"]),
                FixedPipelinePolicy("frequency", order),
                ModelPolicy(model, name=f"model:{model.name}"),
                OraclePolicy(evaluator),
            ]
            for stem, a in agents.items():
                out.append(DQNPolicy(a, MAX_STEPS, name=stem))
                if args.noretry:
                    out.append(DQNPolicy(a, MAX_STEPS, name=f"{stem}+noretry", no_retry=True))
            return out

        rows: list[dict[str, object]] = []
        suites: dict[str, object] = {}
        for bench in benchmarks:
            module = build_ir(bench.instantiate("small"), bench.name)
            decisions: dict[str, tuple[list[str], float]] = {}
            for policy in policies():
                result = schedule(policy, module, MAX_STEPS)
                decisions[policy.name] = (result.actions, result.decision_seconds)
            configs = [BenchConfig(name, tuple(acts), 0) for name, (acts, _) in decisions.items()]
            configs.append(BenchConfig("llvm-O2", (), 2))
            suite = run_suite([bench], configs, args.repeats, args.seed)
            suites[bench.name] = suite.to_json()
            summaries = {r.config: r.summary() for r in suite.records}
            ref = summaries[REFERENCE]
            for name, s in summaries.items():
                actions, decision_s = decisions.get(name, ([], 0.0))
                rows.append(
                    {
                        "benchmark": bench.name,
                        "class": bench.workload_class,
                        "policy": name,
                        "actions": actions,
                        "n_passes": len(actions),
                        "decision_ms": 1000 * decision_s,
                        "pass_ms": s["pass_ms"],
                        "native_compile_s": s["native_compile_s"],
                        "text_bytes": s["text_bytes"],
                        "native_median_s": s["native_median_s"],
                        "native_cv": s["native_cv"],
                        "native_ratio": s["native_median_s"] / ref["native_median_s"],
                        "size_ratio": s["text_bytes"] / ref["text_bytes"],
                        "interp_cost_ratio": s["interp_cost"] / ref["interp_cost"],
                    }
                )
            run.save_json("rows.json", rows)  # incremental
        run.save_json("suites.json", suites)

        policy_names = list(dict.fromkeys(str(r["policy"]) for r in rows))
        summary: dict[str, dict[str, float]] = {}
        for name in policy_names:
            items = [r for r in rows if r["policy"] == name]
            summary[name] = {
                "geomean_native_ratio": geomean([float(str(r["native_ratio"])) for r in items]),
                "geomean_size_ratio": geomean([float(str(r["size_ratio"])) for r in items]),
                "geomean_interp_cost_ratio": geomean(
                    [float(str(r["interp_cost_ratio"])) for r in items]
                ),
                "worst_native_ratio": max(float(str(r["native_ratio"])) for r in items),
                "mean_decision_ms": sum(float(str(r["decision_ms"])) for r in items) / len(items),
                "mean_pass_ms": sum(float(str(r["pass_ms"])) for r in items) / len(items),
                "mean_passes": sum(int(str(r["n_passes"])) for r in items) / len(items),
            }
        run.save_json("summary.json", summary)
    run.finalize("completed", {"policies": policy_names})

    header = "| policy | native time (geomean vs fc-O0) | worst | .text size | interp cost | "
    header += "passes | decision ms | pass ms |"
    lines = [header, "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in sorted(summary.items(), key=lambda kv: kv[1]["geomean_native_ratio"]):
        lines.append(
            f"| {name} | {m['geomean_native_ratio']:.3f} | {m['worst_native_ratio']:.3f} | "
            f"{m['geomean_size_ratio']:.3f} | {m['geomean_interp_cost_ratio']:.3f} | "
            f"{m['mean_passes']:.1f} | {m['mean_decision_ms']:.1f} | {m['mean_pass_ms']:.1f} |"
        )
    per_bench = ["", "| benchmark | policy | native ratio | CV | size ratio | passes |"]
    per_bench.append("|---|---|---:|---:|---:|---|")
    for r in rows:
        per_bench.append(
            f"| {r['benchmark']} | {r['policy']} | {float(str(r['native_ratio'])):.3f} | "
            f"{float(str(r['native_cv'])):.1%} | {float(str(r['size_ratio'])):.3f} | "
            f"{','.join(r['actions']) if isinstance(r['actions'], list) else ''} |"
        )
    markdown = "\n".join(lines + per_bench) + "\n"
    if not args.sanity:
        write(HERE / "results.md", markdown)
        write(HERE / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
        write(HERE / "rows.json", json.dumps(rows, indent=2) + "\n")
        write(
            HERE / "metadata.json",
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
        )
    print(markdown)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
