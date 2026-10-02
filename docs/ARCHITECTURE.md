# Architecture

> **Status:** Phase 0. This describes the *planned* architecture and what exists today. Each
> component section is filled in when its phase lands.

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
| `cli/` | 0+ | `forgecompile` command; gains a subcommand per phase | ✅ (`info`, `lex`, `parse`, `check`) |
| `driver.py` | 2+ | runs pipeline stages in order (`check_source`, later lowering/optimization/codegen) | ✅ |
| `diagnostics.py` | 1 | `Span`, `SourceFile`, `Diagnostic`, `CompileError`, rustc-style rendering | ✅ |
| `frontend/` | 1 | tokens, lexer, parser (recursive descent + Pratt, panic-mode recovery) | ✅ |
| `ast/` | 1 | nodes, language types, operator precedence table, tree/S-expr dump, source formatter | ✅ |
| `semantic/` | 2 | symbols and scopes, two-pass type checker, return-path analysis | ✅ |
| `runtime/` | 3 | exact MiniLang arithmetic semantics; reference AST interpreter | ✅ |
| `lowering.py` | 3 | type-checked AST → pre-SSA IR | ✅ |
| `ir/` | 3 | values, instructions, blocks/functions, printer, parser, verifier, interpreter + cost model, SSA construction | ✅ |
| `analysis/` | 3–4 | CFG queries, dominator tree, dominance frontiers (✅); liveness, loops (Phase 4) | 🔨 |
| `testing/` | 3 | random well-typed terminating program generator | ✅ |
| `optimization/` | 4 | pass interface, pass manager, passes | ⏳ |
| `backend/` | 5 | LLVM IR emission, native linking | ⏳ |
| `benchmarks` (runner) | 6 | measurement harness | ⏳ |
| `ml/` | 7 | features, datasets, models, baselines | ⏳ |
| `rl/` | 8–9 | environment, agents, training | ⏳ |

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

## Key design choices

See [DECISIONS.md](DECISIONS.md). In short: Python (D-001), LLVM via llvmlite + zig cc
(D-002), interpreter-based deterministic cost metric (D-006, to be validated).
