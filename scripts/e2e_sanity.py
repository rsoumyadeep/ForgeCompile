"""Tiny end-to-end sanity run of the whole ML/RL pipeline, one stage per step, with checks.

    program -> compiler (AST, IR, SSA) -> features -> dataset (oracle labels) -> ML model
    -> optimization decisions -> optimized IR -> native execution (output checked)
    -> reward (RL environment) -> DQN training step

Seconds to minutes on a laptop; fixed seed; no worker processes. Every stage asserts its
invariant, so a broken stage fails loudly here before any large experiment is launched.

Usage::

    uv run python scripts/e2e_sanity.py
"""

from __future__ import annotations

import random
import time

from forgecompile.backend.llvm_emitter import emit_module
from forgecompile.backend.native import build_and_run
from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.ml.dataset import LABELS, CostEvaluator, ProgramSpec, trajectory
from forgecompile.ml.features import FEATURE_NAMES, feature_vector
from forgecompile.ml.models import feature_columns, fit, make_models, score
from forgecompile.ml.policies import ModelPolicy, schedule
from forgecompile.rl.dqn import DQNAgent, DQNConfig, DQNPolicy, train
from forgecompile.rl.env import PassSchedulingEnv
from forgecompile.testing.program_generator import LOOP_HEAVY, generate_program

SEED = 0


def stage(name: str) -> float:
    print(f"\n== {name}")
    return time.perf_counter()


def done(start: float, detail: str) -> None:
    print(f"   ok ({time.perf_counter() - start:.1f}s) {detail}")


def main() -> None:
    random.seed(SEED)
    programs = [
        ProgramSpec(f"gen{s}", generate_program(s, LOOP_HEAVY), "generated")
        for s in range(100_000, 100_010)
    ]
    train_programs, test_programs = programs[:8], programs[8:]

    t = stage("1. compiler: source -> AST -> IR -> SSA (verified)")
    module = build_ir(test_programs[0].source, test_programs[0].name)
    reference = run_module(module)
    assert reference.trap is None
    done(
        t, f"{test_programs[0].name}: {len(module.functions)} functions, cost {reference.cost:.0f}"
    )

    t = stage("2. features")
    phi = feature_vector(module)
    assert len(phi) == len(FEATURE_NAMES) == 61
    done(
        t, f"{len(phi)} features, e.g. n_instructions={phi[FEATURE_NAMES.index('n_instructions')]}"
    )

    t = stage("3. dataset: every pass applied and executed at every state (oracle labels)")
    evaluator = CostEvaluator("cost")
    rng = random.Random(SEED)
    train_records = [r for p in train_programs for r in trajectory(p, 3, 0.3, rng, evaluator)]
    test_records = [r for p in test_programs for r in trajectory(p, 3, 0.3, rng, evaluator)]
    assert all(r.label in LABELS for r in train_records + test_records)
    done(t, f"{len(train_records)} train / {len(test_records)} test records")

    t = stage("4. ML model (random forest) and one-step decision quality")
    model = fit(
        "random_forest", make_models(SEED)["random_forest"], train_records, feature_columns()
    )
    metrics = score(model, test_records)
    assert 0.0 <= metrics["mean_regret"] <= 1.0
    done(t, f"test regret {metrics['mean_regret']:.4f}, accuracy {metrics['accuracy']:.2f}")

    t = stage("5. optimization decisions: the model schedules passes")
    result = schedule(ModelPolicy(model), build_ir(test_programs[0].source), max_steps=12)
    optimized_cost = run_module(result.module).cost
    done(t, f"passes {result.actions}; cost {reference.cost:.0f} -> {optimized_cost:.0f}")

    t = stage("6. native execution of the optimized IR (output must match)")
    _, native = build_and_run(emit_module(result.module), 0)
    assert (native.stdout, native.exit_code) == reference.observable
    done(t, "native output identical to the unoptimized interpreter run")

    t = stage("7. reward: RL environment step")
    env = PassSchedulingEnv(train_programs, horizon=12, seed=SEED)
    obs, _ = env.reset()
    assert obs.shape == (env.obs_size,) == (74,)
    _, reward, _, _, _ = env.step(env.actions.index("sccp"))
    done(t, f"obs {obs.shape}, reward after sccp {reward:+.4f}")

    t = stage("8. DQN: a few training episodes, then a greedy schedule")
    agent = DQNAgent(env.obs_size, env.n_actions, DQNConfig(warmup_steps=30, seed=SEED))
    log = train(env, agent, episodes=10)
    dqn = schedule(DQNPolicy(agent), build_ir(test_programs[0].source), max_steps=12)
    assert log.invalid_transformations == 0
    assert run_module(dqn.module).observable == reference.observable
    done(t, f"{agent.steps} env steps, 0 invalid transformations, DQN passes {dqn.actions}")

    print("\nEnd-to-end sanity run passed.")


if __name__ == "__main__":
    main()
