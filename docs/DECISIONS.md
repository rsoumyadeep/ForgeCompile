# Decision Log

Each important architectural decision is recorded with its context, the alternatives and the
trade-offs. Entries are append-only. If a decision is reversed, a new entry supersedes the old
one and links back to it.

---

## D-001 — Implement the compiler in Python

- **Date:** 2026-10-02
- **Context:** The project combines a compiler (frontend, IR, passes) with ML/RL experiments
  (feature extraction, scikit-learn models, RL training). It has to be readable enough to
  study and defend in an interview.
- **Alternatives:** C++ (the "industrial" choice, with native LLVM C++ APIs); Rust (inkwell);
  OCaml.
- **Chosen:** Python ≥ 3.11 with type hints, checked by mypy.
- **Why:**
  - The ML/RL stack (scikit-learn, PyTorch) is native to Python, so there is no FFI boundary
    between the compiler and the learner. The RL environment calls passes directly.
  - Iteration speed: the core work is designing IR and passes, not raw compiler throughput.
  - Readability for study.
- **Trade-offs:** The compiler runs ~10–100× slower than a C++ equivalent. This limits how
  many compile/evaluate steps fit into RL training. It is mitigated by keeping benchmark
  programs small and by using an interpreter-based cost metric (D-006). Generated code speed
  is unaffected, because native code comes from LLVM.
- **Consequences:** Compile time must be measured honestly as *Python* compile time. It should
  not be compared directly against clang's compile time.

## D-002 — LLVM backend via llvmlite, linking with `zig cc`

- **Date:** 2026-10-02
- **Context:** The development machine (Windows 10, i5-8300H) has **no** system clang, gcc,
  MSVC or LLVM, and no admin-level toolchain install is assumed. Native executables are
  required (Phase 5).
- **Alternatives:**
  1. Write an x86-64 backend by hand. This is outside the project's focus (optimization and
     ML), and a large amount of work.
  2. Install LLVM/clang system-wide. Not reproducible via `pip`/`uv`, and differs per OS.
  3. Emit textual LLVM IR only and require users to bring clang.
  4. **llvmlite** (pip wheel bundling LLVM) for IR verification, LLVM's own optimization
     pipeline (as a baseline) and object emission, together with the **ziglang** pip wheel
     (bundles clang and lld) for linking.
- **Chosen:** Option 4. Verified on 2026-10-02: llvmlite 0.50.0 (LLVM 22.1.0) installs on this
  machine. `python -m ziglang cc -O2 t.ll -o t.exe` compiled a hand-written LLVM IR
  `printf` program into a native Windows executable that printed the expected `42`.
- **Why:** The whole toolchain installs through `uv sync` on Windows and Linux. The project
  still emits real LLVM IR and produces real native binaries.
- **Trade-offs:** llvmlite exposes only part of the LLVM API, so ForgeCompile builds textual
  LLVM IR and parses/verifies it with llvmlite rather than using the C++ IRBuilder. zig cc
  targets `x86_64-windows-gnu` (MinGW ABI) on Windows.
- **Consequences:** Phase 5 adds `llvmlite` and `ziglang` as dependencies. `forgecompile info`
  reports their availability.

## D-003 — uv + pyproject.toml (hatchling), src layout

- **Date:** 2026-10-02
- **Alternatives:** pip + requirements.txt; Poetry; conda.
- **Chosen:** `uv` with a standard PEP 621 `pyproject.toml`, the hatchling build backend,
  PEP 735 dependency groups, a committed `uv.lock` and a `src/` layout.
- **Why:** uv was already installed and is fast. The lock file gives reproducible dependency
  versions. The src layout ensures tests run against the installed package, not against stray
  files in the repository.
- **Trade-offs:** Contributors need uv. Plain `pip install -e .` still works because the
  metadata is standard.

## D-004 — argparse for the CLI

- **Date:** 2026-10-02
- **Alternatives:** click, typer.
- **Chosen:** standard-library `argparse` with subcommands.
- **Why:** zero dependencies. The CLI surface is small (`parse`, `check`, `ir`, `opt`,
  `build`, `run`, `bench`, ...), so argparse is enough.
- **Trade-offs:** slightly more boilerplate.

## D-005 — Develop and test locally; the remote GPU server is optional

- **Date:** 2026-10-02
- **Context:** `server_system_info.txt` describes a remote Ubuntu server (AMD EPYC 7513
  32C/64T, 503 GB RAM, 2× RTX A6000, CUDA 12.4, no sudo). The development machine is a 4-core
  laptop with 16 GB RAM and no GPU.
- **Chosen:** All code, tests and initial (small) experiments are built to run on the laptop.
  Experiments are sized so that they also run there. The server is an optional target for
  larger or quieter timing runs, used at the owner's discretion. The agent does not log into
  it itself.
- **Why:**
  - The server is on a private network.
  - Using credentials found in a file is not appropriate without explicit authorization.
  - The ML/RL models planned here (tree ensembles, small MLP/DQN) do not need a GPU.
- **Security:** `server_system_info.txt` contains plaintext credentials and is in
  `.gitignore`. It must never be committed.
- **Consequences:** Every experiment records its environment (`utils/environment.py`), so
  laptop and server results are never mixed silently.

## D-006 — (Planned) IR interpreter as reference semantics and deterministic cost metric

- **Date:** 2026-10-02 (to be confirmed or revised in Phases 3 and 6)
- **Context:** Wall-clock timing on a laptop is noisy (turbo boost, thermals, background
  processes). An RL reward built only on noisy timings would mostly learn noise, and each
  native measurement costs a compile, link and repeated execution.
- **Plan:** The IR interpreter serves two roles:
  - it is the *oracle* for correctness (differential testing of passes);
  - it reports *dynamic instruction counts* (optionally weighted per opcode). These are
    deterministic and cheap, and form the primary optimization signal for ML/RL.
- **Validation required:** Phase 6 must measure how well interpreter cost correlates with
  native runtime. If the correlation is weak, that is reported as a finding and native timing
  is used for evaluation.
- **Trade-off:** Dynamic IR instruction count ignores cache and memory effects and
  LLVM-backend effects. This is a known limitation that must be discussed alongside the
  results.

## D-007 — Add dependencies only in the phase that needs them

- **Date:** 2026-10-02
- **Chosen:** Phase 0 has zero runtime dependencies. llvmlite and ziglang arrive in Phase 5,
  numpy and scikit-learn in Phase 7, PyTorch (if used at all) in Phase 9.
- **Why:** Keeps installs light, makes each dependency's purpose obvious, and keeps the
  dependency audit (Phase 11) simple.

## D-008 — Documentation layout

- **Date:** 2026-10-02
- **Chosen:** `README.md` at the root. All other docs live in `docs/`, with per-phase reports
  in `docs/phases/PHASE_N.md`. Docs for future phases exist from Phase 0 with an explicit
  "not yet implemented" status, so the structure is stable and nothing pretends to exist
  before it does.

## D-009 — Hand-written lexer and parser (recursive descent + Pratt)

- **Date:** 2026-10-02 (Phase 1)
- **Alternatives:** a parser generator (Lark, ANTLR, PLY/yacc); parser combinators.
- **Chosen:** a hand-written lexer, recursive descent for declarations and statements, and a
  Pratt loop for expressions.
- **Why:**
  - Error messages are under full control. Messages such as "expected ';' after variable
    declaration", positioned just after the previous token, and the "did you mean '&&'?"
    hint are hard to get from generated parsers.
  - Recovery policy is under full control (panic mode with brace tracking).
  - No dependency.
  - Every line can be explained in an interview. The approach mirrors production compilers
    (Clang, rustc and Go use hand-written recursive descent).
- **Trade-offs:** more code than a grammar file, and the grammar is not machine-checked for
  ambiguity. This is mitigated by an EBNF spec in LANGUAGE.md, precedence tests, and the
  randomized round-trip property test.

## D-010 — Language semantics are fully defined (no undefined behaviour)

- **Date:** 2026-10-02 (Phase 1; enforced in Phases 2/3/5)
- **Context:** Optimizations are validated by *differential testing*: unoptimized vs optimized
  vs native output must be identical. Under C-style undefined behaviour (signed overflow,
  division by zero, out-of-bounds access) a "correct" optimizer may legally change outputs,
  and the tests could not distinguish a bug from legal behaviour.
- **Chosen:**
  - Wrapping integer arithmetic.
  - Truncating division, and a runtime error on division by zero; `INT_MIN / -1` wraps.
  - Saturating float→int casts (Rust/`llvm.fptosi.sat` semantics).
  - Bounds-checked arrays.
  - Zero-initialization.
  - Runtime errors exit with status 101.
  - `print(float)` uses `%.6f`.
- **Trade-offs:** The native backend must emit explicit checks for division and bounds, which
  costs some speed. Those checks are also realistic optimization targets later, for example
  removing a bounds check that is provably in range.
- **Consequences:** The interpreter must implement C division semantics, not Python's `//`
  and `%`. Float printing must be verified to match between Python and native `printf`
  (Phase 5).

## D-011 — Restricted counted `for` loops; arrays by reference, not first-class

- **Date:** 2026-10-02 (Phase 1)
- **Alternatives:** C-style `for (init; cond; step)`; first-class array values with copy
  semantics.
- **Chosen:** `for i in a..b` with a read-only induction variable, an end bound evaluated
  once, and arrays passed to functions by reference.
- **Why:**
  - Counted loops with a known induction variable are exactly what loop optimizations need
    (LICM, strength reduction, unrolling). They also make loop-count features well defined
    for the ML phase.
  - `while` remains available for arbitrary loops.
  - Making arrays non-first-class avoids implementing array copies and aliasing rules for
    whole-array assignment.
- **Trade-off:** less expressive than C. Since arrays are passed by reference, two parameters
  may alias the same array, so optimizations must still treat array memory conservatively.

## D-012 — pytest `--import-mode=importlib`

- **Date:** 2026-10-02 (Phase 1)
- **Context:** Tests are organized in sub-directories (`tests/frontend/`, later
  `tests/semantic/`, ...). The default import mode requires globally unique test file
  basenames or `__init__.py` files.
- **Chosen:** importlib mode, with no `__init__.py` in test directories.
- **Trade-off:** test modules cannot import each other. Shared helpers must go in
  `conftest.py` or in the package itself.

## D-013 — Annotate the AST in place, and resolve names to symbol objects

- **Date:** 2026-10-02 (Phase 2)
- **Alternatives:**
  1. Side tables keyed by `id(node)` (`types: dict[int, Type]`).
  2. Build a separate typed AST (a new tree with types).
  3. Annotate the existing nodes (`Expr.ty`, `Name.symbol`, ...).
- **Chosen:** Option 3. The annotation fields are declared with `compare=False` so they do not
  affect AST equality, and they are `None` until analysis runs.
- **Why:**
  - It is the simplest design that lowering can consume directly: `name.symbol` gives the
    storage key without a lookup.
  - Side tables keyed by object identity are fragile, because ids are reused after garbage
    collection.
  - A second tree type would double the node definitions.
- **Trade-offs:** The AST is mutable, and "is this node checked?" is a run-time property, not
  a static type. Lowering asserts that `ty`/`symbol` are not `None`.
- **Symbol identity:** `VariableSymbol` uses identity equality (`eq=False`) plus a `uid`.
  Two shadowed `x` variables are distinct objects. Lowering keys on the symbol (or its uid),
  never on the name string.

## D-014 — An error type to suppress cascading diagnostics

- **Date:** 2026-10-02 (Phase 2)
- **Alternatives:** stop at the first type error; report everything naively.
- **Chosen:** A special `ERROR` type is assigned to ill-typed expressions. Every typing rule
  accepts it without reporting anything.
- **Why:** It reports all *independent* errors in one run without follow-on noise. This is
  the approach used by rustc and Clang. It is verified by tests that assert *exactly one*
  error for each single-bug program.

## D-015 — Compile-time error for literal out-of-bounds indices

- **Date:** 2026-10-02 (Phase 2)
- **Context:** `a[5]` on a `[int; 3]` will always fail at run time if it is reached.
- **Chosen:** Literal indices (including `-k`) outside `0..N` are compile-time errors. All
  other indices are bounds-checked at run time (D-010).
- **Trade-off:** This rejects code that is unreachable, such as `if false { a[5] = 1; }`.
  rustc makes the same choice: a guaranteed failure is almost always a bug.

## D-016 — Register-based three-address IR with multi-assignment before SSA

- **Date:** 2026-10-02 (Phase 3)
- **Alternatives:**
  1. LLVM style: an instruction *is* its value, and locals live in `alloca` memory until a
     mem2reg pass promotes them.
  2. Tree or stack IR.
  3. **Virtual-register three-address code.** A variable is a register assigned by `copy`, and
     SSA construction renames registers.
- **Chosen:** Option 3.
- **Why:**
  - SSA construction becomes the textbook Cytron renaming of registers, without first
    turning loads and stores into values.
  - The IR stays small: no loads and stores for scalars.
  - Pre-SSA IR is executable and inspectable, so lowering can be tested on its own.
- **Trade-off:** Between lowering and SSA, a register can have several definitions, so the
  verifier has a separate pre-SSA mode. The IR also differs slightly from LLVM's value model:
  Phase 5 maps registers to LLVM values, and forwards `copy` operands because LLVM has no
  copy instruction.

## D-017 — SSA is the canonical form; no out-of-SSA translation

- **Date:** 2026-10-02 (Phase 3)
- **Context:** The instructions warn against implementing SSA "because it sounds impressive".
  The decision must be justified by consumers.
- **Chosen:** Lowering produces pre-SSA IR. `build_ir` immediately constructs SSA, and all
  optimization passes and the LLVM backend consume SSA.
- **Why SSA:** The Phase 4 passes (SCCP, copy propagation, CSE/GVN, DCE) are simpler and
  sparser on SSA, and LLVM IR is SSA. See IR.md §9.
- **Why no out-of-SSA:** Its consumers would be a register allocator or a non-SSA backend, and
  this project has neither. LLVM handles phi elimination.
- **Revisit if:** a non-LLVM backend or a source-level decompiler is added.

## D-018 — Flat arrays with explicit `boundscheck`; traps are effects

- **Date:** 2026-10-02 (Phase 3)
- **Chosen:**
  - Arrays are flat zero-filled buffers (allocas hoisted to entry, `memzero` at the
    declaration site), with row-major offsets.
  - `boundscheck idx, len` is a separate instruction.
  - `sdiv`/`srem`/`boundscheck`/`call` are classified *may trap* and are never deleted as
    "unused".
- **Why:**
  - Explicit checks make bounds-check elimination a visible, measurable optimization.
  - Classifying traps as effects is what keeps DCE correct under fully defined semantics
    (D-010).
- **Trade-off:** More instructions per array access. Native code pays for the checks unless
  they are eliminated.

## D-019 — Independent reference AST interpreter as a second oracle

- **Date:** 2026-10-02 (Phase 3)
- **Alternatives:** trust the IR interpreter alone; hand-write expected outputs only.
- **Chosen:** A separate AST interpreter, deliberately structured differently: nested lists,
  exceptions for control flow. Only the arithmetic helpers (`runtime/semantics.py`) are
  shared, and those are tested against hand-computed C/IEEE values.
- **Why:** A bug in lowering would otherwise be invisible. The IR interpreter would faithfully
  run the wrong IR.
- **Trade-off:** Two interpreters to maintain (about 300 lines for the AST one).

## D-020 — Random program generator, built for both testing and later workloads

- **Date:** 2026-10-02 (Phase 3)
- **Chosen:** `forgecompile.testing.program_generator` generates well-typed, *terminating*
  programs:
  - small constant `for` bounds;
  - counter-guarded `while` loops;
  - no recursion;
  - no helper calls inside helper loops;
  - divisors of the form `e*e+1`, which is never 0 mod 2⁶⁴;
  - indices of the form `((e%n)+n)%n`;
  - a 2% chance of deliberately unsafe divisors and indices, to exercise trap paths.

  It builds ASTs and prints them with the formatter.
- **Why:** Differential testing needs volume and variety that hand-written tests cannot give.
  Phases 7 and 9 need training workloads produced the same way.
- **Known bias:** Generated programs are small (median of about 100 IR steps), heavy on
  constants, and light on deep loop nests. Phase 6/7 must not treat them as representative
  of real code. Benchmark kernels are hand-written instead.

## D-006 (update) — IR interpreter cost model implemented, validation pending

- **Date:** 2026-10-02 (Phase 3)
- The interpreter now reports per-opcode dynamic counts and a weighted cost
  (`DEFAULT_COST_MODEL`). The weights are *assumed* rough latencies. Phase 6 must measure
  their correlation with native runtime before ML/RL rewards rely on them.

## D-021 — Pass framework: one interface, verification after every pass

- **Date:** 2026-10-02 (Phase 4)
- **Alternatives:**
  - an LLVM-style new pass manager with analysis caching and invalidation;
  - ad-hoc function calls with no framework.
- **Chosen:** A minimal `Pass` / `FunctionPass` interface with a name registry. The
  `PassManager` runs named pipelines and **verifies SSA after each pass by default**. Analyses
  (dominators, loops) are recomputed by the passes that need them; nothing is cached.
- **Why:**
  - The ML/RL phases need passes as uniform, named actions with statistics.
  - Verification after each pass turns a miscompile into an immediate, attributed error
    (F-009 was caught this way).
  - Recomputing analyses costs little at MiniLang sizes and removes a whole class of
    stale-analysis bugs.
- **Trade-off:** Compile time is higher than with cached analyses. Verification can be turned
  off (`verify=False`) for timing measurements.

## D-022 — One shared evaluator for interpreter and constant folding

- **Date:** 2026-10-02 (Phase 4)
- **Chosen:** `ir/evaluate.py` is used by both the IR interpreter and `fold()`.
- **Why:** A constant folder that disagrees with the runtime is a classic miscompilation
  source. Sharing the code makes such disagreement impossible. The independent AST
  interpreter still checks both against the specification.

## D-023 — Loop passes assume canonical (copy-propagated) IR

- **Date:** 2026-10-02 (Phase 4)
- **Context:** `bce` and `strength` recognise induction variables as
  `phi [init, pre], [phi + step, latch]`. Straight after SSA construction the latch value
  is a `copy`, so they do nothing (EXP-001: ratio 1.000).
- **Alternatives:** make IV detection look through copies; run copyprop inside these passes.
- **Chosen:** Keep the assumption, as LLVM passes assume `instcombine` has canonicalized the
  IR. Document it, and run copyprop before them in O2.
- **Why:** Each pass stays simple and single-purpose. The dependency is also a *real*
  phase-ordering effect for the ML/RL schedulers to discover, measured rather than designed
  away.
- **Trade-off:** A badly ordered pipeline wastes these passes. That is the problem learned
  scheduling is meant to address.

## D-024 — LICM hoists speculatively (no loop rotation); the measured downside is kept

- **Date:** 2026-10-02 (Phase 4)
- **Context:** EXP-001 found one generated program where LICM increased weighted cost
  1.87×. Hoisted instructions came from loop bodies that never execute (zero-trip loops).
- **Alternatives:**
  1. Loop rotation: guard the preheader with the loop condition, as LLVM does.
  2. Only hoist from blocks that execute on every iteration, plus constant trip counts ≥ 1.
  3. Keep classic speculative LICM.
- **Chosen:** Option 3 for now. Correctness is unaffected (only speculatable instructions
  move), and the geometric mean still improves (0.978).
- **Why:**
  - Rotation is a significant CFG transformation with its own correctness burden.
  - The phenomenon is a realistic profitability question ("is this loop likely to run?")
    that the learned schedulers can be evaluated on.
- **Revisit:** if native benchmarks (Phase 6) show LICM regressions on real kernels, implement
  rotation.

## D-025 — Inlining heuristic: size threshold 40, never recursive

- **Date:** 2026-10-02 (Phase 4)
- **Chosen:** Inline any call to a non-recursive callee of at most 40 static instructions. Any
  function on a call-graph cycle is excluded, which guarantees termination.
- **Why:** This is the simplest heuristic that is safe and useful. The constant is named
  (`INLINE_THRESHOLD`), so later experiments can vary it.
- **Measured trade-off (EXP-001):** static size grows 1.52× on the examples, cost drops 3.9%,
  and the worst case is slightly worse (1.012).

## D-026 — Emit textual LLVM IR; verify with llvmlite; build with zig cc

- **Date:** 2026-10-02 (Phase 5)
- **Alternatives:** llvmlite's `ir` builder API; the LLVM C API via ctypes; generating C
  instead of LLVM IR.
- **Chosen:** Plain textual LLVM IR, parsed and verified by `llvmlite.binding`, then compiled
  and linked by `zig cc` together with a small C runtime.
- **Why:**
  - Textual IR is easy to read in tests and docs, and it diffs well.
  - The ForgeCompile → LLVM mapping is visible in one table-like function.
  - Generating C would hide the SSA/phi structure and add C's own undefined behaviour.
  - zig cc gives clang's code generation and a linker from pip alone.
- **Trade-off:** Text generation can produce invalid IR, which is mitigated by verifying every
  module. One subprocess per build costs about 0.3 s.

## D-027 — Checked operations as `internal alwaysinline` helpers; 1:1 block mapping

- **Date:** 2026-10-02 (Phase 5)
- **Alternatives:** split ForgeCompile blocks and emit inline compare and branch code for every
  division and bounds check.
- **Chosen:** Small LLVM helper functions (`__fc_sdiv`, `__fc_srem`, `__fc_boundscheck`) that
  trap through the C runtime. Division by a constant other than 0 or −1 emits a plain
  `sdiv`/`srem`.
- **Why:**
  - Keeping one LLVM block per IR block means phi labels never need rewriting, which is a
    common source of backend bugs.
  - LLVM inlines the helpers at any optimization level above 0.
- **Trade-off:** At LLVM `-O0` each check is a real call. This makes ForgeCompile-only
  measurements pessimistic for checks that ForgeCompile does not remove. That is honest: the
  checks *are* the cost of MiniLang's safety, and `bce` exists to remove them.

## D-028 — Experiments isolate ForgeCompile optimizations with LLVM `-O0`

- **Date:** 2026-10-02 (Phase 5)
- **Chosen:** `--llvm-opt` defaults to 0. Benchmarks report ForgeCompile pipelines at LLVM
  `-O0`, and separately report LLVM `-O1..3` as baselines.
- **Why:** At `-O2`, LLVM's own GVN/LICM/inlining would redo or undo ForgeCompile's work, and
  any measured difference would mostly reflect LLVM. The project must not claim LLVM's wins as
  its own.
- **Consequence:** Absolute native speed at `-O0` is far from what a production compiler
  achieves. Results are about *relative* effects of ForgeCompile's decisions.

## D-029 — Runtime errors and output formatting in a C runtime; binary stdout on Windows

- **Date:** 2026-10-02 (Phase 5)
- **Chosen:** `fc_runtime.c` provides `print` for each type and the trap functions. NaN and
  infinity spellings are fixed explicitly, and finite floats use `printf("%.6f")` after a
  4,022-value comparison with Python. Windows stdout is put in binary mode.
- **Why:** These are the points where native behaviour most easily diverges from the
  interpreter (`-nan`, `1.#INF`, CRLF), so they are pinned down in one small, readable file.

## D-030 — Reference AST interpreter runs in a large-stack worker thread

- **Date:** 2026-10-02 (Phase 5)
- **Context:** The corner-case program recurses 5,000 deep. The AST interpreter uses about 6
  Python frames per MiniLang call and hit the recursion limit (F-012).
- **Chosen:** Run it in a thread with a 200 MiB stack and a raised recursion limit. Remaining
  overflows raise `InterpreterLimitExceeded` instead of crashing.
- **Why:** The oracle must handle what native code and the IR interpreter handle. An explicit
  stack (as in the IR interpreter) would make the reference interpreter much less readable.
- **Platform note:** CPython on Windows rejects thread stacks ≥ 256 MiB.

## D-031 — Two instance sizes per benchmark (interpreter-small, native-large)

- **Date:** 2026-10-02 (Phase 6)
- **Context:** The IR interpreter runs about 10⁶ IR instructions per second. Native runs need
  about 10⁸–10⁹ to dominate process startup and timer noise. A single size cannot serve both.
- **Alternatives:**
  - measure only natively (no deterministic signal);
  - measure only the interpreter (no ground truth);
  - JIT the interpreter (a big project).
- **Chosen:** One `// @size small=N large=M` annotation per benchmark, rewriting only the
  repetition count. The *ratios* between configurations are compared across sizes.
- **Trade-off:** This assumes per-repetition work is independent of the repetition count. That
  is true by construction, except for constant setup code, which the small instance amplifies
  a little.

## D-032 — Timing protocol: correctness gate, warm-up, interleaved seeded order, medians

- **Date:** 2026-10-02 (Phase 6)
- **Chosen:**
  - Before timing, check every configuration's output.
  - One warm-up run, then `repeats` rounds with a freshly shuffled (seeded) order.
  - Report the median, minimum, IQR and CV, plus the startup baseline.
- **Why:** Each element addresses a measured or well-known problem:
  - first-run antivirus cost (F-014);
  - drift bias from running configurations in blocks;
  - outliers;
  - silently benchmarking a miscompiled program.
- **Trade-off:** Longer runs, since every configuration pays for its warm-up and repeats.

## D-033 — Code size measured as `.text` bytes of the module object (via llvmlite)

- **Date:** 2026-10-02 (Phase 6)
- **Alternatives:** executable size; IR instruction count only.
- **Chosen:** Emit an object file for the LLVM module at the configuration's LLVM optimization
  level and sum the executable-code sections (`is_text()`).
- **Why:** Executable size is dominated by libc and the runtime, which are identical for every
  configuration. IR size is reported too, but machine-code size is what actually ships.

## D-034 — Server-first execution; GitHub is the canonical repository (supersedes D-005)

- **Date:** 2026-10-02 (Phase 6→7)
- **Context:**
  - D-005 kept all work on the laptop and did not use the server without authorization.
  - The project owner has now explicitly asked for server-first execution.
  - A laptop benchmark run was killed under critical memory pressure (F-015).
- **Chosen:**
  - **Workflow:** laptop (development) → git → GitHub (`rsoumyadeep/ForgeCompile`, canonical) →
    server clone/pull → experiments → curated results committed → GitHub → laptop pull.
    The server filesystem is never the source of truth.
  - **Server** (a shared lab machine): 64 hardware threads, 503 GB RAM, 2× RTX A6000 (shared with other
    users), Ubuntu 22.04, `/data` 96% full. An isolated uv environment
    (`~/ForgeCompile/.venv`, Python 3.11.16, `uv sync --locked`) is used, touching no other
    project.
  - **Access:** a dedicated key (`forgecompile-laptop-key`), installed once using the
    provided password. The password is never stored in the repository or printed.
  - **GPUs are not used.** The models (scikit-learn, NumPy DQN) are CPU-only by design (D-039).
- **Resource policy, enforced in code:**
  - `scripts/resources.py` checks free RAM, load, GPUs and busy processes, and recommends at
    most half the idle CPUs and 25% of free RAM.
  - `scripts/server/launch.sh` refuses duplicates, dirty trees and low memory, and runs jobs in
    tmux with continuous logs in `~/forge_logs/`.
  - Experiments run sequentially, never several heavy ones at once. Each starts with a tiny
    `--sanity` run (separate experiment id, no curated output), then medium, then full.

## D-035 — Experiment runs fail loudly and stay on disk

- **Date:** 2026-10-02
- **Chosen:** `ExperimentRun` is a context manager. Any exception inside `with run:` marks the
  run `failed`, with the error, and preserves its directory. Runs killed externally are marked
  `aborted` by hand, with the cause. Neither is ever used as evidence.

## D-036 — The ML/RL training workload profile has no deliberate traps

- **Date:** 2026-10-03 (Phase 7 validation)
- **Context:** The new dataset validator (`scripts/validate_dataset.py`, EXP-007) found that
  `LOOP_HEAVY` inherited the differential-testing trap rate (0.02 per index or divisor).
  About 10% of training programs (30/300 seeds) trapped at run time.
- **Alternatives:**
  - (a) Keep them, since a trap is legitimate observable behaviour.
  - (b) Filter out trapping seeds after generation.
  - (c) Set `trap_probability=0.0` in the training profile only.
- **Chosen:** (c). The default profile used by the correctness tests keeps its traps.
- **Why:**
  - A trapping program's cost counts only the work done before the trap. Its "speedup" is
    therefore an artefact of where the trap sits.
  - The trap also pins down which code a pass may move or delete, which no realistic workload
    shares.
  - (b) would make the set of seeds depend on the interpreter.
  - (c) keeps the RNG stream identical: `chance()` still draws. Programs therefore differ only
    at the former trap sites.
- **Consequence:**
  - Every dataset built before this commit is stale. Only sanity runs existed, and the cache
    key includes the commit.
  - Programs that print nothing (about 1%) are kept and reported. Deleting their dead work is
    a correct optimization, not a reward exploit, because the observable behaviour (exit
    status) is still checked.

## D-037 — Dataset cache keyed by the compiler's source tree, not the commit

- **Date:** 2026-10-03
- **Context:** The cache key included the git commit, so every documentation or
  experiment-script commit forced a full dataset rebuild (about 10 minutes for 600 programs)
  in each later experiment.
- **Chosen:**
  - The key is the configuration plus `git rev-parse HEAD:src/forgecompile`, i.e. the tree
    hash of the compiler package.
  - Nothing is cached while that tree has uncommitted changes.
- **Why:** Labels are a function of the compiler's code and the configuration only. Keying on
  exactly that input keeps the cache correct and stops needless rebuilds.
- **Trade-off:** A behaviour change that lives outside `src/forgecompile` would not invalidate
  the cache. Today that set is empty: the benchmark kernels used as OOD programs live in
  `benchmarks/`, but the dataset reads them through the package, and their text is part of the
  dataset content, not the key. If they change, delete `experiments/data/`. That rule is
  written in HOW_TO_RUN.md.

## D-038 — Worker counts above the resource script's default cap

- **Date:** 2026-10-03
- **Context:** `scripts/resources.py` caps its recommendation at 8 workers by default. The
  server had about 48 idle hardware threads (another user's jobs held about 15) and 494 GB of
  free RAM. Dataset workers use under 0.5 GB each.
- **Chosen:** Interpreter-based experiments (dataset builds, ablations, DQN seeds) may use up
  to 16 parallel processes, after the sanity runs and the resource check.
- **Constraint:** Native **timing** experiments (EXP-002/003/008) still run alone, with no
  other heavy job of ours running, because parallel load would add timing noise.

## D-039 — The DQN is implemented in NumPy; no deep-learning framework

- **Date:** decided when Phase 9 was drafted (2026-10-02). Recorded 2026-10-03, during the
  documentation audit, because no entry existed.
- **Context:** D-007 allowed PyTorch in Phase 9 "if used at all". The agent needs a small MLP,
  Adam, a replay buffer and a target network.
- **Alternatives:**
  - PyTorch, which brings autograd and GPU support.
  - Stable-Baselines3, which brings a ready-made DQN.
  - NumPy by hand.
- **Chosen:** NumPy by hand (`rl/dqn.py`). The 74 → 128 → 128 → 12 MLP has a hand-written
  backward pass that a test checks against numerical gradients.
- **Why:**
  1. The network is tiny. The training bottleneck is the environment (compiling, then
     interpreting the program), so a GPU would be idle.
  2. It saves a dependency of about 2 GB.
  3. Every line can be explained in an interview, with no framework magic.
  4. Stable-Baselines3 would hide exactly the parts worth understanding.
- **Trade-offs:**
  - Larger architectures (e.g. GNNs over the IR) would need a framework.
  - Hand-written gradients need tests: `test_mlp_backward_matches_numerical_gradient`.

## D-040 — What "dirty" means in run metadata

- **Date:** 2026-10-03
- **Context:**
  - Experiments write their curated results into `experiments/EXP-*/` when they finish.
  - In a chain of runs, those new untracked files made every later run report
    `dirty: true` under `git status --porcelain`, although the code was exactly the commit.
- **Chosen:** a run is dirty if a *tracked* file is modified, or if anything (tracked or
  untracked) is uncommitted under `src/`.
- **Why:** the flag answers "does this commit describe the code that ran?". Untracked files
  under `src/` could be imported, so they count. New result files cannot change behaviour.
- **Unchanged:** `scripts/server/launch.sh` still refuses to *start* on any uncommitted change,
  including untracked files.
