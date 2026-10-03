# Architecture

> **Status:** all components exist (Phases 0–9). Each section describes what is implemented,
> with links to the detailed design documents.

## Pipeline

```
            ┌──────────── frontend ────────────┐   ┌─ middle end ──────────────────────────┐   ┌─ backend ─────────┐
 source ──► │ lexer ─► parser ─► AST ─► semantic │─► │ lowering ─► IR ─► CFG/SSA ─► passes  │─► │ LLVM IR ─► zig cc │─► native exe
            └────────────────────────────────────┘   │            ▲         │               │   └───────────────────┘
                                                     │            │   IR interpreter        │
                                                     │            │   (oracle + cost)       │
                                                     │   pass scheduler: fixed │ ML │ RL    │
                                                     └─────────────────────────────────────┘
```

Each stage has a single input type and a single output type. This keeps the stages
independently testable: a parser test never needs the backend, and a pass test builds IR
directly from text.

## Package layout (`src/forgecompile/`)

| Package | Phase | Responsibility | Status |
|---------|-------|----------------|--------|
| `utils/` | 0 | logging, environment capture, experiment runs | ✅ |
| `cli/` | 0+ | `forgecompile` command (`info lex parse check ir run passes opt llvm build bench`) | ✅ |
| `driver.py` | 2+ | runs pipeline stages in order (`check_source`, later lowering/optimization/codegen) | ✅ |
| `diagnostics.py` | 1 | `Span`, `SourceFile`, `Diagnostic`, `CompileError`, rustc-style rendering | ✅ |
| `frontend/` | 1 | tokens, lexer, parser (recursive descent + Pratt, panic-mode recovery) | ✅ |
| `ast/` | 1 | nodes, language types, operator precedence table, tree/S-expr dump, source formatter | ✅ |
| `semantic/` | 2 | symbols and scopes, two-pass type checker, return-path analysis | ✅ |
| `runtime/` | 3 | exact MiniLang arithmetic semantics; reference AST interpreter | ✅ |
| `lowering.py` | 3 | type-checked AST → pre-SSA IR | ✅ |
| `ir/` | 3 | values, instructions, blocks/functions, printer, parser, verifier, interpreter + cost model, SSA construction | ✅ |
| `analysis/` | 3–4 | CFG queries, dominator tree, dominance frontiers, natural loops, preheaders, induction variables | ✅ |
| `testing/` | 3 | random well-typed terminating program generator | ✅ |
| `optimization/` | 4 | pass interface and registry, pass manager (verify after each pass), presets, utilities, 11 passes | ✅ |
| `backend/` | 5 | LLVM IR emission + llvmlite verification, zig cc build/run, C runtime | ✅ |
| `benchmarking/` | 6 | benchmark suite loader, correctness-gated native timing runner, statistics, reports | ✅ |
| `ml/` | 7 | IR features, oracle-labelled datasets, splits/caching, models, policies, end-to-end evaluation | ✅ |
| `rl/` | 8–9 | pass-scheduling MDP environment, NumPy Double DQN, parallel training jobs | ✅ |

## Cross-cutting infrastructure (exists)

- **Logging** (`utils/logging.py`): every logger lives under the `forgecompile.*` namespace.
  Output is human-readable text on the console and JSON lines in files. Structured fields are
  passed via `extra={"data": {...}}`.
- **Environment capture** (`utils/environment.py`): Python, OS, CPU count, git commit and dirty
  flag, and backend tool versions. `forgecompile info` displays it.
- **Experiment runs** (`utils/experiment.py`): `ExperimentRun.create(id, config, seed)` makes
  `experiments/runs/<ID>_<timestamp>/` with `metadata.json`, `config.json` and `run.log`, and
  seeds RNGs. Failed runs are finalized as `failed`, not deleted.

## Frontend (Phase 1)

```
SourceFile ──tokenize()──► list[Token] + lexer diagnostics
           ──Parser.parse_program()──► ast.Program + parser diagnostics
           (parse_source() raises CompileError if either list is non-empty)
```

- Errors are **collected, not thrown one by one**. The lexer skips bad characters. The
  parser uses panic-mode recovery with brace tracking (FAILURES F-002), so one run reports
  every independent syntax error.
- `ast/operators.py` is the single precedence table, shared by the parser and the formatter.
- The AST desugars `else if` and drops parentheses. Equality ignores spans, which is what
  makes the round-trip tests possible.

## Semantic analysis (Phase 2)

```
ast.Program ──TypeChecker pass 1──► function signature table
            ──TypeChecker pass 2──► annotated AST (Expr.ty, Name.symbol, Call.function, ...)
                                    + ProgramInfo(functions, main)
            (analyze() raises CompileError with every diagnostic, sorted by position)
```

- Annotations are written **in place** (DECISIONS D-013). Names resolve to `VariableSymbol`
  objects with unique `uid`s, so shadowed variables never collide in later phases.
- An `ERROR` type suppresses cascades (D-014).
- `control_flow.completes_normally` handles the conservative missing-return check.

## Middle end (Phase 3)

```
CheckedProgram ──lower_program──► pre-SSA IR ──verify──► construct_ssa ──verify(ssa)──► SSA IR
                                       │                                                 │
                                       └──────── IRInterpreter (oracle + cost) ◄──────────┘
AST ──AstInterpreter── reference behaviour (differential tests compare all engines)
```

- `driver.build_ir(text, ssa=True)` runs the whole chain, with verification after each step.
- See [IR.md](IR.md) for the instruction set, memory model, effect classes and SSA design.

## Optimization (Phase 4)

```
SSA IR ──PassManager([names])──► optimized SSA IR + PipelineReport (per-pass stats)
          │  after each pass: verify_module(ssa=True)
          └─ passes: constfold sccp copyprop dce simplify simplifycfg cse licm strength bce inline
```

- Constant folding and the interpreter share `ir/evaluate.py` (D-022).
- Loop passes assume copy-propagated IR (D-023), which is a measured phase-ordering
  dependency.
- See [OPTIMIZATIONS.md](OPTIMIZATIONS.md).

## Backend (Phase 5)

```
optimized SSA IR ──emit_module──► LLVM IR text ──verify_llvm (llvmlite)──►
   zig cc -O<llvm_opt> program.ll fc_runtime.c ──► native executable ──run_executable──► (stdout, status)
```

- `driver.compile_to_llvm(text, pipeline)` runs the whole chain up to verified LLVM IR.
- LLVM defaults to `-O0` so measurements isolate ForgeCompile's passes (D-028).
- See [LLVM_BACKEND.md](LLVM_BACKEND.md).

## Benchmarking (Phase 6)

```
benchmarks/*.mini ──load_suite──► Benchmark(small/large instance)
   run_suite(benchmarks, configs):  small: interpreter + native output must match (gate)
                                    large: build once, warm up, interleaved seeded rounds
                                    ──► BenchRecord(static, interpreter, native times) ──► reports
```

- One `BenchConfig` = (name, ForgeCompile pass list, LLVM level).
- See [THEORY §12](THEORY.md#12-measuring-performance) and `benchmarks/README.md`.

## ML-guided pass selection (Phase 7)

```
generator seeds ──program_splits──► train / val / test (generated) + ood (hand-written)
   trajectory(): at each state, apply every pass to a copy (clone via print/parse),
                 run the IR interpreter ──► StateRecord(features φ(M) ∈ ℝ⁶¹, outcome table, label)
   build_dataset() ──cache (config + src tree hash)──► records ──select_model (val regret)──►
   TrainedModel.rank(φ) ──ModelPolicy──► schedule(policy, module) ──evaluate_policies (outputs checked)
```

- Baselines: `FixedPipelinePolicy` (O1/O2/frequency), `RandomPolicy`, `OraclePolicy` (greedy
  upper bound).
- See [ML_GUIDED_OPTIMIZATION.md](ML_GUIDED_OPTIMIZATION.md).

## RL pass scheduling (Phases 8–9)

```
PassSchedulingEnv(train programs):  reset() ──► o₀ = [φ(M₀), 1, 0…0] ∈ ℝ⁷⁴
   step(a): M' = pass_a(M) (verified; output re-checked) ──► r = ΔC/C₀ (+ w_s ΔS/S₀) − λ
DQNAgent (NumPy MLP 74→128→128→12, replay, target net, Double DQN)
run_training_job ──► best-validation checkpoint ──► DQNPolicy ──► evaluate_policies
```

- Seeds and ablation conditions train in parallel processes, one cost cache per process.
- See [RL_FORMULATION.md](RL_FORMULATION.md).

## Experiments

Every experiment is one script, `experiments/EXP-NNN-*/run.py`. It creates an `ExperimentRun`
(config, seed, environment, git commit, status), writes raw results to the git-ignored
`experiments/runs/`, and writes curated copies next to the script. Long runs go through
`scripts/server/launch.sh` (tmux, resource check, clean-tree check). See
[EXPERIMENTS.md](EXPERIMENTS.md).

## Key design choices

See [DECISIONS.md](DECISIONS.md). In short: Python (D-001), LLVM via llvmlite + zig cc
(D-002), interpreter-based deterministic cost metric (D-006, tested by EXP-002), NumPy-only
ML/RL (D-039), server-first execution with GitHub as the source of truth (D-034).
