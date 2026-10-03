"""Differential correctness of every pass, every preset, and random pass orderings.

The reference is the unoptimized SSA IR. Each optimized module must pass the
SSA verifier after every pass and produce identical observable behaviour.
Random orderings matter because the ML/RL schedulers will apply arbitrary
sequences. ``scripts/fuzz_passes.py`` runs the same check at larger scale.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.parser import parse_module
from forgecompile.ir.printer import format_module
from forgecompile.optimization.pass_manager import PRESETS, available_passes, optimize
from forgecompile.testing.program_generator import generate_program

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.mini"))
PASSES = sorted(available_passes())


def assert_preserves(source: str, passes: list[str]) -> None:
    reference = run_module(build_ir(source)).observable
    module = build_ir(source)
    optimize(module, passes)
    assert run_module(module).observable == reference, passes
    # Optimized IR must stay printable *and* parseable: the ML/RL pipeline deep-copies
    # modules through the text format (F-016: a pass created an unparseable name).
    text = format_module(module)
    assert format_module(parse_module(text)) == text, passes


@pytest.mark.parametrize("pipeline", sorted(PRESETS))
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_presets_on_examples_match_golden_output(path: Path, pipeline: str) -> None:
    module = build_ir(path.read_text("utf-8"))
    optimize(module, PRESETS[pipeline])
    result = run_module(module)
    assert (result.stdout, result.exit_code) == (
        path.with_suffix(".expected").read_text("utf-8"),
        0,
    )


@pytest.mark.parametrize("name", PASSES)
def test_each_pass_alone_on_generated_programs(name: str) -> None:
    for seed in range(25):
        assert_preserves(generate_program(seed), [name])


@pytest.mark.parametrize("seed", range(20))
def test_random_pass_orderings(seed: int) -> None:
    rng = random.Random(seed)
    source = generate_program(5000 + seed)
    for _ in range(3):
        assert_preserves(source, [rng.choice(PASSES) for _ in range(rng.randrange(1, 10))])


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_random_orderings_on_examples(path: Path) -> None:
    rng = random.Random(path.name)
    for _ in range(4):
        assert_preserves(path.read_text("utf-8"), [rng.choice(PASSES) for _ in range(8)])


def test_optimizations_reduce_work_on_examples() -> None:
    """O2 must never execute more IR instructions than unoptimized code on the examples."""
    for path in EXAMPLES:
        source = path.read_text("utf-8")
        base = run_module(build_ir(source)).steps
        module = build_ir(source)
        optimize(module, PRESETS["O2"])
        assert run_module(module).steps <= base, path.name
