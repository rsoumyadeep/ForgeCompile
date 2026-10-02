# Development Guide

## Environment

| Item | Value (development machine, 2026-10-02) |
|------|------------------------------------------|
| OS | Windows 10 Home (build 21996), x86-64 |
| CPU | Intel Core i5-8300H (4 cores / 8 threads), 16 GB RAM, no GPU |
| Python | 3.11.15 (uv-managed; pinned via `.python-version`) |
| Package manager | uv 0.11 |
| Backend toolchain | none system-wide; llvmlite + ziglang wheels from Phase 5 (D-002) |

`forgecompile info` prints the live equivalent of this table.

## Everyday commands

```bash
uv sync                          # install / update .venv from uv.lock
uv run pytest                    # all tests
uv run pytest -m "not slow"      # skip long-running tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy                      # type-check src/
scripts/check.sh                 # all of the above (CI equivalent); scripts/check.ps1 on Windows
```

## Conventions

- **Layout:** one sub-package per pipeline stage. Keep modules small: split a file once it
  grows past roughly 500 lines or covers more than one concept.
- **Types:** all functions in `src/` are type-annotated (`disallow_untyped_defs`).
- **Errors:** user-facing errors (syntax, type and CLI errors) are diagnostics with source
  locations, never raw tracebacks. Internal invariant violations raise exceptions.
- **Tests:** they mirror the package layout under `tests/<package>/`. Every bug fix comes with
  a regression test. Mark long tests `@pytest.mark.slow` and native-binary tests
  `@pytest.mark.native`.
- **Logging:** call `get_logger(__name__)`. Never call `print` outside the CLI layer.
- **Docs:** a phase is not complete until its docs, its decision/failure entries and its phase
  report are written.
- **Commits:** `phase-N: <what changed>`. Run `scripts/check.sh` before committing.

## Phase completion checklist

1. Acceptance criteria in `docs/ROADMAP.md` pass.
2. `scripts/check.sh` is green.
3. `git diff` reviewed; no stray files.
4. Docs updated: phase docs, DECISIONS, FAILURES, THEORY/HOW_TO_STUDY sections.
5. `docs/phases/PHASE_N.md` written.
6. Commit; roadmap status updated.
