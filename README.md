# ForgeCompile — ML-Guided Optimizing Compiler

ForgeCompile is a compiler for **MiniLang**, a small statically typed language. It has its own
IR and optimization passes and uses LLVM as the backend. It is also a testbed for a research
question: **can a learned policy (supervised or reinforcement learning) choose and order
optimization passes better than fixed pipelines?**

```
MiniLang source ─► lexer ─► parser ─► AST ─► semantic analysis
        ─► ForgeCompile IR ─► CFG / SSA ─► optimization passes (classical, ML/RL-scheduled)
        ─► LLVM IR ─► native executable
```

> **Project status:** Phase 0 (foundation) is complete. The compiler itself is not implemented
> yet. See [docs/ROADMAP.md](docs/ROADMAP.md) for phase status. This README only describes
> things that already exist; nothing here is aspirational.

## Quick start

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # create .venv and install dev dependencies
uv run forgecompile --version
uv run forgecompile info     # environment + backend toolchain report
uv run pytest                # run the test suite
```

See [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) for details.

## Repository layout

| Path | Contents |
|------|----------|
| `src/forgecompile/` | Compiler package (one sub-package per pipeline stage, added phase by phase) |
| `tests/` | Unit, integration and end-to-end tests |
| `benchmarks/` | MiniLang benchmark programs + runner (Phase 6) |
| `experiments/` | Experiment definitions; `runs/` holds per-run outputs (git-ignored) |
| `scripts/` | Developer and reproducibility scripts |
| `examples/` | Example MiniLang programs |
| `docs/` | Design docs, theory, decision/failure/experiment logs, study guide |

## Documentation map

- **Design:** [ARCHITECTURE](docs/ARCHITECTURE.md) · [LANGUAGE](docs/LANGUAGE.md) ·
  [IR](docs/IR.md) · [OPTIMIZATIONS](docs/OPTIMIZATIONS.md) · [LLVM_BACKEND](docs/LLVM_BACKEND.md)
- **ML/RL:** [ML_GUIDED_OPTIMIZATION](docs/ML_GUIDED_OPTIMIZATION.md) ·
  [RL_FORMULATION](docs/RL_FORMULATION.md)
- **Evidence:** [EXPERIMENTS](docs/EXPERIMENTS.md) · [RESULTS](docs/RESULTS.md) ·
  [FAILURES](docs/FAILURES.md) · [DECISIONS](docs/DECISIONS.md)
- **Learning:** [THEORY](docs/THEORY.md) · [HOW_TO_STUDY](docs/HOW_TO_STUDY.md)
- **Process:** [ROADMAP](docs/ROADMAP.md) · [DEVELOPMENT](docs/DEVELOPMENT.md) ·
  [HOW_TO_RUN](docs/HOW_TO_RUN.md) · [phase reports](docs/phases/)

## Principles

1. **Correctness before speed.** An optimization that changes program output is a bug. Every
   pass is checked by comparing optimized and unoptimized execution.
2. **Honest experiments.** No fabricated numbers. Negative results stay in the record
   ([RESULTS](docs/RESULTS.md), [FAILURES](docs/FAILURES.md)).
3. **Understandable code.** Each component comes with the theory behind it and the
   alternatives that were considered.

## License

MIT
