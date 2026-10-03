"""EXP-005: does ML-guided pass scheduling beat fixed pipelines and simple baselines?

Policies, evaluated end-to-end on held-out programs (generated test split and
the hand-written OOD programs), each with a budget of 12 passes:

* ``O1``, ``O2``: the fixed presets;
* ``random-k12-s{0,1,2}``: 12 uniformly random passes (3 seeds);
* ``frequency``: passes in order of how often each was the best next pass in train;
* ``model``: the classifier selected in EXP-004 (same data, same selection rule);
* ``oracle-greedy``: evaluates every pass at every step. An upper bound for any
  one-step-greedy policy, and expensive.

Every final program's output is checked against the unoptimized program.

Usage::

    uv run python experiments/EXP-005-ml-scheduling/run.py --workers 4
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from forgecompile.ml.data_pipeline import DatasetConfig, build_dataset, program_splits
from forgecompile.ml.dataset import CostEvaluator
from forgecompile.ml.evaluate import evaluate_policies, markdown_summary, summarize
from forgecompile.ml.models import select_model
from forgecompile.ml.policies import (
    FixedPipelinePolicy,
    ModelPolicy,
    OraclePolicy,
    RandomPolicy,
    frequency_order,
)
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MAX_STEPS = 12


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-train", type=int, default=400)
    parser.add_argument("--n-val", type=int, default=100)
    parser.add_argument("--n-test", type=int, default=100)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument(
        "--max-ood", type=int, default=None, help="limit OOD programs (sanity runs)"
    )
    parser.add_argument(
        "--sanity",
        action="store_true",
        help="tiny run under a separate '-sanity' experiment id; never writes curated results",
    )
    args = parser.parse_args()

    config = DatasetConfig(
        n_train=args.n_train, n_val=args.n_val, n_test=args.n_test, steps=args.steps, seed=args.seed
    )
    run = ExperimentRun.create(
        "EXP-005-ml-scheduling" + ("-sanity" if args.sanity else ""),
        {"dataset": config.__dict__, "max_steps": MAX_STEPS},
        seed=args.seed,
        repo_dir=REPO,
    )
    try:
        data = build_dataset(config, workers=args.workers)
        model, _ = select_model(data["train"], data["val"], args.seed)
        order = frequency_order(data["train"])
        evaluator = CostEvaluator(config.metric)

        policies = [
            lambda: FixedPipelinePolicy("O1", PRESETS["O1"]),
            lambda: FixedPipelinePolicy("O2", PRESETS["O2"]),
            *[(lambda s=s: RandomPolicy(f"random-k12-s{s}", MAX_STEPS, s)) for s in range(3)],
            lambda: FixedPipelinePolicy("frequency", order),
            lambda: ModelPolicy(model, name=f"model:{model.name}"),
            lambda: OraclePolicy(evaluator),
        ]
        splits = program_splits(config)
        ood = splits["ood"] if args.max_ood is None else splits["ood"][: args.max_ood]
        outcomes = evaluate_policies(splits["test"] + ood, policies, evaluator, MAX_STEPS)
        table = summarize(outcomes)
        run.save_json(
            "outcomes.json",
            [asdict(o) | {"ratio": o.ratio, "size_ratio": o.size_ratio} for o in outcomes],
        )
        run.save_json("summary.json", table)
    except BaseException as exc:  # preserve the run directory, marked failed, with the cause
        run.finalize("failed", {"error": repr(exc)})
        raise
    run.finalize("completed", {"model": model.name, "frequency_order": order})

    markdown = markdown_summary(table)
    markdown += f"\nModel: {model.name}. Frequency order: {', '.join(order)}.\n"
    if not args.sanity:  # curated copies only for real runs
        write(HERE / "results.md", markdown)
        write(HERE / "summary.json", json.dumps(table, indent=2, sort_keys=True) + "\n")
        write(
            HERE / "metadata.json",
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
        )
    print(markdown)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
