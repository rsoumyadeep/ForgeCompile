# How to Run

## 1. Install

Prerequisites: Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
No system compiler or LLVM installation is required (DECISIONS D-002).

```bash
git clone <repo-url> ForgeCompile
cd ForgeCompile
uv sync
```

Without uv: `python -m venv .venv`, activate it, then `pip install -e . pytest ruff mypy`.

## 2. Verify

```bash
uv run forgecompile --version
uv run forgecompile info        # shows Python/OS and backend tool availability
uv run pytest
```

## 3. Compile programs

This section grows with each phase. Currently the frontend is available:

```bash
uv run forgecompile lex examples/gcd.mini              # token stream with line:column
uv run forgecompile parse examples/gcd.mini            # AST tree
uv run forgecompile parse --format examples/gcd.mini   # canonical source (round-trippable)
uv run forgecompile check examples/gcd.mini            # parse + type-check
uv run forgecompile check --dump examples/gcd.mini     # AST annotated with types
uv run forgecompile ir --no-ssa examples/gcd.mini      # IR straight from lowering
uv run forgecompile ir examples/gcd.mini               # SSA IR
uv run forgecompile run examples/gcd.mini              # execute (SSA IR interpreter)
uv run forgecompile run --engine ast examples/gcd.mini # execute (reference AST interpreter)
uv run forgecompile run --stats examples/gcd.mini      # + dynamic instruction counts (stderr)
uv run forgecompile passes                             # list optimization passes and presets
uv run forgecompile opt -O 2 --stats examples/gcd.mini # optimized IR + per-pass report
uv run forgecompile opt --passes copyprop,bce examples/matmul.mini
uv run forgecompile run -O 2 examples/matmul.mini      # execute optimized IR
uv run forgecompile llvm -O 2 examples/gcd.mini        # LLVM IR (add --llvm-opt 2 to see LLVM's -O2)
uv run forgecompile build -O 2 -o gcd.exe examples/gcd.mini   # native executable
uv run forgecompile run --engine native -O 2 examples/gcd.mini
```

Native builds need no system compiler: the `ziglang` package provides `zig cc`. **The first
native build on a machine takes about a minute**, because zig compiles its libc into a
cache. After that each build takes about 0.3 s. Native tests are marked `native`
(`uv run pytest -m "not native"` skips them).

`run` exits with the program's own exit status: main's return value mod 256, or 101 after a
runtime error such as division by zero or an out-of-bounds index.

The extended differential fuzz test (940 generated programs) is marked `slow`:
`uv run pytest -m slow`.

Syntax and type errors are printed to stderr with source excerpts, and the exit code is 1.

## 4. Reproduce experiments

Each experiment has a single command. Its run directory (`experiments/runs/<ID>_<time>/`)
records the config, seed, environment and git commit. A curated copy of the results is
committed in `experiments/<ID>/`.

| Experiment | Command | Approx. time (laptop) |
|------------|---------|----------------------|
| EXP-001 per-pass effects | `uv run python experiments/EXP-001-pass-effects/run.py --generated 200 --seed 0 --repeats 3` | ~8 min |

Optimization-correctness fuzzing (not an experiment, a test at scale):
`uv run python scripts/fuzz_passes.py --programs 300 --sequences 3` (~2 min).
