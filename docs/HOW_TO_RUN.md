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
```

`run` exits with the program's own exit status: main's return value mod 256, or 101 after a
runtime error such as division by zero or an out-of-bounds index.

The extended differential fuzz test (940 generated programs) is marked `slow`:
`uv run pytest -m slow`.

Syntax and type errors are printed to stderr with source excerpts, and the exit code is 1.

## 4. Reproduce experiments

_Available from Phase 6 onward. Each experiment will have a single command listed here._
