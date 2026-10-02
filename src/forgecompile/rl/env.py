"""Pass scheduling as a Markov decision process: a Gym-style environment (no gym dependency).

MDP (full derivation in docs/RL_FORMULATION.md):

* **State** ``s_t``: the current IR module ``M_t`` and the step ``t``. The agent
  *observes* ``o_t = [phi(M_t), (T - t) / T, onehot(a_{t-1})]``: static IR
  features (``ml/features.py``), the remaining-step fraction, and the previous
  action. The features are a lossy summary of ``M_t``, so strictly this is a
  POMDP. The step counter makes the finite-horizon problem Markov in time.
* **Actions** ``A``: the 11 passes plus ``stop``.
* **Transition** ``P``: deterministic, ``M_{t+1} = pass_a(M_t)``. ``stop`` ends the
  episode. The only randomness is the initial program, drawn from the
  training set at ``reset``.
* **Reward**::

      r_t = w_cost * (C(M_t) - C(M_{t+1})) / C(M_0)
          + w_size * (S(M_t) - S(M_{t+1})) / S(M_0)
          - step_penalty                       (charged for every pass applied)

  ``C`` is the IR-interpreter cost (validated against native time in EXP-002),
  and ``S`` is the static instruction count. Summed over an episode, the
  improvement terms *telescope* to the total relative improvement. Cycling
  through states therefore gains nothing, and an optimal policy simply maximizes
  final improvement minus the compile-time penalty.
* **Termination:** ``stop``, the horizon ``T``, or an invalid transformation
  (the IR fails verification or the observable output changes). An invalid
  transformation gets ``invalid_penalty`` and is counted. Since every pass is
  correct, the expected count is zero, and the check guards against compiler
  bugs being "learned" as wins.

Costs are memoized by IR hash, shared across episodes (``CostEvaluator``).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from forgecompile.driver import build_ir
from forgecompile.ir.function import Module
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.printer import format_module
from forgecompile.ml.dataset import (
    ACTIONS,
    STOP,
    CostEvaluator,
    ProgramSpec,
    apply_pass,
    clone_module,
)
from forgecompile.ml.features import FEATURE_NAMES, feature_vector
from forgecompile.optimization.utils import module_instruction_count

ENV_ACTIONS: list[str] = [*ACTIONS, STOP]
STOP_INDEX = len(ENV_ACTIONS) - 1


@dataclass(frozen=True)
class RewardConfig:
    w_cost: float = 1.0
    w_size: float = 0.0
    step_penalty: float = 0.002  # per applied pass: a proxy for compile time
    invalid_penalty: float = 1.0


@dataclass
class EpisodeStats:
    program: str = ""
    initial_cost: float = 0.0
    final_cost: float = 0.0
    passes: list[str] = field(default_factory=list)
    total_reward: float = 0.0
    invalid: bool = False


class PassSchedulingEnv:
    """Gym-style API.

    ``reset() -> (obs, info)`` and ``step(action) -> (obs, reward, terminated, truncated, info)``.
    """

    def __init__(
        self,
        programs: list[ProgramSpec],
        horizon: int = 12,
        reward: RewardConfig | None = None,
        evaluator: CostEvaluator | None = None,
        check_output: bool = True,
        seed: int = 0,
    ) -> None:
        if not programs:
            raise ValueError("the environment needs at least one program")
        self.programs = programs
        self.horizon = horizon
        self.reward_config = reward or RewardConfig()
        self.evaluator = evaluator or CostEvaluator("cost")
        self.check_output = check_output
        self.rng = random.Random(seed)
        self.n_actions = len(ENV_ACTIONS)
        self.obs_size = len(FEATURE_NAMES) + 1 + self.n_actions
        self.invalid_transformations = 0
        self._base_modules: dict[str, tuple[Module, tuple[str, int]]] = {}
        self._observable_cache: dict[str, tuple[str, int]] = {}  # IR hash -> (stdout, status)
        self._module: Module | None = None

    # ------------------------------------------------------------------ helpers

    def _observe(self) -> np.ndarray:
        assert self._module is not None
        last = np.zeros(self.n_actions)
        if self._last_action is not None:
            last[self._last_action] = 1.0
        remaining = (self.horizon - self._t) / self.horizon
        return np.concatenate([np.array(feature_vector(self._module)), [remaining], last])

    def load_program(self, program: ProgramSpec) -> tuple[Module, tuple[str, int]]:
        cached = self._base_modules.get(program.name)
        if cached is None:
            module = build_ir(program.source, program.name)
            cached = (module, run_module(module).observable)
            self._base_modules[program.name] = cached
        return clone_module(cached[0]), cached[1]

    def _observable(self, module: Module) -> tuple[str, int]:
        """Observable behaviour, memoized by IR hash (states recur across episodes)."""
        key = hashlib.sha1(format_module(module).encode()).hexdigest()
        cached = self._observable_cache.get(key)
        if cached is None:
            cached = run_module(module).observable
            self._observable_cache[key] = cached
        return cached

    # ------------------------------------------------------------------ Gym API

    def reset(self, program: ProgramSpec | None = None) -> tuple[np.ndarray, dict[str, Any]]:
        program = program or self.rng.choice(self.programs)
        self._program = program
        self._module, self._reference = self.load_program(program)
        self._t = 0
        self._last_action: int | None = None
        self._c0 = self.evaluator(self._module)
        self._s0 = max(module_instruction_count(self._module), 1)
        self._cost = self._c0
        self._size = float(self._s0)
        self.stats = EpisodeStats(program.name, self._c0, self._c0)
        return self._observe(), {"program": program.name}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._module is None:
            raise RuntimeError("call reset() before step()")
        name = ENV_ACTIONS[action]
        if name == STOP:
            self._last_action = action
            return self._observe(), 0.0, True, False, {"stop": True}
        cfg = self.reward_config
        try:
            new_module = apply_pass(self._module, name)  # verifies the IR
            if self.check_output and self._observable(new_module) != self._reference:
                raise RuntimeError(f"{name} changed observable behaviour")
        except Exception as exc:  # an invalid transformation is a compiler bug: count it
            self.invalid_transformations += 1
            self.stats.invalid = True
            self.stats.total_reward -= cfg.invalid_penalty
            return self._observe(), -cfg.invalid_penalty, True, False, {"invalid": str(exc)}
        new_cost = self.evaluator(new_module)
        new_size = float(module_instruction_count(new_module))
        reward = (
            cfg.w_cost * (self._cost - new_cost) / self._c0
            + cfg.w_size * (self._size - new_size) / self._s0
            - cfg.step_penalty
        )
        self._module, self._cost, self._size = new_module, new_cost, new_size
        self._t += 1
        self._last_action = action
        self.stats.passes.append(name)
        self.stats.final_cost = new_cost
        self.stats.total_reward += reward
        truncated = self._t >= self.horizon
        return self._observe(), reward, False, truncated, {"cost": new_cost}

    @property
    def module(self) -> Module:
        assert self._module is not None
        return self._module
