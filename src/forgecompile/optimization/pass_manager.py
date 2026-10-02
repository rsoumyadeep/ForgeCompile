"""Pass interface, registry, pass manager and pipeline presets.

Every optimization is a :class:`Pass` with a ``name``, a one-line
``description`` and a ``run`` method that transforms a module in place and
returns a :class:`PassResult`: whether anything changed, plus pass-specific
counters such as ``{"folded": 3}``. Most passes are a :class:`FunctionPass`,
which applies ``run_on_function`` to each function independently.

The :class:`PassManager` runs a pipeline (an ordered list of pass names). It
verifies the IR after every pass, so a buggy pass is caught at the pass that
broke the IR, and it records per-pass statistics:

* static instruction count before and after,
* wall-clock time spent in the pass,
* the pass's own counters.

These records are the "optimization statistics" used by the benchmarks
(Phase 6), and the raw material for ML features and rewards (Phases 7-9).

Pipelines can be given as:

* a comma-separated list: ``"constfold,dce,cse"``;
* a preset name: ``"O0"``, ``"O1"``, ``"O2"`` (see :data:`PRESETS`);
* a file with pass names separated by commas or whitespace (``#`` starts a comment).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from forgecompile.ir.function import Function, Module
from forgecompile.ir.verify import verify_module
from forgecompile.optimization.utils import module_instruction_count


@dataclass
class PassResult:
    changed: bool = False
    stats: Counter[str] = field(default_factory=Counter)

    def merge(self, other: PassResult) -> None:
        self.changed |= other.changed
        self.stats.update(other.stats)


class Pass(ABC):
    """A transformation of a whole module (e.g. inlining, which needs the call graph)."""

    name: ClassVar[str]
    description: ClassVar[str]

    @abstractmethod
    def run(self, module: Module) -> PassResult: ...


class FunctionPass(Pass):
    """A transformation applied to each function independently (most passes)."""

    def run(self, module: Module) -> PassResult:
        result = PassResult()
        for fn in module.functions.values():
            result.merge(self.run_on_function(fn, module))
        return result

    @abstractmethod
    def run_on_function(self, fn: Function, module: Module) -> PassResult: ...


_REGISTRY: dict[str, type[Pass]] = {}


def register_pass(cls: type[Pass]) -> type[Pass]:
    """Class decorator: make a pass available by name to pipelines and the CLI."""
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate pass name {cls.name!r}")
    _REGISTRY[cls.name] = cls
    return cls


def available_passes() -> dict[str, type[Pass]]:
    _load_passes()
    return dict(sorted(_REGISTRY.items()))


def create_pass(name: str) -> Pass:
    passes = available_passes()
    if name not in passes:
        known = ", ".join(passes)
        raise ValueError(f"unknown pass {name!r}; available passes: {known}")
    return passes[name]()


def _load_passes() -> None:
    # Importing the package registers every pass through @register_pass.
    import forgecompile.optimization.passes  # noqa: F401


# --------------------------------------------------------------------------- pipelines

# Presets are starting points, not tuned results. Phase 6/10 measure them, and
# their composition is part of what the ML/RL schedulers try to improve on.
PRESETS: dict[str, list[str]] = {
    "O0": [],
    "O1": ["constfold", "copyprop", "simplify", "dce", "simplifycfg"],
    "O2": [
        "inline",
        "sccp",
        "copyprop",
        "simplify",
        "cse",
        "licm",
        "strength",
        "bce",
        "constfold",
        "copyprop",
        "dce",
        "simplifycfg",
    ],
}


def parse_pipeline(spec: str) -> list[str]:
    """Turn a preset name, a comma list, or a path to a pipeline file into pass names."""
    spec = spec.strip()
    if spec in PRESETS:
        return list(PRESETS[spec])
    path = Path(spec)
    if path.suffix in (".txt", ".pipeline") and path.exists():
        lines = [line.split("#")[0] for line in path.read_text("utf-8").splitlines()]
        text = " ".join(lines)
    else:
        text = spec
    names = [part for chunk in text.split(",") for part in chunk.split()]
    for name in names:
        create_pass(name)  # validate eagerly, with a helpful error
    return names


@dataclass
class PassRecord:
    name: str
    changed: bool
    stats: dict[str, int]
    instructions_before: int
    instructions_after: int
    seconds: float


@dataclass
class PipelineReport:
    records: list[PassRecord] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return sum(r.seconds for r in self.records)

    def summary(self) -> str:
        lines = [f"{'pass':<12} {'changed':<8} {'insts':>14} {'ms':>8}  stats"]
        for r in self.records:
            stats = ", ".join(f"{k}={v}" for k, v in sorted(r.stats.items()))
            change = f"{r.instructions_before}->{r.instructions_after}"
            lines.append(
                f"{r.name:<12} {('yes' if r.changed else 'no'):<8} {change:>14} "
                f"{r.seconds * 1000:>8.2f}  {stats}"
            )
        return "\n".join(lines)


class PassManager:
    def __init__(self, pipeline: list[str], verify: bool = True) -> None:
        self.passes = [create_pass(name) for name in pipeline]
        self.verify = verify

    def run(self, module: Module) -> PipelineReport:
        report = PipelineReport()
        for opt in self.passes:
            before = module_instruction_count(module)
            start = time.perf_counter()
            result = opt.run(module)
            elapsed = time.perf_counter() - start
            if self.verify:
                try:
                    verify_module(module, ssa=True)
                except Exception as exc:
                    raise RuntimeError(f"IR invalid after pass '{opt.name}': {exc}") from exc
            report.records.append(
                PassRecord(
                    opt.name,
                    result.changed,
                    dict(result.stats),
                    before,
                    module_instruction_count(module),
                    elapsed,
                )
            )
        return report


def optimize(module: Module, pipeline: list[str] | str, verify: bool = True) -> PipelineReport:
    names = parse_pipeline(pipeline) if isinstance(pipeline, str) else pipeline
    return PassManager(names, verify=verify).run(module)
