"""``forgecompile bench``: run the benchmark suite and record the results."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forgecompile.benchmarking.measure import BenchConfig
from forgecompile.benchmarking.report import geomean_speedups, markdown_table, to_csv
from forgecompile.benchmarking.runner import DEFAULT_CONFIGS, run_suite
from forgecompile.benchmarking.suite import DEFAULT_SUITE_DIR, BenchmarkError, load_suite
from forgecompile.cli.common import EXIT_OK, CliError
from forgecompile.optimization.pass_manager import parse_pipeline
from forgecompile.utils.experiment import ExperimentRun


def parse_config(spec: str) -> BenchConfig:
    """``name=PIPELINE@LLVMOPT``, e.g. ``mine=copyprop,bce@0`` or ``O2fast=O2@2``."""
    try:
        name, rest = spec.split("=", 1)
        pipeline, llvm_opt = rest.rsplit("@", 1)
        return BenchConfig(name, tuple(parse_pipeline(pipeline)), int(llvm_opt))
    except ValueError as exc:
        raise CliError(f"bad --config {spec!r} (expected NAME=PIPELINE@LLVMOPT): {exc}") from None


def _cmd_bench(args: argparse.Namespace) -> int:
    try:
        benchmarks = load_suite(
            Path(args.suite), args.benchmarks.split(",") if args.benchmarks else None
        )
    except BenchmarkError as exc:
        raise CliError(str(exc)) from None
    configs = [parse_config(spec) for spec in args.config] if args.config else DEFAULT_CONFIGS
    run = ExperimentRun.create(
        args.experiment,
        {
            "benchmarks": [b.name for b in benchmarks],
            "configs": [
                {"name": c.name, "passes": list(c.passes), "llvm_opt": c.llvm_opt} for c in configs
            ],
            "repeats": args.repeats,
            "native": not args.no_native,
        },
        seed=args.seed,
    )
    try:
        result = run_suite(benchmarks, configs, args.repeats, args.seed, native=not args.no_native)
    except Exception:
        run.finalize("failed")
        raise
    summaries = [r.summary() for r in result.records]
    run.save_json("results.json", result.to_json())
    (run.run_dir / "summary.csv").write_text(to_csv(summaries), encoding="utf-8", newline="\n")
    table = markdown_table(summaries)
    (run.run_dir / "summary.md").write_text(table, encoding="utf-8", newline="\n")
    geo = geomean_speedups(summaries)
    run.finalize(
        "completed",
        {
            "geomean_speedup": geo,
            "startup_median_s": result.startup.median if result.startup else None,
        },
    )
    print(table)
    if geo:
        print("geometric-mean speedup vs fc-O0.llvm-O0:")
        for name, value in geo.items():
            print(f"  {name:<18} {value:.3f}x")
    if result.startup:
        print(f"process startup (empty program): median {result.startup.median * 1000:.1f} ms")
    print(f"results: {run.run_dir}", file=sys.stderr)
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    bench = subparsers.add_parser("bench", help="run the benchmark suite (correctness-checked)")
    bench.add_argument("--suite", default=str(DEFAULT_SUITE_DIR), help="benchmark directory")
    bench.add_argument("--benchmarks", help="comma-separated subset of benchmark names")
    bench.add_argument(
        "--config",
        action="append",
        help="configuration NAME=PIPELINE@LLVMOPT (repeatable); default: 5 standard configs",
    )
    bench.add_argument("--repeats", type=int, default=5, help="timed runs per configuration")
    bench.add_argument("--seed", type=int, default=0, help="seed for the run order")
    bench.add_argument("--no-native", action="store_true", help="interpreter metrics only")
    bench.add_argument(
        "--experiment", default="EXP-000-adhoc", help="experiment id for the run directory"
    )
    bench.set_defaults(handler=_cmd_bench)
