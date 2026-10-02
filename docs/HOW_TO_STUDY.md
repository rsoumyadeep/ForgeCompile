# How to Study ForgeCompile

A study guide for understanding and defending the project. Topics are filled in as the
corresponding phase is built. For each topic the guide gives: what you need to know, where it
lives in the code, key equations, an example, likely interview questions and common
misconceptions.

| # | Topic | Phase | Status |
|---|-------|-------|--------|
| 0 | Project infrastructure and reproducibility | 0 | ✅ below |
| 1 | Compiler overview | 0 | ✅ see [THEORY §1](THEORY.md#1-what-a-compiler-is-and-why-it-is-split-into-phases) |
| 2 | Lexing | 1 | ⏳ |
| 3 | Parsing | 1 | ⏳ |
| 4 | AST | 1 | ⏳ |
| 5 | Semantic analysis | 2 | ⏳ |
| 6 | IR | 3 | ⏳ |
| 7 | CFG | 3 | ⏳ |
| 8 | SSA | 3 | ⏳ |
| 9 | Data-flow analysis | 4 | ⏳ |
| 10 | Classical optimizations | 4 | ⏳ |
| 11 | LLVM | 5 | ⏳ |
| 12 | Benchmarking | 6 | ⏳ |
| 13 | ML for compiler optimization | 7 | ⏳ |
| 14 | RL formulation | 8 | ⏳ |
| 15 | RL implementation | 9 | ⏳ |
| 16 | Experimental methodology | 10 | ⏳ |
| 17 | Failure analysis | all | ⏳ (read [FAILURES.md](FAILURES.md)) |
| 18 | Interview questions | 11 | ⏳ |

Suggested order: read [ARCHITECTURE.md](ARCHITECTURE.md), then this guide topic by topic, with
the code open alongside. After each topic, run its tests and change something on purpose to
see which tests fail.

---

## 0. Project infrastructure and reproducibility

**What you need to know**
- Why a `src/` layout: tests import the *installed* package, which catches packaging mistakes
  that a flat layout hides.
- Why a lock file (`uv.lock`): `pyproject.toml` states *ranges*, while the lock pins the
  *exact* versions, so a fresh clone gets the same dependency set.
- Why every experiment stores environment metadata: a timing is meaningless without the
  machine, OS, Python version and git commit that produced it.
- Why seeds are recorded: RL and ML results vary with the seed. Results are reported across
  several seeds, never from one lucky run.

**Where in the code**
- `src/forgecompile/utils/environment.py`: `collect_environment()`, `detect_tools()`.
- `src/forgecompile/utils/experiment.py`: `ExperimentRun.create()` / `finalize()`.
- `src/forgecompile/utils/logging.py`: JSON-lines logging.
- `src/forgecompile/cli/main.py`: CLI entry point (`forgecompile info`).

**Likely interview questions**
- *How would someone else reproduce your results?* Clone, run `uv sync`, then run the script
  in `HOW_TO_RUN.md`. Each result links to a run directory with its config, seed, environment
  and commit.
- *Why not just print results to the console?* Console output is lost and unstructured. JSON
  lines can be parsed later, for example to rebuild reward curves.
- *What does the `dirty` flag in metadata mean?* The run used uncommitted code, so its commit
  hash does not fully describe the code. Final results must come from clean runs.

**Common misconceptions**
- "Setting a seed makes everything deterministic." It only covers RNGs that you seed. Wall-clock
  timings, thread scheduling and some GPU kernels stay nondeterministic, which is one reason
  for the interpreter-based cost metric (DECISIONS D-006).
