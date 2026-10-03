"""End-to-end evaluation of scheduling policies on held-out programs.

For each program and policy: run the policy from the unoptimized SSA IR, and
measure the final cost relative to the unoptimized cost (lower is better), the
number of passes applied, and the decision time. Each final program's
observable behaviour is also checked against the unoptimized program. A policy
that "wins" by producing wrong code must be caught here, not trusted.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.ml.dataset import CostEvaluator, ProgramSpec, clone_module
from forgecompile.ml.policies import Policy, schedule
from forgecompile.optimization.utils import module_instruction_count


@dataclass
class PolicyOutcome:
    program: str
    origin: str
    policy: str
    initial_cost: float
    final_cost: float
    n_passes: int
    decision_seconds: float
    schedule_seconds: float
    actions: list[str]
    initial_size: int = 0  # static IR instruction count (code-size proxy)
    final_size: int = 0

    @property
    def ratio(self) -> float:
        return self.final_cost / self.initial_cost if self.initial_cost else 1.0

    @property
    def size_ratio(self) -> float:
        return self.final_size / self.initial_size if self.initial_size else 1.0


class WrongCodeError(Exception):
    """A policy produced a program whose observable behaviour differs: a compiler bug."""


def evaluate_policies(
    programs: list[ProgramSpec],
    policies: list[Callable[[], Policy]],
    evaluator: CostEvaluator,
    max_steps: int = 12,
) -> list[PolicyOutcome]:
    outcomes: list[PolicyOutcome] = []
    for program in programs:
        base = build_ir(program.source, program.name)
        reference = run_module(base).observable
        initial = evaluator(base)
        for make_policy in policies:
            policy = make_policy()
            start = time.perf_counter()
            result = schedule(policy, clone_module(base), max_steps)
            elapsed = time.perf_counter() - start
            if run_module(result.module).observable != reference:
                raise WrongCodeError(f"{policy.name} on {program.name}: {result.actions}")
            outcomes.append(
                PolicyOutcome(
                    program.name,
                    program.origin,
                    policy.name,
                    initial,
                    evaluator(result.module),
                    len(result.actions),
                    result.decision_seconds,
                    elapsed,
                    result.actions,
                    module_instruction_count(base),
                    module_instruction_count(result.module),
                )
            )
    return outcomes


def summarize(outcomes: list[PolicyOutcome]) -> dict[str, dict[str, dict[str, float]]]:
    """{origin: {policy: {geomean_ratio, mean_passes, mean_decision_ms, worst_ratio, ...}}}."""
    groups: dict[tuple[str, str], list[PolicyOutcome]] = defaultdict(list)
    for o in outcomes:
        groups[(o.origin, o.policy)].append(o)
        groups[("all", o.policy)].append(o)
    table: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for (origin, policy), items in groups.items():
        ratios = [max(o.ratio, 1e-12) for o in items]
        table[origin][policy] = {
            "geomean_ratio": math.exp(sum(math.log(r) for r in ratios) / len(ratios)),
            "worst_ratio": max(ratios),
            "best_ratio": min(ratios),
            "geomean_size_ratio": math.exp(
                sum(math.log(max(o.size_ratio, 1e-12)) for o in items) / len(items)
            ),
            "mean_passes": sum(o.n_passes for o in items) / len(items),
            "mean_decision_ms": 1000 * sum(o.decision_seconds for o in items) / len(items),
            "mean_schedule_ms": 1000 * sum(o.schedule_seconds for o in items) / len(items),
            "n": float(len(items)),
        }
    return table


def markdown_summary(table: dict[str, dict[str, dict[str, float]]]) -> str:
    header = ["programs", "policy", "geomean cost ratio", "best", "worst", "size ratio"]
    header += ["mean passes", "decision ms", "schedule ms"]
    lines = ["| " + " | ".join(header) + " |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for origin in sorted(table):
        for policy, m in sorted(table[origin].items(), key=lambda kv: kv[1]["geomean_ratio"]):
            lines.append(
                f"| {origin} | {policy} | {m['geomean_ratio']:.3f} | {m['best_ratio']:.3f} | "
                f"{m['worst_ratio']:.3f} | {m['geomean_size_ratio']:.3f} | "
                f"{m['mean_passes']:.1f} | {m['mean_decision_ms']:.1f} | "
                f"{m['mean_schedule_ms']:.1f} |"
            )
    return "\n".join(lines) + "\n"
