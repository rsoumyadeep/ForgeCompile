# ForgeCompile Roadmap

Each phase has an objective, acceptance criteria and a status. A phase is **done** only when
its criteria pass, its tests are green, its docs are updated and it is committed. Each phase
gets a report in [`docs/phases/`](phases/).

Status legend: ✅ done · 🔨 in progress · ⏳ not started · ⚠️ done with documented caveats

| # | Phase | Status | Report |
|---|-------|--------|--------|
| 0 | Project foundation | ✅ | [PHASE_0](phases/PHASE_0.md) |
| 1 | MiniLang frontend (lexer, parser, AST) | ✅ | [PHASE_1](phases/PHASE_1.md) |
| 2 | Semantic analysis | ⏳ | — |
| 3 | IR, reference interpreter, CFG, SSA | ⏳ | — |
| 4 | Classical optimization engine | ⏳ | — |
| 5 | LLVM backend + native executables | ⏳ | — |
| 6 | Benchmarking infrastructure | ⏳ | — |
| 7 | ML-based pass selection | ⏳ | — |
| 8 | RL environment | ⏳ | — |
| 9 | RL optimization agent | ⏳ | — |
| 10 | Experimental study + ablations | ⏳ | — |
| 11 | Final hardening + audit | ⏳ | — |

---

## Phase 0 — Project foundation ✅

**Objective:** a working, tested, documented skeleton. No compiler functionality yet.

**Acceptance criteria**
- [x] `uv sync` installs the project. `forgecompile --version` and `forgecompile info` run.
- [x] `uv run pytest` passes. `ruff` and `mypy` pass.
- [x] Logging infrastructure (text/JSON-lines) and experiment-run metadata capture.
- [x] Directory structure: `src/ tests/ docs/ benchmarks/ experiments/ scripts/ examples/`.
- [x] All required docs exist. Sections for unimplemented phases are explicitly marked.
- [x] CI workflow (lint + type-check + tests on Linux and Windows).

## Phase 1 — MiniLang frontend ✅

**Objective:** turn MiniLang source into an AST with precise source locations.

- Language spec in `docs/LANGUAGE.md`: types `int`, `float`, `bool`, fixed-size arrays;
  `let` variables; arithmetic, comparison and logical operators; `if/else`, `while`, `for`;
  functions with `return`; built-in `print`.
- Hand-written lexer with line/column spans. A Pratt parser for expressions and recursive
  descent for statements.
- Syntax errors show the location and a source excerpt. The parser recovers so that it can
  report more than one error.

**Acceptance** (all met)
- [x] Tests cover valid programs, invalid syntax, precedence and associativity, nesting,
  functions, loops and arrays (139 frontend tests).
- [x] The AST pretty-printer (`forgecompile parse --format`) round-trips all example
  programs, plus 1,000 random expression trees.

## Phase 2 — Semantic analysis

**Objective:** reject ill-formed programs with clear diagnostics and annotate the AST with
types.

- Scoped symbol tables, name resolution, type checking (no implicit int↔float conversion), and
  function arity/return checks (including "missing return on some path").

**Acceptance:** the negative test suite has at least one test per diagnostic.
`docs/LANGUAGE.md` gains a type system section. `forgecompile check` exists.

## Phase 3 — IR, reference interpreter, CFG, SSA

**Objective:** an inspectable three-address IR that supports optimization.

- IR made of functions, basic blocks, instructions, virtual registers and explicit
  terminators. It has loads and stores for arrays and mutable locals, plus calls and
  returns. A textual printer and a parser for that text format (for golden tests).
- AST → IR lowering.
- **IR interpreter.** This is the reference semantics. It also counts dynamic instructions by
  opcode, which gives a deterministic cost metric (D-006).
- CFG utilities, dominator tree (Cooper–Harvey–Kennedy), dominance frontiers, and SSA
  construction (Cytron et al.: mem2reg-style promotion with φ insertion and renaming) plus
  out-of-SSA. The decision to use SSA, and its limits, will be argued in `docs/IR.md`.
- IR verifier (well-formedness, SSA dominance property).

**Acceptance:** for every test program, the interpreter's output matches the expected output
both before and after SSA conversion. The verifier passes on all lowered IR.

## Phase 4 — Classical optimization engine

**Objective:** a pass framework with a common interface and configurable pipelines.

- `Pass` interface, pass registry, `PassManager`, and `--passes a,b,c` as well as pipeline
  config files.
- Passes: constant folding/propagation (SCCP or simple), DCE, algebraic simplification, copy
  propagation, CSE/GVN (dominator-scoped). Later, and only if they can be done correctly:
  strength reduction, LICM, inlining, loop unrolling.
- Per-pass statistics, which become ML features and rewards later.

**Acceptance:** every pass has before/after unit tests. Differential testing checks that
optimized output equals unoptimized output across all programs, including randomly generated
ones. Each pass is documented in `docs/OPTIMIZATIONS.md`.

## Phase 5 — LLVM backend

**Objective:** ForgeCompile IR → LLVM IR → native executable.

- Lowering with llvmlite and the LLVM verifier. Linking a native executable via `zig cc`
  (D-002).
- Differential tests: interpreter output vs native executable output.
- Compare against LLVM's own `-O0..-O3` as a baseline. ForgeCompile's own passes stay the
  object of study.

**Acceptance:** all end-to-end programs produce identical output on the interpreter and on
native code. `docs/LLVM_BACKEND.md` states what is ours and what comes from LLVM.

## Phase 6 — Benchmarking infrastructure

**Objective:** a reproducible measurement harness.

- Benchmark programs covering arithmetic, branches, loops, memory, calls, vectors and matrices.
  A program generator for training data.
- Runner that records runtime (repeated runs with summary statistics), compile time, code
  size, interpreter dynamic instruction counts, pass statistics and environment metadata.
- Table and plot scripts.

**Acceptance:** two runs of the same configuration agree within a measured noise band, and the
noise is documented.

## Phase 7 — ML-based pass selection

**Objective:** a supervised model that predicts a beneficial next pass from IR features.

- Feature extractor (instruction histogram, CFG/loop/memory/call statistics).
- Labels come from real compiler experiments. Splits are made per program to avoid leakage.
- Baselines: random, fixed pipeline, frequency heuristic. Models: decision tree, random forest,
  gradient boosting, small MLP.

**Acceptance:** results are reported on a held-out set of programs against all baselines,
including negative results.

## Phase 8 — RL environment

**Objective:** pass scheduling as an MDP (S, A, P, R, γ, termination). Gym-style API,
seeded and reproducible. Reward design that resists exploitation (for example, no reward for
deleting observable behaviour, and penalties for invalid transformations).

## Phase 9 — RL agent

**Objective:** a progression from random to heuristic to supervised to DQN (or a comparable
discrete-action method). Training configs, seeds, reward curves, held-out evaluation.

## Phase 10 — Experimental study

**Objective:** answer the research questions in `docs/EXPERIMENTS.md`. Ablations cover
feature groups, reward definitions, action spaces and benchmark distributions.

## Phase 11 — Hardening

**Objective:** a fresh-clone reproduction of the main results, cleanup, profiling, a dependency
audit, `INTERVIEW_QUESTIONS.md`, `CV_DESCRIPTION.md`, and the final audit checklist.
