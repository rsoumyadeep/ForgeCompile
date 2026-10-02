"""EXP-003: ForgeCompile pipelines vs LLVM's optimizer, natively, plus run-to-run reproducibility.

Configurations (the runner defaults): ForgeCompile {O0, O1, O2} at LLVM -O0,
and ForgeCompile {O0, O2} at LLVM -O2. The whole suite is run *twice*, with
different seeds (so the run order also differs). The difference between the
two runs' medians is the empirical noise band; any effect smaller than that
band is reported as "not distinguishable from noise".

Usage::

    uv run python experiments/EXP-003-fc-vs-llvm/run.py --repeats 7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from forgecompile.benchmarking.report import geomean_speedups, markdown_table, speedups
from forgecompile.benchmarking.runner import DEFAULT_CONFIGS, run_suite
from forgecompile.benchmarking.suite import load_suite
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--seeds", type=int, nargs=2, default=[0, 1])
    parser.add_argument("--benchmarks", help="comma-separated subset (sanity runs)")
    parser.add_argument(
        "--sanity", action="store_true", help="tiny run; separate id, no curated output"
    )
    args = parser.parse_args()

    benchmarks = load_suite(names=args.benchmarks.split(",") if args.benchmarks else None)
    configs = DEFAULT_CONFIGS
    run = ExperimentRun.create(
        "EXP-003-fc-vs-llvm" + ("-sanity" if args.sanity else ""),
        {
            "configs": [
                {"name": c.name, "passes": list(c.passes), "llvm_opt": c.llvm_opt} for c in configs
            ],
            "repeats": args.repeats,
            "seeds": args.seeds,
            "benchmarks": [b.name for b in benchmarks],
        },
        seed=args.seeds[0],
        repo_dir=REPO,
    )
    with run:  # an exception marks the run failed, preserving its directory
        runs = []
        for seed in args.seeds:
            result = run_suite(benchmarks, configs, args.repeats, seed)
            run.save_json(f"suite_seed{seed}.json", result.to_json())
            runs.append([r.summary() for r in result.records])

        # Reproducibility: relative difference of medians between the two runs.
        first = {(r["benchmark"], r["config"]): r for r in runs[0]}
        deltas = []
        for r in runs[1]:
            a = first[(r["benchmark"], r["config"])]["native_median_s"]
            deltas.append(
                {
                    "benchmark": r["benchmark"],
                    "config": r["config"],
                    "rel_diff": abs(r["native_median_s"] - a) / a,
                }
            )
        deltas.sort(key=lambda d: d["rel_diff"])
        median_delta = deltas[len(deltas) // 2]["rel_diff"]
        p90_delta = deltas[int(len(deltas) * 0.9)]["rel_diff"]
        max_delta = deltas[-1]

        speed = [speedups(rows) for rows in runs]
        geo = [geomean_speedups(rows) for rows in runs]
        summary = {
            "geomean_speedup_run1": geo[0],
            "geomean_speedup_run2": geo[1],
            "reproducibility": {
                "median_rel_diff": median_delta,
                "p90_rel_diff": p90_delta,
                "max": max_delta,
            },
            "per_benchmark_speedup_run1": speed[0],
            "per_benchmark_speedup_run2": speed[1],
        }
        run.save_json("summary.json", summary)
    run.finalize("completed", {"geomean_run1": geo[0], "reproducibility_median": median_delta})

    if not args.sanity:  # curated copies only for real runs
        write(HERE / "table_run1.md", markdown_table(runs[0]))
        write(HERE / "table_run2.md", markdown_table(runs[1]))
        write(HERE / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
        write(
            HERE / "metadata.json",
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
        )
    print(json.dumps({k: v for k, v in summary.items() if not k.startswith("per_")}, indent=2))
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
