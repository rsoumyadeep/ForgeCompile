"""Validate the ML/RL training-data generator on a real dataset before any model is trained.

Checks (each one is a hard failure; the run is marked failed and keeps its directory):

1. **Determinism:** the dataset built with 1 worker and with ``--workers`` workers is
   identical, record by record. Program seeds must not depend on scheduling.
2. **Split hygiene:** program names *and* program sources are disjoint across
   train/val/test/ood (no near-duplicate leakage by identical text). Every record
   carries the origin of its split.
3. **Program validity:** every program lowers, verifies, runs in the reference IR
   interpreter without a trap. Programs that print nothing are legal (deleting
   their dead work is a correct optimization) but are counted and reported.
4. **Record invariants:** 61 finite, non-negative features; an outcome for every
   pass; positive costs; contiguous steps; ``initial_cost`` equals the step-0 cost;
   each next state's cost equals the previous state's outcome for the action taken;
   the label follows the argmin rule; a trajectory ends with STOP or at the budget.
5. **Replay:** for a sample of programs, replay the recorded actions from scratch with
   a fresh cost evaluator and recompute features and the complete outcome table.
   They must match exactly. Labels are therefore reproducible facts, not artefacts.
6. **Semantics on the trajectory:** every replayed state (and every one-step outcome)
   has the same observable output as the unoptimized program.

Usage::

    uv run python scripts/validate_dataset.py --n-train 40 --n-val 10 --n-test 10 --workers 3
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.ml.data_pipeline import SPLITS, DatasetConfig, build_dataset, program_splits
from forgecompile.ml.dataset import (
    ACTIONS,
    IMPROVEMENT_EPSILON,
    STOP,
    CostEvaluator,
    StateRecord,
    apply_pass,
    record_to_json,
)
from forgecompile.ml.features import FEATURE_NAMES, feature_vector
from forgecompile.utils.experiment import ExperimentRun

REPO = Path(__file__).resolve().parents[1]
ORIGIN_OF_SPLIT = {"train": "generated", "val": "generated", "test": "generated"}


class ValidationError(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def build(config: DatasetConfig, workers: int) -> dict[str, list[StateRecord]]:
    with tempfile.TemporaryDirectory() as tmp:  # never reuse a cache: build from scratch
        return build_dataset(config, workers=workers, cache_dir=Path(tmp))


def canonical(data: dict[str, list[StateRecord]]) -> str:
    payload = {s: [record_to_json(r) for r in data[s]] for s in SPLITS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def check_records(data: dict[str, list[StateRecord]], steps: int) -> dict[str, object]:
    by_program: dict[str, list[StateRecord]] = defaultdict(list)
    for split, records in data.items():
        for r in records:
            if split in ORIGIN_OF_SPLIT:
                check(r.origin == ORIGIN_OF_SPLIT[split], f"{r.program}: origin {r.origin}")
            else:
                check(r.origin in ("benchmark", "example"), f"{r.program}: origin {r.origin}")
            check(len(r.features) == len(FEATURE_NAMES), f"{r.program}: feature length")
            check(all(math.isfinite(x) and x >= 0 for x in r.features), f"{r.program}: features")
            check(set(r.outcomes) == set(ACTIONS), f"{r.program}: outcome table incomplete")
            check(r.cost > 0 and all(c > 0 for c in r.outcomes.values()), f"{r.program}: cost")
            best = min(ACTIONS, key=lambda a: (r.outcomes[a], a))
            gain = (r.cost - r.outcomes[best]) / r.cost
            check(r.label == (best if gain > IMPROVEMENT_EPSILON else STOP), f"{r.program}: label")
            by_program[f"{split}/{r.program}"].append(r)
    lengths = []
    for key, records in by_program.items():
        check([r.step for r in records] == list(range(len(records))), f"{key}: steps")
        check(records[0].cost == records[0].initial_cost, f"{key}: initial cost")
        check(all(r.initial_cost == records[0].initial_cost for r in records), f"{key}: c0")
        for prev, nxt in itertools.pairwise(records):
            check(prev.taken in ACTIONS, f"{key}: non-final record took {prev.taken}")
            check(nxt.cost == prev.outcomes[prev.taken], f"{key}: chain broken at {prev.step}")
        last = records[-1]
        check(last.taken == STOP or len(records) == steps, f"{key}: trajectory ends early")
        check(last.taken != STOP or last.label == STOP, f"{key}: STOP taken with a gain")
        lengths.append(len(records))
    return {
        "programs": len(by_program),
        "mean_trajectory_length": sum(lengths) / len(lengths),
        "trajectories_ending_in_stop": sum(1 for rs in by_program.values() if rs[-1].taken == STOP),
    }


def replay(
    data: dict[str, list[StateRecord]], sources: dict[str, str], sample: int, seed: int
) -> dict[str, int]:
    """Recompute features, outcome tables and observable behaviour along recorded trajectories."""
    rng = random.Random(seed)
    by_program: dict[str, list[StateRecord]] = defaultdict(list)
    for records in data.values():
        for r in records:
            by_program[r.program].append(r)
    chosen = rng.sample(sorted(by_program), min(sample, len(by_program)))
    evaluator = CostEvaluator("cost")
    states = outcomes_checked = 0
    for name in chosen:
        module = build_ir(sources[name], name)
        reference = run_module(module).observable
        for record in by_program[name]:
            check(feature_vector(module) == record.features, f"{name}@{record.step}: features")
            check(evaluator(module) == record.cost, f"{name}@{record.step}: cost")
            successors = {a: apply_pass(module, a) for a in ACTIONS}
            for action, successor in successors.items():
                check(
                    evaluator(successor) == record.outcomes[action],
                    f"{name}@{record.step}: outcome of {action}",
                )
                check(
                    run_module(successor).observable == reference,
                    f"{name}@{record.step}: {action} changed observable behaviour",
                )
                outcomes_checked += 1
            states += 1
            if record.taken == STOP:
                break
            module = successors[record.taken]
    return {"programs": len(chosen), "states": states, "outcomes": outcomes_checked}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-train", type=int, default=40)
    parser.add_argument("--n-val", type=int, default=10)
    parser.add_argument("--n-test", type=int, default=10)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--replay", type=int, default=12, help="programs to replay from scratch")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    config = DatasetConfig(
        n_train=args.n_train, n_val=args.n_val, n_test=args.n_test, steps=args.steps, seed=args.seed
    )
    run = ExperimentRun.create(
        "EXP-007-dataset-validation",
        {"dataset": config.__dict__, "workers": args.workers, "replay": args.replay},
        seed=args.seed,
        repo_dir=REPO,
    )
    with run:
        report: dict[str, object] = {}
        # 2 + 3: split hygiene and program validity (on the program specs themselves).
        splits = program_splits(config)
        names: dict[str, str] = {}
        source_hashes: dict[str, str] = {}
        sources: dict[str, str] = {}
        program_stats: dict[str, list[float]] = defaultdict(list)
        silent = 0
        for split, programs in splits.items():
            for p in programs:
                check(p.name not in names, f"{p.name} in both {names.get(p.name)} and {split}")
                digest = hashlib.sha256(p.source.encode()).hexdigest()
                check(digest not in source_hashes, f"{p.name}: same source in another split")
                names[p.name], source_hashes[digest], sources[p.name] = split, split, p.source
                result = run_module(build_ir(p.source, p.name))
                check(result.trap is None, f"{p.name}: traps ({result.trap})")
                silent += not result.stdout.strip()
                program_stats[split].append(result.cost)
        report["programs_per_split"] = {s: len(ps) for s, ps in splits.items()}
        report["programs_without_output"] = silent
        report["median_initial_cost"] = {
            s: sorted(costs)[len(costs) // 2] for s, costs in program_stats.items()
        }

        # 1: determinism across worker counts.
        start = time.perf_counter()
        serial = build(config, workers=1)
        serial_seconds = time.perf_counter() - start
        start = time.perf_counter()
        parallel = build(config, workers=args.workers)
        parallel_seconds = time.perf_counter() - start
        check(canonical(serial) == canonical(parallel), "dataset depends on the worker count")
        report["determinism"] = {
            "sha256": canonical(serial),
            "build_seconds": {"1": serial_seconds, str(args.workers): parallel_seconds},
        }

        # 4: record invariants.
        report["records"] = {s: len(rs) for s, rs in serial.items()}
        report["trajectories"] = check_records(serial, config.steps)
        report["label_counts"] = {
            s: dict(Counter(r.label for r in rs).most_common()) for s, rs in serial.items()
        }

        # 5 + 6: replay from scratch, with semantic checks.
        report["replay"] = replay(serial, sources, args.replay, args.seed)
        run.save_json("report.json", report)
    run.finalize("completed", {"sha256": canonical(serial), "replay": report["replay"]})
    print(json.dumps(report, indent=2))
    print(f"run directory: {run.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
