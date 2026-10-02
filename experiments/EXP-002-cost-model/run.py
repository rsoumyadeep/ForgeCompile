"""EXP-002: does the IR-interpreter cost model predict native speedups?

For every benchmark and every ForgeCompile pipeline P (all compiled with LLVM
-O0, so that only ForgeCompile's decisions differ):

    predicted ratio  = interp_cost(P) / interp_cost(O0)         (small instance)
    measured ratio   = native_median(P) / native_median(O0)     (large instance)

A ratio below 1 means faster or cheaper. The question is how well the
predicted ratio tracks the measured one: Spearman (ranking), Pearson (linear),
pooled over all points and within each benchmark. Raw dynamic instruction
count (``steps``) is evaluated as an alternative predictor, to test whether
the latency weights add anything.

Usage::

    uv run python experiments/EXP-002-cost-model/run.py --repeats 5 --seed 0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from forgecompile.benchmarking.measure import BenchConfig
from forgecompile.benchmarking.runner import run_suite
from forgecompile.benchmarking.stats import pearson, spearman
from forgecompile.benchmarking.suite import load_suite
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

PIPELINES: dict[str, list[str]] = {
    "O0": [],
    "O1": PRESETS["O1"],
    "O2": PRESETS["O2"],
    "copyprop": ["copyprop"],
    "constfold": ["constfold"],
    "sccp": ["sccp"],
    "dce": ["copyprop", "dce"],
    "cse": ["copyprop", "cse"],
    "licm": ["copyprop", "licm"],
    "strength": ["copyprop", "strength"],
    "bce": ["copyprop", "bce"],
    "inline": ["inline"],
    "simplifycfg": ["simplifycfg"],
}


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--benchmarks", help="comma-separated subset (sanity runs)")
    parser.add_argument(
        "--sanity", action="store_true", help="tiny run; separate id, no curated output"
    )
    args = parser.parse_args()

    configs = [BenchConfig(name, tuple(passes), 0) for name, passes in PIPELINES.items()]
    benchmarks = load_suite(names=args.benchmarks.split(",") if args.benchmarks else None)
    run = ExperimentRun.create(
        "EXP-002-cost-model" + ("-sanity" if args.sanity else ""),
        {
            "pipelines": PIPELINES,
            "llvm_opt": 0,
            "repeats": args.repeats,
            "benchmarks": [b.name for b in benchmarks],
        },
        seed=args.seed,
        repo_dir=REPO,
    )
    with run:  # an exception marks the run failed, preserving its directory
        result = run_suite(benchmarks, configs, args.repeats, args.seed)
        run.save_json("suite.json", result.to_json())

        rows = [r.summary() for r in result.records]
        base = {r["benchmark"]: r for r in rows if r["config"] == "O0"}
        points = []
        for r in rows:
            if r["config"] == "O0":
                continue
            b = base[r["benchmark"]]
            points.append(
                {
                    "benchmark": r["benchmark"],
                    "config": r["config"],
                    "pred_cost": r["interp_cost"] / b["interp_cost"],
                    "pred_steps": r["interp_steps"] / b["interp_steps"],
                    "measured": r["native_median_s"] / b["native_median_s"],
                    "measured_min": r["native_min_s"] / b["native_min_s"],
                    "cv": r["native_cv"],
                }
            )
        xs_cost = [p["pred_cost"] for p in points]
        xs_steps = [p["pred_steps"] for p in points]
        ys = [p["measured"] for p in points]
        analysis: dict[str, object] = {
            "n_points": len(points),
            "pooled": {
                "spearman_cost": spearman(xs_cost, ys),
                "pearson_cost": pearson(xs_cost, ys),
                "spearman_steps": spearman(xs_steps, ys),
                "pearson_steps": pearson(xs_steps, ys),
            },
            "per_benchmark_spearman_cost": {},
            "startup_median_s": result.startup.median if result.startup else None,
        }
        per_bench: dict[str, float] = {}
        for bench in base:
            sub = [p for p in points if p["benchmark"] == bench]
            per_bench[bench] = spearman([p["pred_cost"] for p in sub], [p["measured"] for p in sub])
        analysis["per_benchmark_spearman_cost"] = per_bench
        run.save_json("analysis.json", {"analysis": analysis, "points": points})

        header = ["benchmark", "pipeline", "predicted (cost)", "predicted (steps)"]
        header += ["measured (median)", "measured (min)", "CV"]
        lines = ["| " + " | ".join(header) + " |", "|---|---|---:|---:|---:|---:|---:|"]
        for p in points:
            lines.append(
                f"| {p['benchmark']} | {p['config']} | {p['pred_cost']:.3f} | "
                f"{p['pred_steps']:.3f} | {p['measured']:.3f} | {p['measured_min']:.3f} | "
                f"{p['cv']:.1%} |"
            )
        pooled = analysis["pooled"]
        assert isinstance(pooled, dict)
        summary = (
            f"points: {len(points)}\n"
            f"pooled Spearman (cost vs measured): {pooled['spearman_cost']:.3f}\n"
            f"pooled Pearson  (cost vs measured): {pooled['pearson_cost']:.3f}\n"
            f"pooled Spearman (steps vs measured): {pooled['spearman_steps']:.3f}\n"
            f"pooled Pearson  (steps vs measured): {pooled['pearson_steps']:.3f}\n"
            "per-benchmark Spearman (cost): "
            + ", ".join(f"{k}={v:.2f}" for k, v in per_bench.items())
            + "\n"
        )
    run.finalize("completed", {"pooled": pooled})
    if not args.sanity:  # curated copies only for real runs
        write(HERE / "points.md", "\n".join(lines) + "\n")
        write(HERE / "summary.txt", summary)
        write(
            HERE / "analysis.json",
            json.dumps({"analysis": analysis, "points": points}, indent=2) + "\n",
        )
        write(
            HERE / "metadata.json",
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
        )
    print(summary)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
