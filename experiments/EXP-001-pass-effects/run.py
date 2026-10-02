"""EXP-001: effect of each optimization pass, alone and in presets, on IR-level metrics.

Metrics (deterministic: from the IR interpreter, not wall-clock):
  * dynamic IR instructions executed (``steps``, excluding phis);
  * weighted cost under ``DEFAULT_COST_MODEL`` (assumed latencies, not yet validated);
  * static instruction count after optimization;
  * pass/pipeline compile time (wall-clock, median of repeats; secondary metric).

For each configuration we report the geometric mean over programs of
``optimized / unoptimized``, separately for the hand-written examples and the
generated programs. The two groups are kept apart because they are very
different distributions (DECISIONS D-020).

Usage::

    uv run python experiments/EXP-001-pass-effects/run.py --generated 200 --seed 0
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.optimization.pass_manager import PRESETS, available_passes, optimize
from forgecompile.optimization.utils import module_instruction_count
from forgecompile.testing.program_generator import generate_program
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def geomean(ratios: list[float]) -> float:
    return math.exp(sum(math.log(r) for r in ratios) / len(ratios))


def measure(source: str, pipeline: list[str], repeats: int) -> dict[str, float]:
    times = []
    module = build_ir(source)
    for _ in range(repeats):
        module = build_ir(source)
        start = time.perf_counter()
        optimize(module, pipeline, verify=False)
        times.append(time.perf_counter() - start)
    result = run_module(module)
    return {
        "steps": result.steps,
        "cost": result.cost,
        "static": module_instruction_count(module),
        "compile_ms": statistics.median(times) * 1000,
        "stdout": result.stdout,  # used for the correctness assertion only
        "exit": result.exit_code,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0, help="first generator seed")
    parser.add_argument("--repeats", type=int, default=3, help="compile-time repeats")
    args = parser.parse_args()

    configs: dict[str, list[str]] = {name: [name] for name in available_passes()}
    configs.update({f"preset:{k}": v for k, v in PRESETS.items() if v})
    # Phase-ordering probes: passes that depend on canonicalized (copy-free) IR.
    configs["copyprop+bce"] = ["copyprop", "bce"]
    configs["copyprop+strength"] = ["copyprop", "strength"]
    configs["copyprop+licm"] = ["copyprop", "licm"]

    config = {
        "generated_programs": args.generated,
        "first_seed": args.seed,
        "compile_time_repeats": args.repeats,
        "configurations": configs,
    }
    run = ExperimentRun.create("EXP-001-pass-effects", config, seed=args.seed, repo_dir=REPO)

    groups = {
        "examples": [
            (p.name, p.read_text("utf-8")) for p in sorted((REPO / "examples").glob("*.mini"))
        ],
        "generated": [
            (f"gen{s}", generate_program(s)) for s in range(args.seed, args.seed + args.generated)
        ],
    }
    table: dict[str, dict[str, dict[str, float]]] = {}
    for group, programs in groups.items():
        baselines = {label: measure(src, [], 1) for label, src in programs}
        for name, pipeline in configs.items():
            ratios: dict[str, list[float]] = {"steps": [], "cost": [], "static": []}
            compile_ms = []
            for label, src in programs:
                base = baselines[label]
                opt = measure(src, pipeline, args.repeats)
                assert (opt["stdout"], opt["exit"]) == (base["stdout"], base["exit"]), (name, label)
                for metric in ratios:
                    ratios[metric].append(opt[metric] / base[metric] if base[metric] else 1.0)
                compile_ms.append(opt["compile_ms"])
            table.setdefault(name, {})[group] = {
                "geomean_steps_ratio": geomean(ratios["steps"]),
                "geomean_cost_ratio": geomean(ratios["cost"]),
                "geomean_static_ratio": geomean(ratios["static"]),
                "best_cost_ratio": min(ratios["cost"]),
                "worst_cost_ratio": max(ratios["cost"]),
                "median_compile_ms": statistics.median(compile_ms),
            }
    run.save_json("results.json", table)

    header = ["configuration", "group", "steps ratio", "cost ratio", "static ratio"]
    header += ["cost best / worst", "compile ms"]
    lines = ["| " + " | ".join(header) + " |", "|---|---|---:|---:|---:|---:|---:|"]
    for name, by_group in table.items():
        for group, m in by_group.items():
            cells = [
                name,
                group,
                f"{m['geomean_steps_ratio']:.3f}",
                f"{m['geomean_cost_ratio']:.3f}",
                f"{m['geomean_static_ratio']:.3f}",
                f"{m['best_cost_ratio']:.3f} / {m['worst_cost_ratio']:.3f}",
                f"{m['median_compile_ms']:.2f}",
            ]
            lines.append("| " + " | ".join(cells) + " |")
    markdown = "\n".join(lines) + "\n"
    (run.run_dir / "results.md").write_text(markdown, "utf-8")
    # Curated copy, committed alongside the script (experiments/README.md).
    (HERE / "results.md").write_text(markdown, "utf-8")
    (HERE / "results.json").write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", "utf-8")
    (HERE / "metadata.json").write_text(
        json.dumps(run.metadata, indent=2, default=str) + "\n", "utf-8"
    )
    run.finalize(
        "completed", {"configurations": len(configs), "programs": sum(map(len, groups.values()))}
    )
    print(markdown)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
