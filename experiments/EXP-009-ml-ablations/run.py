"""EXP-009: ablations of the supervised pass scheduler (Phase 10).

Every condition repeats the EXP-004 protocol: fit all candidate models on the
training records, select on validation regret, refit on train + val, then
report one-step decision quality (regret) *and* end-to-end schedule quality
(geomean final/initial interpreter cost of the greedy model policy, budget 12).
Test/OOD data never influence a choice.

Conditions:

* **features:** all features; all minus one group, for each of the 7 groups; and
  only the hand-engineered ``opportunities`` group (research question: is the
  model more than these detectors?).
* **data:** the first k training programs, k in {25, 50, 100, 200, 400} (in a fixed,
  seeded random order). How much data is needed?
* **distribution:** train on the ``loop_heavy`` or ``default`` generator profile,
  evaluate on both profiles' test programs and on OOD. Does the learned scheduler
  transfer? O2 and oracle-greedy are evaluated on the same programs for reference.

Usage::

    uv run python experiments/EXP-009-ml-ablations/run.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from forgecompile.ml.data_pipeline import DatasetConfig, build_dataset, program_splits
from forgecompile.ml.dataset import CostEvaluator, ProgramSpec, StateRecord
from forgecompile.ml.evaluate import evaluate_policies
from forgecompile.ml.features import FEATURE_GROUPS
from forgecompile.ml.models import score, select_model
from forgecompile.ml.policies import FixedPipelinePolicy, ModelPolicy, OraclePolicy, Policy
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MAX_STEPS = 12
PROFILES = ("loop_heavy", "default")
DATA_SIZES = (25, 50, 100, 200, 400)


@dataclass(frozen=True)
class Condition:
    family: str  # "features" | "data" | "distribution" | "reference"
    name: str
    train_profile: str = "loop_heavy"
    exclude_groups: tuple[str, ...] = ()
    n_train_programs: int | None = None
    eval_sets: tuple[str, ...] = ("loop_heavy", "ood")
    policy: str = "model"  # "model" | "O2" | "oracle"


def conditions() -> list[Condition]:
    out = [Condition("features", "all")]
    out += [Condition("features", f"-{g}", exclude_groups=(g,)) for g in FEATURE_GROUPS]
    others = tuple(g for g in FEATURE_GROUPS if g != "opportunities")
    out.append(Condition("features", "only:opportunities", exclude_groups=others))
    out += [Condition("data", f"n={k}", n_train_programs=k) for k in DATA_SIZES]
    for profile in PROFILES:
        out.append(Condition("distribution", f"train:{profile}", train_profile=profile,
                             eval_sets=(*PROFILES, "ood")))  # fmt: skip
    out += [
        Condition("reference", p, eval_sets=(*PROFILES, "ood"), policy=p) for p in ("O2", "oracle")
    ]
    return out


def dataset_config(profile: str, seed: int) -> DatasetConfig:
    return DatasetConfig(profile=profile, seed=seed)


def subsample(records: list[StateRecord], k: int, seed: int) -> list[StateRecord]:
    programs = sorted({r.program for r in records})
    random.Random(seed).shuffle(programs)
    keep = set(programs[:k])
    return [r for r in records if r.program in keep]


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(max(v, 1e-12)) for v in values) / len(values))


def run_condition(job: tuple[Condition, int]) -> dict[str, object]:
    cond, seed = job
    data = {p: build_dataset(dataset_config(p, seed), workers=1) for p in PROFILES}  # cache hits
    eval_programs: dict[str, list[ProgramSpec]] = {
        p: program_splits(dataset_config(p, seed))["test"] for p in PROFILES
    }
    eval_programs["ood"] = program_splits(dataset_config("loop_heavy", seed))["ood"]
    eval_records = {p: data[p]["test"] for p in PROFILES} | {"ood": data["loop_heavy"]["ood"]}
    evaluator = CostEvaluator("cost")
    row: dict[str, object] = {"family": cond.family, "condition": cond.name}
    make: Callable[[], Policy]

    if cond.policy == "model":
        train = data[cond.train_profile]["train"]
        if cond.n_train_programs is not None:
            train = subsample(train, cond.n_train_programs, seed)
        model, val_scores = select_model(
            train, data[cond.train_profile]["val"], seed, cond.exclude_groups
        )
        row["selected_model"] = model.name
        row["train_records"] = len(train)
        row["val_regret"] = val_scores[model.name]["mean_regret"]
        for name in cond.eval_sets:
            s = score(model, eval_records[name])
            row[f"{name}_regret"] = s["mean_regret"]
            row[f"{name}_near_optimal"] = s["near_optimal_rate"]
        make = lambda: ModelPolicy(model, name="model")  # noqa: E731
    elif cond.policy == "O2":
        make = lambda: FixedPipelinePolicy("O2", PRESETS["O2"])  # noqa: E731
    else:
        make = lambda: OraclePolicy(evaluator)  # noqa: E731

    for name in cond.eval_sets:
        outcomes = evaluate_policies(eval_programs[name], [make], evaluator, MAX_STEPS)
        row[f"{name}_e2e_ratio"] = geomean([o.ratio for o in outcomes])
        row[f"{name}_mean_passes"] = sum(o.n_passes for o in outcomes) / len(outcomes)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--only", help="comma-separated families (sanity runs)")
    parser.add_argument("--sanity", action="store_true", help="separate id, no curated output")
    args = parser.parse_args()

    todo = conditions()
    if args.only:
        todo = [c for c in todo if c.family in args.only.split(",")]
    run = ExperimentRun.create(
        "EXP-009-ml-ablations" + ("-sanity" if args.sanity else ""),
        {
            "datasets": {p: dataset_config(p, args.seed).__dict__ for p in PROFILES},
            "conditions": [c.__dict__ for c in todo],
            "max_steps": MAX_STEPS,
        },
        seed=args.seed,
        repo_dir=REPO,
    )
    with run:
        for profile in PROFILES:  # build (or load) both datasets once, in parallel
            build_dataset(dataset_config(profile, args.seed), workers=args.workers)
        rows: list[dict[str, object]] = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(run_condition, [(c, args.seed) for c in todo]):
                rows.append(row)
                run.save_json("rows.json", rows)  # incremental
    run.finalize("completed", {"conditions": len(rows)})

    columns = ["loop_heavy", "default", "ood"]
    header = "| family | condition | model | val regret | "
    header += " | ".join(f"{c} regret | {c} e2e" for c in columns) + " |"
    lines = [header, "|---|---|---|---:|" + "---:|---:|" * len(columns)]
    for r in rows:
        cells = [str(r["family"]), str(r["condition"]), str(r.get("selected_model", "-"))]
        cells.append(f"{r['val_regret']:.4f}" if "val_regret" in r else "-")
        for c in columns:
            regret, e2e = r.get(f"{c}_regret"), r.get(f"{c}_e2e_ratio")
            cells.append(f"{regret:.4f}" if isinstance(regret, float) else "-")
            cells.append(f"{e2e:.3f}" if isinstance(e2e, float) else "-")
        lines.append("| " + " | ".join(cells) + " |")
    markdown = "\n".join(lines) + "\n"
    if not args.sanity:
        (HERE / "results.md").write_text(markdown, encoding="utf-8", newline="\n")
        (HERE / "rows.json").write_text(json.dumps(rows, indent=2) + "\n", "utf-8", newline="\n")
        (HERE / "metadata.json").write_text(
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(markdown)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
