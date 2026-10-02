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
```

Syntax and type errors are printed to stderr with source excerpts, and the exit code is 1.

## 4. Reproduce experiments

_Available from Phase 6 onward. Each experiment will have a single command listed here._
