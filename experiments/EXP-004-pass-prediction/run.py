"""EXP-004: can a model predict the best next optimization pass from static IR features?

1. Build the dataset (``ml/data_pipeline.py``): generated LOOP_HEAVY programs split
   train/val/test by program, plus hand-written programs as an out-of-distribution
   (OOD) split. Labels come from applying every pass and measuring the cost.
2. Fit all candidate models on train; select by validation regret.
3. Refit the selected model on train + val; score it once on test and once on OOD.
4. Report the label distribution and a (biased but cheap) random-forest impurity
   importance per feature group.

Usage::

    uv run python experiments/EXP-004-pass-prediction/run.py --workers 4
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from forgecompile.ml.data_pipeline import DatasetConfig, build_dataset
from forgecompile.ml.dataset import LABELS
from forgecompile.ml.features import FEATURE_GROUPS, FEATURE_NAMES
from forgecompile.ml.models import feature_columns, fit, make_models, score, select_model
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


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
        "--sanity",
        action="store_true",
        help="tiny run under a separate '-sanity' experiment id; never writes curated results",
    )
    args = parser.parse_args()

    config = DatasetConfig(
        n_train=args.n_train, n_val=args.n_val, n_test=args.n_test, steps=args.steps, seed=args.seed
    )
    run = ExperimentRun.create(
        "EXP-004-pass-prediction" + ("-sanity" if args.sanity else ""),
        {"dataset": config.__dict__},
        seed=args.seed,
        repo_dir=REPO,
    )
    with run:  # an exception marks the run failed, preserving its directory
        start = time.perf_counter()
        data = build_dataset(config, workers=args.workers)
        build_seconds = time.perf_counter() - start

        label_counts = {
            split: dict(Counter(r.label for r in records)) for split, records in data.items()
        }
        model, val_scores = select_model(data["train"], data["val"], args.seed)
        test_scores = score(model, data["test"])
        ood_scores = score(model, data["ood"])
        majority = fit(
            "majority", make_models(args.seed)["majority"], data["train"], feature_columns()
        )
        baseline = {"test": score(majority, data["test"]), "ood": score(majority, data["ood"])}

        forest = fit(
            "random_forest",
            make_models(args.seed)["random_forest"],
            data["train"],
            feature_columns(),
        )
        importances = dict(zip(FEATURE_NAMES, forest.estimator.feature_importances_, strict=True))
        group_importance = {
            g: float(sum(importances[n] for n in names)) for g, names in FEATURE_GROUPS.items()
        }

        results = {
            "dataset_build_seconds": build_seconds,
            "records": {split: len(records) for split, records in data.items()},
            "programs": {
                split: len({r.program for r in records}) for split, records in data.items()
            },
            "label_counts": label_counts,
            "validation_scores": val_scores,
            "selected_model": model.name,
            "test_scores": test_scores,
            "ood_scores": ood_scores,
            "majority_baseline": baseline,
            "rf_group_importance": group_importance,
        }
        run.save_json("results.json", results)
    run.finalize("completed", {"selected": model.name, "test": test_scores, "ood": ood_scores})

    lines = [
        "| model | val accuracy | val top-2 | val mean regret | val near-optimal |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, s in sorted(val_scores.items(), key=lambda kv: kv[1]["mean_regret"]):
        lines.append(
            f"| {name} | {s['accuracy']:.3f} | {s['top2_accuracy']:.3f} | {s['mean_regret']:.4f} | "
            f"{s['near_optimal_rate']:.3f} |"
        )
    lines += ["", f"Selected: **{model.name}** (refit on train+val).", ""]
    lines += [
        "| split | model | accuracy | top-2 | mean regret | near-optimal | n |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for split, s, b in (
        ("test", test_scores, baseline["test"]),
        ("ood", ood_scores, baseline["ood"]),
    ):
        for name, m in ((model.name, s), ("majority", b)):
            lines.append(
                f"| {split} | {name} | {m['accuracy']:.3f} | {m['top2_accuracy']:.3f} | "
                f"{m['mean_regret']:.4f} | {m['near_optimal_rate']:.3f} | {m['n']:.0f} |"
            )
    lines += [
        "",
        "Label distribution (train): " + json.dumps(label_counts["train"], sort_keys=True),
    ]
    lines += [
        "",
        "Random-forest impurity importance by feature group: "
        + ", ".join(
            f"{g}={v:.2f}" for g, v in sorted(group_importance.items(), key=lambda kv: -kv[1])
        ),
    ]
    table = "\n".join(lines) + "\n"
    if not args.sanity:  # curated copies only for real runs
        write(HERE / "results.md", table)
        write(HERE / "results.json", json.dumps(results, indent=2, sort_keys=True) + "\n")
        write(
            HERE / "metadata.json",
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
        )
    print(table)
    print(f"labels: {LABELS}")
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
