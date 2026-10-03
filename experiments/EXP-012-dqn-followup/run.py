"""EXP-012: DQN follow-up to EXP-006 — equal policy wrappers, then 4x more training.

EXP-006 found the DQN policies repeating no-op passes, and that the supervised
``ModelPolicy`` has a "never retry a pass in an unchanged state" rule that
``DQNPolicy`` lacked. This experiment separates the two explanations:

* **Part A (no training):** the three EXP-006 checkpoints, evaluated with and without
  the no-retry wrapper — on *all 100 validation programs first* (the decision
  metric), then once on test + OOD. O2 on the same programs for reference.
* **Part B (scaled training):** 3 seeds x 12,000 episodes (4x EXP-006), epsilon decay
  over 24,000 steps (4x), checkpoints selected on 40 validation programs *with* the
  no-retry wrapper; evaluated on test + OOD with and without the wrapper.

Everything else equals EXP-006 (reward, gamma, network, horizon, programs).

Usage::

    uv run python experiments/EXP-012-dqn-followup/run.py --part both --workers 16
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ml.data_pipeline import DatasetConfig, program_splits
from forgecompile.ml.dataset import CostEvaluator, ProgramSpec
from forgecompile.ml.evaluate import evaluate_policies, markdown_summary, summarize
from forgecompile.ml.features import FEATURE_NAMES
from forgecompile.ml.policies import FixedPipelinePolicy, Policy, schedule
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.rl.dqn import DQNAgent, DQNConfig, DQNPolicy
from forgecompile.rl.env import ENV_ACTIONS, RewardConfig
from forgecompile.rl.training import TrainingJob, run_training_job
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
HORIZON = 12
EXP006_CHECKPOINTS = REPO / "experiments" / "EXP-006-rl-scheduling" / "checkpoints"
OBS_SIZE = len(FEATURE_NAMES) + 1 + len(ENV_ACTIONS)


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(max(v, 1e-12)) for v in values) / len(values))


def load(path: Path) -> DQNAgent:
    return DQNAgent.load(path, OBS_SIZE, len(ENV_ACTIONS))


def val_score(policy: Policy, programs: list[ProgramSpec], evaluator: CostEvaluator) -> float:
    ratios = []
    for program in programs:
        module = build_ir(program.source, program.name)
        result = schedule(policy, module, HORIZON)
        ratios.append(evaluator(result.module) / evaluator(module))
    return geomean(ratios)


def dqn_policies(agents: dict[str, DQNAgent]) -> list[Callable[[], Policy]]:
    """Each agent twice: the plain argmax policy (EXP-006 protocol) and the no-retry wrapper."""
    out: list[Callable[[], Policy]] = []
    for name, agent in agents.items():
        out.append(partial(DQNPolicy, agent, HORIZON, name))
        out.append(partial(DQNPolicy, agent, HORIZON, f"{name}+noretry", no_retry=True))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=["A", "B", "both"], default="both")
    parser.add_argument("--episodes", type=int, default=12_000)
    parser.add_argument("--epsilon-decay", type=int, default=24_000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--max-val", type=int, default=40, help="val programs for checkpointing")
    parser.add_argument("--part-a-val", type=int, default=100, help="val programs for part A")
    parser.add_argument("--max-test", type=int, default=None)
    parser.add_argument("--max-ood", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sanity", action="store_true", help="separate id, no curated output")
    args = parser.parse_args()

    dataset_config = DatasetConfig()
    dqn_config = DQNConfig(epsilon_decay_steps=args.epsilon_decay)
    run = ExperimentRun.create(
        "EXP-012-dqn-followup" + ("-sanity" if args.sanity else ""),
        {
            "part": args.part,
            "dataset": asdict(dataset_config),
            "episodes": args.episodes,
            "seeds": args.seeds,
            "dqn": asdict(dqn_config),
            "reward": asdict(RewardConfig()),
            "horizon": HORIZON,
            "max_val": args.max_val,
            "exp006_checkpoints": str(EXP006_CHECKPOINTS.relative_to(REPO)),
        },
        seed=args.seeds[0],
        repo_dir=REPO,
    )
    results: dict[str, object] = {}
    with run:
        splits = program_splits(dataset_config)
        test = splits["test"][: args.max_test] if args.max_test else splits["test"]
        ood = splits["ood"][: args.max_ood] if args.max_ood else splits["ood"]
        evaluator = CostEvaluator("cost")
        o2 = FixedPipelinePolicy("O2", PRESETS["O2"])

        if args.part in ("A", "both"):
            agents = {
                f"exp006-seed{s}": load(EXP006_CHECKPOINTS / f"dqn_seed{s}.npz") for s in args.seeds
            }
            val = splits["val"][: args.part_a_val]
            validation = {"O2": val_score(o2, val, evaluator)}
            for name, agent in agents.items():
                validation[name] = val_score(DQNPolicy(agent, HORIZON), val, evaluator)
                validation[f"{name}+noretry"] = val_score(
                    DQNPolicy(agent, HORIZON, no_retry=True), val, evaluator
                )
            outcomes = evaluate_policies(
                test + ood, [lambda: o2, *dqn_policies(agents)], evaluator, HORIZON
            )
            results["A"] = {"validation": validation, "test": summarize(outcomes)}
            run.save_json("results.json", results)

        if args.part in ("B", "both"):
            jobs = [
                TrainingJob(
                    name=f"scaled-seed{seed}",
                    train_programs=splits["train"],
                    val_programs=splits["val"][: args.max_val],
                    checkpoint=run.run_dir / f"dqn_scaled_seed{seed}.npz",
                    episodes=args.episodes,
                    dqn=replace(dqn_config, seed=seed),
                    horizon=HORIZON,
                    no_retry=True,
                )
                for seed in args.seeds
            ]
            training: dict[str, object] = {}
            with ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as pool:
                futures = {pool.submit(run_training_job, job): job.name for job in jobs}
                for future in as_completed(futures):
                    training[futures[future]] = future.result()
                    run.save_json("training.json", training)
            agents = {job.name: load(job.checkpoint) for job in jobs}
            outcomes = evaluate_policies(
                test + ood, [lambda: o2, *dqn_policies(agents)], evaluator, HORIZON
            )
            results["B"] = {
                "test": summarize(outcomes),
                "training_summary": {
                    name: {
                        k: t[k]
                        for k in (
                            "train_seconds",
                            "env_steps",
                            "best_validation",
                            "invalid_transformations",
                        )
                    }
                    for name, t in training.items()
                    if isinstance(t, dict)
                },
            }
            run.save_json("results.json", results)
            run.save_json("training.json", training)
    run.finalize("completed", {"parts": list(results)})

    markdown = ""
    if "A" in results:
        a = results["A"]
        assert isinstance(a, dict)
        markdown += "## Part A: EXP-006 checkpoints, with and without the no-retry wrapper\n\n"
        markdown += "Validation (geomean cost ratio):\n\n"
        markdown += "\n".join(f"- {k}: {v:.4f}" for k, v in a["validation"].items())
        markdown += "\n\nTest + OOD:\n\n" + markdown_summary(a["test"])
    if "B" in results:
        b = results["B"]
        assert isinstance(b, dict)
        markdown += "\n## Part B: scaled training (no-retry validation)\n\n"
        markdown += "```\n" + json.dumps(b["training_summary"], indent=1) + "\n```\n\n"
        markdown += markdown_summary(b["test"])
    if not args.sanity:
        (HERE / "results.md").write_text(markdown, encoding="utf-8", newline="\n")
        (HERE / "results.json").write_text(
            json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        (HERE / "metadata.json").write_text(
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if "B" in results:
            checkpoints = HERE / "checkpoints"
            checkpoints.mkdir(exist_ok=True)
            for seed in args.seeds:
                for suffix in (".npz", ".json"):
                    name = f"dqn_scaled_seed{seed}{suffix}"
                    (checkpoints / name).write_bytes((run.run_dir / name).read_bytes())
    print(markdown)
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
