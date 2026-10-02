"""End-to-end differential testing across execution engines.

For every program, all engines must agree on the observable behaviour
``(stdout, exit status)``:

    reference AST interpreter == IR interpreter (pre-SSA) == IR interpreter (SSA)

Inputs: the example programs, which also have hand-verified golden outputs,
plus randomly generated programs (deterministic seeds). Phase 4 adds the
optimized pipelines and Phase 5 adds native executables to the same comparison.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.driver import build_ir, check_source
from forgecompile.ir.interpreter import run_module
from forgecompile.runtime.ast_interpreter import run_program
from forgecompile.testing.program_generator import generate_program

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))
FAST_SEEDS = range(60)
SLOW_SEEDS = range(60, 1000)


def observable_everywhere(source: str) -> list[tuple[str, int]]:
    reference = run_program(check_source(source).ast)
    pre_ssa = run_module(build_ir(source, ssa=False))
    ssa = run_module(build_ir(source, ssa=True))
    return [reference.observable, pre_ssa.observable, ssa.observable]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_match_golden_output_on_all_engines(path: Path) -> None:
    expected = (path.with_suffix(".expected").read_text("utf-8"), 0)
    assert observable_everywhere(path.read_text("utf-8")) == [expected] * 3


def test_generated_programs_type_check() -> None:
    for seed in range(200):
        check_source(generate_program(seed))  # raises CompileError if the generator is wrong


def test_generator_is_deterministic() -> None:
    assert generate_program(7) == generate_program(7)
    assert generate_program(7) != generate_program(8)


@pytest.mark.parametrize("seed", FAST_SEEDS)
def test_random_programs_agree(seed: int) -> None:
    results = observable_everywhere(generate_program(seed))
    assert results[0] == results[1] == results[2]


@pytest.mark.slow
def test_random_programs_agree_extended() -> None:
    failures = [s for s in SLOW_SEEDS if len(set(observable_everywhere(generate_program(s)))) != 1]
    assert failures == []
