"""Differential fuzzing of optimization passes.

For each program (the examples plus generated programs), the unoptimized SSA
IR is the reference. Each pass on its own, and then random pass sequences,
must produce IR that passes the verifier and has identical observable
behaviour ``(stdout, exit status)``.

Usage::

    uv run python scripts/fuzz_passes.py --programs 300 --sequences 3 --seed 0

Exit status 1 if any mismatch or verifier failure is found. Failing cases are
printed with the program seed and the pass sequence, so they can be reproduced.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.optimization.pass_manager import available_passes, optimize
from forgecompile.testing.program_generator import generate_program

REPO = Path(__file__).resolve().parent.parent


def programs(count: int, first_seed: int) -> list[tuple[str, str]]:
    examples = [(p.name, p.read_text("utf-8")) for p in sorted((REPO / "examples").glob("*.mini"))]
    generated = [(f"gen:{s}", generate_program(s)) for s in range(first_seed, first_seed + count)]
    return examples + generated


def check(label: str, source: str, sequence: list[str], reference: tuple[str, int]) -> str | None:
    module = build_ir(source)
    try:
        optimize(module, sequence)  # verifies SSA after every pass
        observed = run_module(module).observable
    except Exception as exc:  # report every crash as a failure, with context
        return f"{label} {sequence}: {type(exc).__name__}: {str(exc)[:300]}"
    if observed != reference:
        return f"{label} {sequence}: output mismatch"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--programs", type=int, default=200, help="number of generated programs")
    parser.add_argument("--first-seed", type=int, default=0, help="first generator seed")
    parser.add_argument("--sequences", type=int, default=3, help="random sequences per program")
    parser.add_argument("--max-length", type=int, default=12, help="maximum sequence length")
    parser.add_argument("--seed", type=int, default=0, help="seed for choosing sequences")
    args = parser.parse_args()

    names = list(available_passes())
    rng = random.Random(args.seed)
    corpus = programs(args.programs, args.first_seed)
    failures: list[str] = []
    start = time.perf_counter()
    per_pass_steps = {name: 0 for name in names}
    reference_steps = 0
    for label, source in corpus:
        ref_result = run_module(build_ir(source))
        reference = ref_result.observable
        reference_steps += ref_result.steps
        for name in names:
            failure = check(label, source, [name], reference)
            if failure:
                failures.append(failure)
            else:
                module = build_ir(source)
                optimize(module, [name], verify=False)
                per_pass_steps[name] += run_module(module).steps
        for _ in range(args.sequences):
            sequence = [rng.choice(names) for _ in range(rng.randrange(1, args.max_length + 1))]
            failure = check(label, source, sequence, reference)
            if failure:
                failures.append(failure)

    elapsed = time.perf_counter() - start
    print(
        f"programs: {len(corpus)}  passes: {len(names)}  random sequences: "
        f"{len(corpus) * args.sequences}  time: {elapsed:.1f}s"
    )
    print(f"dynamic IR instructions, unoptimized total: {reference_steps}")
    for name, steps in per_pass_steps.items():
        print(f"  {name:<12} alone -> {steps}")
    for failure in failures:
        print("FAIL", failure)
    print(f"failures: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
