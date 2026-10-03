"""EXP-010: ablations of the RL formulation (Phase 10).

Each condition trains DQN (same protocol as EXP-006: train programs, best checkpoint
on validation programs) and evaluates the greedy policy on the generated test
programs and the OOD programs. Measured: geomean final/initial interpreter cost,
geomean final/initial static size, and passes used.

Conditions (one changed factor each, relative to the EXP-006 configuration):

* ``base``: w_cost=1, w_size=0, lambda=0.002, gamma=1, all 11 passes
* ``lambda=0`` and ``lambda=0.01``: step penalty (the compile-time proxy)
* ``gamma=0.9``: discounting, which biases toward immediate gains
* ``w_size=0.5``: multi-objective reward (cost and static size)
* ``actions:O1``: only the O1 passes (constfold, copyprop, simplify, dce, simplifycfg)
* ``actions:-copyprop``: all passes but copyprop (an enabling pass, EXP-001)

References on the same programs: O2, and oracle-greedy restricted to each action
space used (an upper bound for any one-step-greedy policy in that space).

Usage::

    uv run python experiments/EXP-010-rl-ablations/run.py --episodes 2000 --seeds 0 1 --workers 14
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from forgecompile.ml.data_pipeline import DatasetConfig, program_splits
from forgecompile.ml.dataset import ACTIONS, CostEvaluator, ProgramSpec
from forgecompile.ml.evaluate import evaluate_policies, summarize
from forgecompile.ml.features import FEATURE_NAMES
from forgecompile.ml.policies import FixedPipelinePolicy, OraclePolicy, Policy
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.rl.dqn import DQNAgent, DQNConfig, DQNPolicy
from forgecompile.rl.env import STOP, RewardConfig
from forgecompile.rl.training import TrainingJob, run_training_job
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
HORIZON = 12
O1_ACTIONS = tuple(sorted(set(PRESETS["O1"])))
NO_COPYPROP = tuple(a for a in ACTIONS if a != "copyprop")


@dataclass(frozen=True)
class Condition:
    name: str
    reward: RewardConfig = field(default_factory=RewardConfig)
    gamma: float = 1.0
    actions: tuple[str, ...] = field(default_factory=lambda: tuple(ACTIONS))


CONDITIONS = [
    Condition("base"),
    Condition("lambda=0", reward=RewardConfig(step_penalty=0.0)),
    Condition("lambda=0.01", reward=RewardConfig(step_penalty=0.01)),
    Condition("gamma=0.9", gamma=0.9),
    Condition("w_size=0.5", reward=RewardConfig(w_size=0.5)),
    Condition("actions:O1", actions=O1_ACTIONS),
    Condition("actions:-copyprop", actions=NO_COPYPROP),
]


@dataclass(frozen=True)
class Task:
    kind: str  # "dqn" | "reference"
    name: str
    eval_programs: list[ProgramSpec]
    job: TrainingJob | None = None
    actions: tuple[str, ...] = ()


def run_task(task: Task) -> dict[str, object]:
    evaluator = CostEvaluator("cost")
    record: dict[str, object] = {"task": task.name, "kind": task.kind}
    policy: Policy
    if task.job is not None:
        record["training"] = run_training_job(task.job)
        actions = [*task.job.actions, STOP]
        obs_size = len(FEATURE_NAMES) + 1 + len(actions)
        agent = DQNAgent.load(task.job.checkpoint, obs_size, len(actions))
        policy = DQNPolicy(agent, HORIZON, name=task.name, actions=actions)
    elif task.name == "O2":
        policy = FixedPipelinePolicy("O2", PRESETS["O2"])
    else:
        policy = OraclePolicy(evaluator, name=task.name, actions=task.actions)
    outcomes = evaluate_policies(task.eval_programs, [lambda: policy], evaluator, HORIZON)
    record["summary"] = summarize(outcomes)
    record["outcomes"] = [
        asdict(o) | {"ratio": o.ratio, "size_ratio": o.size_ratio} for o in outcomes
    ]
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=2000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--max-val", type=int, default=40)
    parser.add_argument("--max-test", type=int, default=None)
    parser.add_argument("--max-ood", type=int, default=None)
    parser.add_argument("--only", help="comma-separated condition names (sanity runs)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sanity", action="store_true", help="separate id, no curated output")
    args = parser.parse_args()

    conditions = CONDITIONS
    if args.only:
        conditions = [c for c in CONDITIONS if c.name in args.only.split(",")]
    dataset_config = DatasetConfig()
    run = ExperimentRun.create(
        "EXP-010-rl-ablations" + ("-sanity" if args.sanity else ""),
        {
            "dataset": asdict(dataset_config),
            "episodes": args.episodes,
            "seeds": args.seeds,
            "warmup": args.warmup,
            "horizon": HORIZON,
            "max_val": args.max_val,
            "conditions": [asdict(c) for c in conditions],
        },
        seed=args.seeds[0],
        repo_dir=REPO,
    )
    with run:
        splits = program_splits(dataset_config)
        test = splits["test"][: args.max_test] if args.max_test else splits["test"]
        ood = splits["ood"][: args.max_ood] if args.max_ood else splits["ood"]
        eval_programs = test + ood
        tasks: list[Task] = []
        for cond in conditions:
            for seed in args.seeds:
                name = f"{cond.name}/seed{seed}"
                job = TrainingJob(
                    name=name,
                    train_programs=splits["train"],
                    val_programs=splits["val"][: args.max_val],
                    checkpoint=run.run_dir / f"dqn_{cond.name.replace(':', '_')}_seed{seed}.npz",
                    episodes=args.episodes,
                    dqn=replace(DQNConfig(), gamma=cond.gamma, warmup_steps=args.warmup, seed=seed),
                    reward=cond.reward,
                    horizon=HORIZON,
                    actions=cond.actions,
                )
                tasks.append(Task("dqn", name, eval_programs, job))
        tasks.append(Task("reference", "O2", eval_programs))
        for actions in dict.fromkeys(c.actions for c in conditions):
            label = "all" if actions == tuple(ACTIONS) else ",".join(actions)
            tasks.append(Task("reference", f"oracle[{label}]", eval_programs, actions=actions))

        records: list[dict[str, object]] = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_task, t) for t in tasks]
            for future in as_completed(futures):
                records.append(future.result())
                run.save_json("records.json", records)  # incremental
        records.sort(key=lambda r: str(r["task"]))
        run.save_json("records.json", records)
    run.finalize("completed", {"tasks": len(records)})

    lines = [
        "| policy | programs | geomean cost ratio | size ratio | mean passes | best val |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in records:
        summary = r["summary"]
        assert isinstance(summary, dict)
        training = r.get("training")
        best_val = training.get("best_validation") if isinstance(training, dict) else None
        for origin in ("generated", "benchmark", "example", "all"):
            m = summary.get(origin, {}).get(r["task"])
            if m is None:
                continue
            val = f"{best_val:.3f}" if isinstance(best_val, float) and origin == "all" else ""
            lines.append(
                f"| {r['task']} | {origin} | {m['geomean_ratio']:.3f} | "
                f"{m['geomean_size_ratio']:.3f} | {m['mean_passes']:.1f} | {val} |"
            )
    markdown = "\n".join(lines) + "\n"
    if not args.sanity:
        compact = [
            {k: v for k, v in r.items() if k != "outcomes"}
            | {"training": _compact_training(r.get("training"))}
            for r in records
        ]
        (HERE / "results.md").write_text(markdown, encoding="utf-8", newline="\n")
        (HERE / "records.json").write_text(
            json.dumps(compact, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
        (HERE / "metadata.json").write_text(
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(markdown)
    print(f"run directory: {run.run_dir}")


def _compact_training(training: object) -> object:
    """Drop per-episode arrays from the curated copy (they stay in the run directory)."""
    if not isinstance(training, dict):
        return training
    keep = ("name", "train_seconds", "env_steps", "validation", "best_validation")
    return {k: training[k] for k in keep if k in training} | {
        "invalid_transformations": training.get("invalid_transformations")
    }


if __name__ == "__main__":
    main()
