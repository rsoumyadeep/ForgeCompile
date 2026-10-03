"""EXP-011: how much better than O2 can *any* 12-pass schedule be? (headroom via beam search)

EXP-005 found O2 within 1% of the one-step greedy oracle. That bounds greedy
learners, not schedulers with lookahead. This experiment estimates the headroom
for any schedule with beam search over pass sequences, using the interpreter
cost (the same objective the learners optimize):

* width 1 = the greedy oracle (sanity: must match EXP-005's oracle-greedy);
* widths 4 and 16 = increasingly thorough searches. Every node keeps the best
  cost seen at any depth (stopping early is always allowed), and states are
  deduplicated by IR hash.

Beam search is a lower bound on the true optimum and an upper bound on what a
policy can be expected to find. Programs: the generated test split and the OOD
programs (no training, no tuning; this only measures).

Usage::

    uv run python experiments/EXP-011-headroom/run.py --widths 1 4 16 --workers 16
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ir.function import Module
from forgecompile.ir.printer import format_module
from forgecompile.ml.data_pipeline import DatasetConfig, program_splits
from forgecompile.ml.dataset import ACTIONS, CostEvaluator, ProgramSpec, apply_pass
from forgecompile.optimization.pass_manager import PRESETS, optimize
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MAX_STEPS = 12


def beam_search(
    module: Module, width: int, evaluator: CostEvaluator
) -> tuple[float, list[str], int]:
    """Best (cost, passes) found by beam search of the given width; also states expanded."""
    best_cost, best_seq = evaluator(module), []
    beam: list[tuple[float, list[str], Module]] = [(best_cost, [], module)]
    seen = {hashlib.sha1(format_module(module).encode()).hexdigest()}
    expanded = 0
    for _ in range(MAX_STEPS):
        candidates: list[tuple[float, list[str], Module]] = []
        for _, seq, state in beam:
            for action in ACTIONS:
                child = apply_pass(state, action)
                key = hashlib.sha1(format_module(child).encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                expanded += 1
                cost = evaluator(child)
                candidates.append((cost, [*seq, action], child))
                if cost < best_cost - 1e-12 * max(best_cost, 1.0):
                    best_cost, best_seq = cost, [*seq, action]
        if not candidates:
            break
        candidates.sort(key=lambda c: (c[0], len(c[1])))
        beam = candidates[:width]
    return best_cost, best_seq, expanded


def run_program(job: tuple[ProgramSpec, list[int]]) -> dict[str, object]:
    program, widths = job
    evaluator = CostEvaluator("cost")
    base = build_ir(program.source, program.name)
    initial = evaluator(base)
    o2 = build_ir(program.source, program.name)
    optimize(o2, PRESETS["O2"])
    row: dict[str, object] = {
        "program": program.name,
        "origin": program.origin,
        "initial_cost": initial,
        "O2_ratio": evaluator(o2) / initial,
    }
    for width in widths:
        start = time.perf_counter()
        cost, seq, expanded = beam_search(base, width, evaluator)
        row[f"beam{width}_ratio"] = cost / initial
        row[f"beam{width}_passes"] = seq
        row[f"beam{width}_expanded"] = expanded
        row[f"beam{width}_seconds"] = time.perf_counter() - start
    return row


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(max(v, 1e-12)) for v in values) / len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", type=int, nargs="+", default=[1, 4, 16])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-test", type=int, default=None)
    parser.add_argument("--max-ood", type=int, default=None)
    parser.add_argument("--sanity", action="store_true", help="separate id, no curated output")
    args = parser.parse_args()

    config = DatasetConfig()
    run = ExperimentRun.create(
        "EXP-011-headroom" + ("-sanity" if args.sanity else ""),
        {"dataset": config.__dict__, "widths": args.widths, "max_steps": MAX_STEPS},
        seed=0,
        repo_dir=REPO,
    )
    with run:
        splits = program_splits(config)
        test = splits["test"][: args.max_test] if args.max_test else splits["test"]
        ood = splits["ood"][: args.max_ood] if args.max_ood else splits["ood"]
        programs = sorted(test + ood, key=lambda p: -len(p.source))  # long jobs first
        rows: list[dict[str, object]] = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(run_program, [(p, args.widths) for p in programs]):
                rows.append(row)
                run.save_json("rows.json", rows)  # incremental
        summary: dict[str, dict[str, float]] = {}
        for origin in ("generated", "benchmark", "example", "all"):
            items = [r for r in rows if origin in ("all", r["origin"])]
            if not items:
                continue
            entry = {
                "n": float(len(items)),
                "O2": geomean([float(str(r["O2_ratio"])) for r in items]),
            }
            for w in args.widths:
                ratios = [float(str(r[f"beam{w}_ratio"])) for r in items]
                entry[f"beam{w}"] = geomean(ratios)
                o2_better = sum(
                    1
                    for r in items
                    if float(str(r[f"beam{w}_ratio"])) > float(str(r["O2_ratio"])) + 1e-9
                )
                entry[f"beam{w}_worse_than_O2"] = float(o2_better)
            summary[origin] = entry
        run.save_json("summary.json", summary)
    run.finalize("completed", {"summary": summary})

    header = "| programs | n | O2 | " + " | ".join(f"beam-{w}" for w in args.widths) + " |"
    lines = [header, "|---|---:|---:|" + "---:|" * len(args.widths)]
    for origin, entry in summary.items():
        cells = [origin, f"{entry['n']:.0f}", f"{entry['O2']:.3f}"]
        cells += [f"{entry[f'beam{w}']:.3f}" for w in args.widths]
        lines.append("| " + " | ".join(cells) + " |")
    markdown = "\n".join(lines) + "\n"
    if not args.sanity:
        (HERE / "results.md").write_text(markdown, encoding="utf-8", newline="\n")
        (HERE / "rows.json").write_text(json.dumps(rows, indent=1) + "\n", "utf-8", newline="\n")
        (HERE / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        (HERE / "metadata.json").write_text(
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(markdown)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
