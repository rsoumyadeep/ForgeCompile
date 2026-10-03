"""Pass-scheduling policies: baselines, the greedy oracle, and learned policies.

A policy looks at the current module and returns the next pass to apply, or
``STOP``. :func:`schedule` runs a policy to completion under a step budget and
records how much time the *decisions* took. That decision time is the
"inference overhead" a learned scheduler must justify (research question 5).

Baselines (required by the project brief):

* :class:`FixedPipelinePolicy`: a hand-written pass list (presets O1, O2);
* :class:`RandomPolicy`: uniformly random passes for a fixed number of steps;
* *frequency*: a :class:`FixedPipelinePolicy` whose order is learned from data
  (:func:`frequency_order`), giving the passes sorted by how often each was the
  best next pass in the training set;
* :class:`OraclePolicy`: at every step, actually apply every pass and take the
  best. It is expensive, and an *upper bound* for any one-step-greedy policy,
  including the learned classifier.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from forgecompile.ir.function import Module
from forgecompile.ir.printer import format_module
from forgecompile.ml.dataset import ACTIONS, STOP, CostEvaluator, StateRecord, apply_pass
from forgecompile.ml.features import feature_vector


class Policy(Protocol):
    name: str

    def reset(self) -> None: ...

    def choose(self, module: Module) -> str: ...


@dataclass
class ScheduleResult:
    module: Module
    actions: list[str]
    decision_seconds: float


def module_hash(module: Module) -> str:
    return hashlib.sha1(format_module(module).encode()).hexdigest()


def schedule(policy: Policy, module: Module, max_steps: int = 12) -> ScheduleResult:
    """Apply the policy's choices until it says STOP or the step budget is used up."""
    policy.reset()
    actions: list[str] = []
    decision = 0.0
    for _ in range(max_steps):
        start = time.perf_counter()
        action = policy.choose(module)
        decision += time.perf_counter() - start
        if action == STOP:
            break
        module = apply_pass(module, action)
        actions.append(action)
    return ScheduleResult(module, actions, decision)


@dataclass
class FixedPipelinePolicy:
    name: str
    passes: Sequence[str]
    _position: int = 0

    def reset(self) -> None:
        self._position = 0

    def choose(self, module: Module) -> str:
        if self._position >= len(self.passes):
            return STOP
        self._position += 1
        return self.passes[self._position - 1]


@dataclass
class RandomPolicy:
    name: str
    length: int
    seed: int
    rng: random.Random = field(init=False)
    _count: int = 0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def reset(self) -> None:
        self._count = 0

    def choose(self, module: Module) -> str:
        if self._count >= self.length:
            return STOP
        self._count += 1
        return self.rng.choice(ACTIONS)


def frequency_order(records: list[StateRecord]) -> list[str]:
    """Passes ordered by how often each was the best next pass in the training records."""
    counts = Counter(r.label for r in records if r.label != STOP)
    return sorted(ACTIONS, key=lambda a: (-counts.get(a, 0), a))


@dataclass
class OraclePolicy:
    """Greedy with perfect one-step knowledge: evaluates every pass, picks the cheapest."""

    evaluator: CostEvaluator
    name: str = "oracle-greedy"
    actions: Sequence[str] = tuple(ACTIONS)  # a subset, for the action-space ablation

    def reset(self) -> None:
        pass

    def choose(self, module: Module) -> str:
        base = self.evaluator(module)
        best, best_cost = STOP, base
        for action in self.actions:
            cost = self.evaluator(apply_pass(module, action))
            if cost < best_cost - 1e-12 * max(base, 1.0):
                best, best_cost = action, cost
        return best


class ActionRanker(Protocol):
    """Anything that ranks labels (passes and STOP) for a feature vector, best first."""

    def rank(self, features: list[float]) -> list[str]: ...


@dataclass
class ModelPolicy:
    """A learned policy: follow the model's ranking, never retrying a pass in the same state.

    A pass that leaves the module unchanged keeps the state, and so the
    features, the same, and the model would predict it again forever.
    Remembering which actions were tried in each state (by IR hash) prevents
    that loop: the policy moves on to the next-ranked action, and stops when the
    model ranks STOP highest among the untried ones.
    """

    ranker: ActionRanker
    name: str = "model"
    _tried: dict[str, set[str]] = field(default_factory=dict)

    def reset(self) -> None:
        self._tried = {}

    def choose(self, module: Module) -> str:
        key = module_hash(module)
        tried = self._tried.setdefault(key, set())
        for action in self.ranker.rank(feature_vector(module)):
            if action == STOP:
                return STOP
            if action not in tried:
                tried.add(action)
                return action
        return STOP
