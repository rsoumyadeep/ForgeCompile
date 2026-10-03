"""EXP-006: does a Double-DQN agent learn a better pass schedule than greedy and fixed baselines?

Protocol:
1. Same programs and splits as EXP-004/005 (``ml/data_pipeline.py``).
2. For each seed: train DQN on the *train* programs in ``PassSchedulingEnv``.
   Every ``--validate-every`` episodes, run the greedy policy on the *val*
   programs. The checkpoint with the best validation geomean cost ratio is kept.
3. Evaluate each seed's best checkpoint on the *test* (generated) and *ood*
   (hand-written) programs, next to O2, the supervised model (EXP-004 selection
   rule) and the greedy oracle, using ``ml/evaluate.py`` (outputs checked).

Recorded per seed: training configuration, episode returns, episode cost
ratios, epsilon, losses, the validation curve, and invalid transformations.

Usage::

    uv run python experiments/EXP-006-rl-scheduling/run.py --episodes 3000 --seeds 0 1 2
    uv run python experiments/EXP-006-rl-scheduling/run.py --sanity --episodes 60 --seeds 0
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ml.data_pipeline import DatasetConfig, build_dataset, program_splits
from forgecompile.ml.dataset import CostEvaluator, ProgramSpec
from forgecompile.ml.evaluate import evaluate_policies, markdown_summary, summarize
from forgecompile.ml.models import select_model
from forgecompile.ml.policies import (
    FixedPipelinePolicy,
    ModelPolicy,
    OraclePolicy,
    Policy,
    schedule,
)
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.rl.dqn import DQNAgent, DQNConfig, DQNPolicy, train
from forgecompile.rl.env import PassSchedulingEnv, RewardConfig
from forgecompile.utils.experiment import ExperimentRun

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
HORIZON = 12


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(max(v, 1e-12)) for v in values) / len(values))


@dataclass(frozen=True)
class SeedJob:
    seed: int
    train_programs: list[ProgramSpec]
    val_programs: list[ProgramSpec]
    reward: RewardConfig
    args: argparse.Namespace
    run_dir: Path


def train_seed(job: SeedJob) -> tuple[int, dict[str, object]]:
    """Train one seed in its own process (own cost cache); keep the best validation checkpoint."""
    args = job.args
    evaluator = CostEvaluator("cost")
    env = PassSchedulingEnv(job.train_programs, HORIZON, job.reward, evaluator, seed=job.seed)
    config = DQNConfig(gamma=args.gamma, warmup_steps=args.warmup, seed=job.seed)
    agent = DQNAgent(env.obs_size, env.n_actions, config)
    checkpoint = job.run_dir / f"dqn_seed{job.seed}.npz"

    def validate(candidate: DQNAgent) -> float:
        ratios = []
        for program in job.val_programs:
            module = build_ir(program.source, program.name)
            result = schedule(DQNPolicy(candidate, HORIZON), module, HORIZON)
            ratios.append(evaluator(result.module) / evaluator(module))
        return geomean(ratios)

    start = time.perf_counter()
    log = train(env, agent, args.episodes, validate, args.validate_every, checkpoint)
    seconds = time.perf_counter() - start
    if not checkpoint.exists():  # too few episodes to validate even once
        agent.save(checkpoint)
    return job.seed, {
        "train_seconds": seconds,
        "env_steps": agent.steps,
        "episode_returns": log.episode_returns,
        "episode_ratios": log.episode_ratios,
        "epsilons": log.epsilons,
        "loss_every_100": log.losses[::100],
        "validation": log.validation,
        "invalid_transformations": log.invalid_transformations,
        "cache_size": len(evaluator.cache),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=3000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--validate-every", type=int, default=100)
    parser.add_argument(
        "--max-val", type=int, default=40, help="val programs used for checkpointing"
    )
    parser.add_argument("--max-ood", type=int, default=None)
    parser.add_argument("--step-penalty", type=float, default=0.002)
    parser.add_argument("--gamma", type=float, default=1.0)
    parser.add_argument("--warmup", type=int, default=500, help="random steps before learning")
    parser.add_argument("--n-train", type=int, default=400)
    parser.add_argument("--n-test", type=int, default=100)
    parser.add_argument(
        "--workers", type=int, default=4, help="dataset workers (supervised baseline)"
    )
    parser.add_argument(
        "--seed-workers", type=int, default=3, help="seeds trained in parallel processes"
    )
    parser.add_argument(
        "--sanity", action="store_true", help="tiny run; separate id, no curated output"
    )
    args = parser.parse_args()

    dataset_config = DatasetConfig(n_train=args.n_train, n_test=args.n_test)
    reward = RewardConfig(step_penalty=args.step_penalty)
    run = ExperimentRun.create(
        "EXP-006-rl-scheduling" + ("-sanity" if args.sanity else ""),
        {
            "dataset": asdict(dataset_config),
            "episodes": args.episodes,
            "seeds": args.seeds,
            "reward": asdict(reward),
            "dqn": asdict(DQNConfig(gamma=args.gamma, warmup_steps=args.warmup)),
            "horizon": HORIZON,
            "validate_every": args.validate_every,
            "max_val": args.max_val,
            "seed_workers": args.seed_workers,
        },
        seed=args.seeds[0],
        repo_dir=REPO,
    )
    with run:  # an exception marks the run failed, preserving its directory
        splits = program_splits(dataset_config)
        training: dict[str, dict[str, object]] = {}
        # Seeds are independent: train them in parallel processes (bounded by --seed-workers).
        jobs = [
            SeedJob(seed, splits["train"], splits["val"][: args.max_val], reward, args, run.run_dir)
            for seed in args.seeds
        ]
        with ProcessPoolExecutor(max_workers=min(args.seed_workers, len(jobs))) as pool:
            futures = [pool.submit(train_seed, job) for job in jobs]
            for future in as_completed(futures):
                seed, record = future.result()
                training[str(seed)] = record
                run.save_json("training.json", training)  # incremental: survives a later crash
        evaluator = CostEvaluator("cost")
        env_shape = PassSchedulingEnv(splits["train"][:1], HORIZON, reward, evaluator)
        agents = {
            seed: DQNAgent.load(
                run.run_dir / f"dqn_seed{seed}.npz", env_shape.obs_size, env_shape.n_actions
            )
            for seed in args.seeds
        }

        data = build_dataset(dataset_config, workers=args.workers)
        model, _ = select_model(data["train"], data["val"], seed=0)
        policies: list[Callable[[], Policy]] = [
            lambda: FixedPipelinePolicy("O2", PRESETS["O2"]),
            lambda: ModelPolicy(model, name=f"model:{model.name}"),
            lambda: OraclePolicy(evaluator),
            *[(lambda s=s: DQNPolicy(agents[s], HORIZON, name=f"dqn-seed{s}")) for s in args.seeds],
        ]
        ood = splits["ood"] if args.max_ood is None else splits["ood"][: args.max_ood]
        outcomes = evaluate_policies(splits["test"] + ood, policies, evaluator, HORIZON)
        table = summarize(outcomes)
        run.save_json("outcomes.json", [asdict(o) | {"ratio": o.ratio} for o in outcomes])
        run.save_json("summary.json", table)
    invalid = {s: training[str(s)]["invalid_transformations"] for s in args.seeds}
    run.finalize("completed", {"invalid_transformations": invalid})

    markdown = markdown_summary(table)
    if not args.sanity:  # curated copies only for real runs
        write(HERE / "results.md", markdown)
        write(HERE / "summary.json", json.dumps(table, indent=2, sort_keys=True) + "\n")
        write(HERE / "training.json", json.dumps(training, sort_keys=True) + "\n")
        checkpoints = HERE / "checkpoints"  # small (~0.2 MB each); EXP-008 loads them
        checkpoints.mkdir(exist_ok=True)
        for seed in args.seeds:
            for suffix in (".npz", ".json"):
                name = f"dqn_seed{seed}{suffix}"
                shutil.copyfile(run.run_dir / name, checkpoints / name)
        write(
            HERE / "metadata.json",
            json.dumps(run.metadata, indent=2, sort_keys=True, default=str) + "\n",
        )
    print(markdown)
    print(f"invalid transformations per seed: {invalid}")
    print(f"run directory: {run.run_dir}")


if __name__ == "__main__":
    main()
