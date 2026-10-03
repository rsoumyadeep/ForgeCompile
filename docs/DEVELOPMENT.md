# Development Guide

## Environment

| Item | Value (development machine, 2026-10-02) |
|------|------------------------------------------|
| OS | Windows 10 Home (build 21996), x86-64 |
| CPU | Intel Core i5-8300H (4 cores / 8 threads), 16 GB RAM, no GPU |
| Python | 3.11.15 (uv-managed; pinned via `.python-version`) |
| Package manager | uv 0.11 |
| Backend toolchain | llvmlite 0.50.0 (LLVM 22.1.0) + ziglang 0.16.0 wheels (D-002); no system compiler |

`forgecompile info` prints the live equivalent of this table.

**Execution server** (experiments, D-034): `csrslave`, AMD EPYC 7513 (32 cores / 64 threads),
503 GB RAM, 2× RTX A6000 (unused, D-039), Ubuntu 22.04. It runs Python 3.11.16 in an isolated uv
environment (`~/ForgeCompile/.venv`, `uv sync --locked`) with numpy 2.4.6, scikit-learn 1.9.1,
llvmlite 0.50.0 (LLVM 22.1) and ziglang 0.16.0. The machine is shared with other users, so
every run's metadata records the load averages.

## Server workflow

```bash
# laptop: commit + push; then on the server:
cd ~/ForgeCompile && git pull
uv run --locked python scripts/resources.py         # RAM / load / GPU / safe worker count
scripts/server/launch.sh <name> <command...>        # tmux, clean-tree + memory checks, ~/forge_logs/<name>.log
# afterwards: copy the curated experiments/EXP-*/ files back, commit them on the laptop, and push
```

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

## Profiling (2026-10-03, laptop, cProfile)

| Workload | Where the time goes |
|---|---|
| `build_ir` + O2 on `examples/matmul.mini` (×20, 1.9 s) | 70% of optimization time is **IR verification after every pass**: the deliberate safety net of the pass manager. The benchmark harness compiles with `verify=False`. Lowering and the frontend take most of the rest. |
| 6 dataset trajectories (ML labelling, 36.7 s under the profiler) | 58% IR interpreter; 20% `clone_module` (print → parse deep copy); 19% applying passes, including verification. **`Enum.__hash__` alone took 11%** (8.5M calls) because opcode-keyed dicts and sets sit on the interpreter's hot path. |

**Change made:** `Opcode`, `CmpPred` and `IRType` use the C-level identity hash. Enum equality is
identity, so behaviour is unchanged. Dataset generation got about 10% faster (10.0 s → 9.0 s on
the benchmark above), with a byte-identical dataset hash.

**Not done (documented trade-offs):**
- A structural `clone_module`, which would replace the text round trip. The round trip is
  tested to be exact and doubles as a printer/parser check (F-016 was found that way).
- A faster interpreter: compiling IR to Python closures, or running natively. That would
  complicate the reference semantics.

## Phase completion checklist

1. Acceptance criteria in `docs/ROADMAP.md` pass.
2. `scripts/check.sh` is green.
3. `git diff` reviewed; no stray files.
4. Docs updated: phase docs, DECISIONS, FAILURES, THEORY/HOW_TO_STUDY sections.
5. `docs/phases/PHASE_N.md` written.
6. Commit; roadmap status updated.
