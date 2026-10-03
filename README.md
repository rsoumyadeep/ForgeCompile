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

> **Project status:** complete through Phase 10. The compiler (Phases 0–5), the benchmark
> harness (6), supervised pass selection (7), and the RL environment and Double-DQN agent (8–9)
> are implemented, tested (772 tests) and evaluated on a lab server (Phase 10). Phase 11 is the
> final audit. See [docs/ROADMAP.md](docs/ROADMAP.md). This README describes only what exists.

## Results in brief

Every number is in [docs/RESULTS.md](docs/RESULTS.md), with its experiment, commit and raw data.

- **The compiler works and its optimizations pay off natively.**
  - ForgeCompile `-O2` makes LLVM `-O0` code 1.18× faster (up to 1.50×) and 13% smaller.
  - LLVM's own `-O2` is 7.4× faster. On top of it, ForgeCompile still shrinks code by 8.9%
    (EXP-003).
- **Learned pass scheduling does not beat the hand-written `-O2` pipeline, on the proxy or
  natively.**
  - Gradient boosting beats the majority baseline 4.4× on one-step regret, yet loses to `-O2`
    end to end (EXP-004/005).
  - A Double DQN loses to both (EXP-006/012).
  - Natively, nothing beats `-O2` beyond the 3% noise band (EXP-008).
- **Why:**
  - Beam search over all 12-pass schedules finds only about 1% headroom above `-O2` (EXP-011).
  - The interpreter cost that the learners optimize correlates only weakly with native time
    (Spearman 0.29, EXP-002).
  - The answers to all ten research questions are in RESULTS.md.

## Quick start

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # create .venv and install dev dependencies
uv run forgecompile --version
uv run forgecompile info     # environment + backend toolchain report
uv run pytest                # run the test suite
uv run forgecompile parse examples/fibonacci.mini           # print the AST
uv run forgecompile parse --format examples/fibonacci.mini  # canonical source
uv run forgecompile check examples/fibonacci.mini           # type-check
uv run forgecompile ir examples/fibonacci.mini              # SSA IR
uv run forgecompile run --stats examples/fibonacci.mini     # execute + instruction counts
uv run forgecompile opt -O 2 --stats examples/matmul.mini   # optimized IR + per-pass report
uv run forgecompile build -O 2 -o matmul.exe examples/matmul.mini  # native executable (via LLVM)
uv run forgecompile run --schedule oracle examples/matmul.mini     # per-program pass schedule
uv run python scripts/e2e_sanity.py                                # whole ML/RL pipeline, ~30 s
```


See [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) for details.

## Repository layout

| Path | Contents |
|------|----------|
| `src/forgecompile/` | Compiler package (one sub-package per pipeline stage, added phase by phase) |
| `tests/` | Unit, integration and end-to-end tests |
| `benchmarks/` | MiniLang benchmark kernels (the runner is `src/forgecompile/benchmarking/`) |
| `experiments/` | One script per experiment plus its curated results; `runs/` holds raw per-run outputs (git-ignored) |
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
- **Learning:** [THEORY](docs/THEORY.md) · [HOW_TO_STUDY](docs/HOW_TO_STUDY.md) ·
  [INTERVIEW_QUESTIONS](docs/INTERVIEW_QUESTIONS.md)
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
