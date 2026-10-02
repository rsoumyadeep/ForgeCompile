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

_Available from Phase 1 onward. This section grows with each phase._

## 4. Reproduce experiments

_Available from Phase 6 onward. Each experiment will have a single command listed here._
