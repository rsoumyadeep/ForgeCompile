"""One self-contained DQN training job, the unit that experiments run in parallel processes.

A job owns its own cost cache and environment, trains for a fixed number of
episodes, validates the greedy policy every ``validate_every`` episodes on the
validation programs (geomean final/initial cost; lower is better), and keeps
the best validation checkpoint. Test programs are never seen here.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ml.dataset import ACTIONS, CostEvaluator, ProgramSpec
from forgecompile.ml.policies import schedule
from forgecompile.rl.dqn import DQNAgent, DQNConfig, DQNPolicy, train
from forgecompile.rl.env import PassSchedulingEnv, RewardConfig


@dataclass(frozen=True)
class TrainingJob:
    name: str
    train_programs: list[ProgramSpec]
    val_programs: list[ProgramSpec]
    checkpoint: Path
    episodes: int
    dqn: DQNConfig = field(default_factory=DQNConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    horizon: int = 12
    validate_every: int = 100
    actions: tuple[str, ...] = field(default_factory=lambda: tuple(ACTIONS))


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(max(v, 1e-12)) for v in values) / len(values))


def run_training_job(job: TrainingJob) -> dict[str, object]:
    """Train; save the best-validation checkpoint to ``job.checkpoint``; return the training log."""
    evaluator = CostEvaluator("cost")
    env = PassSchedulingEnv(
        job.train_programs,
        job.horizon,
        job.reward,
        evaluator,
        seed=job.dqn.seed,
        actions=list(job.actions),
    )
    agent = DQNAgent(env.obs_size, env.n_actions, job.dqn)

    def validate(candidate: DQNAgent) -> float:
        ratios = []
        for program in job.val_programs:
            module = build_ir(program.source, program.name)
            policy = DQNPolicy(candidate, job.horizon, actions=env.actions)
            result = schedule(policy, module, job.horizon)
            ratios.append(evaluator(result.module) / evaluator(module))
        return geomean(ratios)

    start = time.perf_counter()
    log = train(env, agent, job.episodes, validate, job.validate_every, job.checkpoint)
    seconds = time.perf_counter() - start
    if not job.checkpoint.exists():  # too few episodes to validate even once
        agent.save(job.checkpoint)
    return {
        "name": job.name,
        "train_seconds": seconds,
        "env_steps": agent.steps,
        "episode_returns": log.episode_returns,
        "episode_ratios": log.episode_ratios,
        "epsilons": log.epsilons,
        "loss_every_100": log.losses[::100],
        "validation": log.validation,
        "best_validation": min((v for _, v in log.validation), default=None),
        "invalid_transformations": log.invalid_transformations,
        "cache_size": len(evaluator.cache),
    }
