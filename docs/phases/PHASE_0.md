# Phase 0 Report — Project Foundation

**PHASE:** 0 — Project foundation
**STATUS:** ✅ Complete (2026-10-02)

## Implemented
- Git repository (`main`) with `.gitignore` (including the credential-bearing
  `server_system_info.txt`) and `.gitattributes` (LF normalization).
- `pyproject.toml` (PEP 621, hatchling, src layout). The `forgecompile` console script, a
  `dev` dependency group (pytest, ruff, mypy) and a committed `uv.lock`. Python pinned to 3.11.
- `forgecompile` CLI (argparse): `--version`, `--log-level`, `info [--json]`. Also works as
  `python -m forgecompile`.
- `utils/logging.py`: namespaced loggers, text or JSON-lines output, file logging,
  `FORGECOMPILE_LOG_LEVEL`.
- `utils/environment.py`: environment capture (Python, OS, CPU, git commit and dirty flag) and
  backend tool detection (llvmlite, zig, clang).
- `utils/experiment.py`: `ExperimentRun`, which creates per-run directories with metadata,
  config and log, seeds RNGs, saves artifacts and records completed/failed status.
- Directory structure: `src/ tests/ docs/ docs/phases/ benchmarks/ experiments/ scripts/
  examples/`.
- Check scripts `scripts/check.sh` and `scripts/check.ps1`, plus GitHub Actions CI
  (Ubuntu + Windows).
- All required docs created. Real content: README, ROADMAP, ARCHITECTURE, DECISIONS
  (D-001…D-008), FAILURES, EXPERIMENTS (template + research questions), THEORY §1,
  HOW_TO_STUDY §0, DEVELOPMENT, HOW_TO_RUN. Docs for future phases are explicit stubs.

## Tests
25 tests in `tests/test_cli.py`, `test_environment.py`, `test_logging.py` and
`test_experiment.py`, all passing locally on Windows (Python 3.11.15). They cover the CLI exit
codes, JSON output, the `python -m` entry point, logger namespacing and handler
de-duplication, JSON-lines structured data, seeding reproducibility, failed-run status,
artifact path validation and experiment-ID validation. ruff and mypy are clean.

## Experiments
None. A toolchain feasibility probe was run (not an experiment): llvmlite 0.50.0 (LLVM 22.1.0)
and the ziglang 0.16.0 wheel installed. `zig cc` compiled a hand-written LLVM IR file into a
native Windows `.exe` that printed `42` (see DECISIONS D-002).

## Results
Not applicable.

## Important decisions
D-001 Python · D-002 llvmlite + zig cc · D-003 uv/hatchling/src layout · D-004 argparse ·
D-005 local development, remote server optional, credentials never committed · D-006
(planned) interpreter-based deterministic cost metric · D-007 add dependencies per phase ·
D-008 docs layout.

## Problems encountered → how they were solved
- F-001: `uv sync` failed because `README.md` did not exist yet (hatchling validates the
  `readme` field). Solved by writing the README before the first install.
- The development machine has no C/LLVM toolchain. Solved by the pip-only backend toolchain
  (D-002).

## Known limitations
- The CI workflow is written and its steps pass locally, but it has **not run on GitHub**
  yet, because no remote is configured.
- Python RNG is the only one seeded so far. numpy and torch seeding must be added when those
  dependencies arrive.

## Files changed
`.gitignore`, `.gitattributes`, `.python-version`, `pyproject.toml`, `uv.lock`, `README.md`,
`.github/workflows/ci.yml`, `src/forgecompile/**`, `tests/*.py`, `scripts/check.{sh,ps1}`,
`docs/*.md`, `docs/phases/PHASE_0.md`, `benchmarks/README.md`, `experiments/README.md`,
`experiments/runs/.gitkeep`, `examples/README.md`.

## Commit
`phase-0: project foundation (packaging, CLI, logging, experiment tracking, docs)`

## Next phase
Phase 1: the MiniLang frontend (language spec, lexer, Pratt/recursive-descent parser, AST
with source spans, syntax diagnostics).
