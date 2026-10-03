# ForgeCompile Roadmap

Each phase has an objective, acceptance criteria and a status. A phase is **done** only when
its criteria pass, its tests are green, its docs are updated and it is committed. Each phase
gets a report in [`docs/phases/`](phases/).

Status legend: ✅ done · 🔨 in progress · ⏳ not started · ⚠️ done with documented caveats

| # | Phase | Status | Report |
|---|-------|--------|--------|
| 0 | Project foundation | ✅ | [PHASE_0](phases/PHASE_0.md) |
| 1 | MiniLang frontend (lexer, parser, AST) | ✅ | [PHASE_1](phases/PHASE_1.md) |
| 2 | Semantic analysis | ✅ | [PHASE_2](phases/PHASE_2.md) |
| 3 | IR, reference interpreter, CFG, SSA | ✅ | [PHASE_3](phases/PHASE_3.md) |
| 4 | Classical optimization engine | ✅ | [PHASE_4](phases/PHASE_4.md) |
| 5 | LLVM backend + native executables | ✅ | [PHASE_5](phases/PHASE_5.md) |
| 6 | Benchmarking infrastructure | 🔨 code done; EXP-002/003 pending on the server | — |
| 7 | ML-based pass selection | ⚠️ done; negative end-to-end result | [PHASE_7](phases/PHASE_7.md) |
| 8 | RL environment | ✅ | [PHASE_8](phases/PHASE_8.md) |
| 9 | RL optimization agent | 🔨 EXP-006 done (negative); EXP-012 follow-up pending | — |
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

## Phase 2 — Semantic analysis ✅

**Objective:** reject ill-formed programs with clear diagnostics and annotate the AST with
types.

- Scoped symbol tables, name resolution, type checking (no implicit int↔float conversion), and
  function arity/return checks (including "missing return on some path").

**Acceptance** (all met)
- [x] The negative suite has at least one test per diagnostic (`tests/semantic/`, 116
  tests; each single-bug program must yield *exactly one* error).
- [x] `docs/LANGUAGE.md` §4–6 (types, typing rules, scopes) are marked as implemented.
- [x] `forgecompile check [--dump]` exists.
- [x] Mutation testing: 4 injected checker bugs were all caught (FAILURES F-005).

## Phase 3 — IR, reference interpreter, CFG, SSA ✅

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

**Acceptance** (all met)
- [x] Every example matches its hand-verified golden output on the AST interpreter, the
  pre-SSA IR and the SSA IR. 1,000 generated programs agree across all three engines.
- [x] The verifier passes on all lowered IR, and on all SSA IR in SSA mode (dominance
  property).
- [x] The SSA decision is argued in IR.md §9 / D-017. Out-of-SSA was deliberately not built.
- [x] Beyond the original plan: a reference AST interpreter (D-019) and a random program
  generator (D-020).

## Phase 4 — Classical optimization engine ✅

**Objective:** a pass framework with a common interface and configurable pipelines.

- `Pass` interface, pass registry, `PassManager`, and `--passes a,b,c` as well as pipeline
  config files.
- Passes: constant folding/propagation (SCCP or simple), DCE, algebraic simplification, copy
  propagation, CSE/GVN (dominator-scoped). Later, and only if they can be done correctly:
  strength reduction, LICM, inlining, loop unrolling.
- Per-pass statistics, which become ML features and rewards later.

**Acceptance** (all met)
- [x] 11 passes, each with before/after IR unit tests, including negative cases.
- [x] Differential testing: single passes, presets and random orderings preserve behaviour.
  This runs in CI (`test_pass_differential.py`) and at scale (`scripts/fuzz_passes.py`:
  0 failures).
- [x] `--passes a,b,c`, `-O 0/1/2` and pipeline files.
- [x] Every pass documented in `docs/OPTIMIZATIONS.md` with real before/after IR.
- [x] EXP-001 measured every pass's effect, including negative results.
- Not implemented, deliberately: loop unrolling, load CSE/LICM, loop rotation (see
  OPTIMIZATIONS.md §5).

## Phase 5 — LLVM backend ✅

**Objective:** ForgeCompile IR → LLVM IR → native executable.

- Lowering with llvmlite and the LLVM verifier. Linking a native executable via `zig cc`
  (D-002).
- Differential tests: interpreter output vs native executable output.
- Compare against LLVM's own `-O0..-O3` as a baseline. ForgeCompile's own passes stay the
  object of study.

**Acceptance** (all met)
- [x] Native output is identical to the interpreters for every example (ForgeCompile O0/O2 ×
  LLVM O0/O2), for a semantic corner-case program (including at LLVM -O3), for runtime
  errors, and for generated programs with random pass sequences and LLVM levels.
- [x] `docs/LLVM_BACKEND.md` §1 tabulates what ForgeCompile implements vs what LLVM provides.
- [x] LLVM `-O1..3` are available as comparison baselines (`--llvm-opt`).

## Phase 6 — Benchmarking infrastructure

**Objective:** a reproducible measurement harness.

- Benchmark programs covering arithmetic, branches, loops, memory, calls, vectors and matrices.
  A program generator for training data.
- Runner that records runtime (repeated runs with summary statistics), compile time, code
  size, interpreter dynamic instruction counts, pass statistics and environment metadata.
- Table and plot scripts.

**Acceptance:** two runs of the same configuration agree within a measured noise band, and the
noise is documented.

## Phase 7 — ML-based pass selection ⚠️

**Objective:** a supervised model that predicts a beneficial next pass from IR features.

**Outcome (2026-10-03):**
- The data were validated (EXP-007).
- The model beats the majority baseline in distribution (EXP-004) but not on OOD programs.
- End to end it is *worse* than O2 (EXP-005), and O2 is within 1% of the greedy oracle.
- This negative result is documented in the phase report.

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

## Future work (motivated by measured results, not started)

EXP-011 showed that, with these 11 passes and a 12-pass budget, even beam search finds only
about 1% average improvement over O2. Learned scheduling only pays off when the decision space
contains real trade-offs. In order of expected value:

1. **Parameterized passes.** Unroll factors, inlining thresholds, LICM with or without loop
   rotation. These are decisions where the best choice genuinely depends on the program, and
   EXP-001 already found one such case (LICM on zero-trip loops).
2. **A native-time objective, or a learned cost model.** EXP-002 measures where the
   interpreter cost misleads, e.g. latency-bound loops.
3. **Training-workload coverage.** The generator never emits induction-variable array
   indexing, so `bce` is never learnable (EXP-004 diagnosis). A coverage-driven generator
   should be designed *without* looking at the OOD programs.
4. **Richer program representations.** Graph neural networks over the CFG/SSA graph instead
   of 61 counts. This would need a deep-learning framework (D-039 trade-off).
5. **Lookahead at inference time.** Beam search or MCTS guided by the learned policy or value
   function. EXP-011 suggests a small beam already captures the available gains.
6. **Evaluation at LLVM -O2,** to see which ForgeCompile decisions survive LLVM's own
   pipeline.
