# Phase 5 Report — LLVM Backend

**PHASE:** 5 — LLVM backend and native executables
**STATUS:** ✅ Complete (2026-10-02)

## Implemented
- **Dependencies:** `llvmlite` 0.50.0 (LLVM 22.1.0) and `ziglang` 0.16.0, added via `uv add`.
  No system compiler is needed.
- **LLVM emitter** (`backend/llvm_emitter.py`):
  - SSA IR → textual LLVM IR, with a 1:1 block mapping and copy forwarding;
  - UB-free lowering: no `nsw`, `fptosi.sat`, checked `sdiv`/`srem` helpers, `fcmp une`;
  - name prefixing (`%v.`, `b.`, `@mini_`);
  - a C `main` wrapper that returns `status & 255`;
  - `verify_llvm` (llvmlite);
  - `optimize_llvm`, which runs LLVM's own pipeline for inspection.
- **C runtime** (`backend/runtime/fc_runtime.c`): typed `print` (fixed `nan`/`inf`
  spellings), traps (flush stdout, stderr message, exit 101), and binary stdout on Windows.
  It is included in the wheel (verified).
- **Native toolchain** (`backend/native.py`): `zig cc` or clang, `compile_llvm`,
  `run_executable` (raw bytes), `build_and_run`.
- **IR change:** `ptradd` now records its element type, which GEP strides need.
- **Driver/CLI:**
  - `compile_to_llvm`;
  - `forgecompile llvm [--llvm-opt N]`;
  - `forgecompile build [-o] [--llvm-opt N] [--emit-llvm]`;
  - `forgecompile run --engine native [--llvm-opt N]`.
- **Reference interpreter:** runs in a large-stack worker thread (D-030, F-012).
- **Corner-case program** `tests/programs/semantics_edge.mini` with golden output: wrap-around,
  `INT_MIN / -1`, NaN/inf spelling, saturating casts, libc name clashes, row pointers, bool
  arrays, recursion depth 5,000, exit status 44.

## Tests
720 total (49 new in `tests/backend/`). `718 passed, 2 deselected (slow)` in the standard
run; the slow native test passes as well.
- `test_llvm_emitter.py` (no toolchain needed):
  - every example and the corner-case program, at O0/O2, verify;
  - 60 generated programs verify;
  - mapping rules: division lowering by divisor, `fcmp une`, exact hex floats,
    `fptosi.sat`, bool print, copy forwarding, name prefixing, the main wrapper;
  - verifier error reporting;
  - the LLVM optimizer runs.
- `test_native.py` (marked `native`):
  - examples vs golden output at (ForgeCompile O0, LLVM O0) and (O2, O2);
  - the corner-case program at LLVM O0, O3, and ForgeCompile O2 + LLVM O3;
  - runtime errors (stdout, exit 101, stderr message);
  - 12 generated programs with random pass sequences and LLVM levels, plus 120 under
    `-m slow`;
  - the CLI `build` and `run --engine native`.
- During development: 360 native builds (120 generated programs × 3 configurations) and
  28 example configurations, with 0 mismatches.

## Experiments
No formal experiment. A pre-implementation **compatibility check**: the C library's
`printf("%.6f")`/`%lld` was compared with Python's formatting on 4,022 values, with 0
mismatches. It decided the runtime design (LLVM_BACKEND.md §3).

## Results
No performance results. *(Correction added in Phase 6: the 50–90 ms below was measured on the
first run of freshly built executables. Warm startup is about 5 ms. See FAILURES F-014.)*
Native run times of the examples (50–90 ms) are dominated by process
startup and are **not** reported as results.

## Important decisions
D-026 textual LLVM IR + llvmlite verification + zig cc · D-027 checked-op helpers and 1:1
blocks · D-028 LLVM `-O0` isolates ForgeCompile's optimizations · D-029 C runtime and binary
stdout · D-030 large-stack thread for the AST interpreter.

## Problems encountered → how they were solved
- **F-012:** the AST interpreter overflowed at recursion depth 5,000. Fixed with a large-stack
  worker thread. The first attempt (512 MiB) hit CPython's < 256 MiB limit on Windows.
- **Design issue found during design:** `ptradd` lacked an element type, so derived pointers
  could not get correct LLVM GEP strides. Added the type to the IR, printer, parser, verifier
  and lowering.
- The first native build took about 70 s (zig building its libc cache). This is documented in
  HOW_TO_RUN.
- mypy: llvmlite and ziglang ship without type information. Handled with a scoped
  `ignore_missing_imports` override.

## Known limitations
- Process startup dominates tiny programs, so Phase 6 needs long-running kernels.
- Native code is only tested locally on Windows x86-64. Linux runs in CI.
- There is no debug info, and the native stack depth is the OS default.
- At LLVM `-O0`, checked operations are real calls (the pessimistic but honest cost of
  MiniLang's safety).

## Files changed
New: `backend/{__init__,llvm_emitter,native}.py`, `backend/runtime/fc_runtime.c`,
`cli/backend_commands.py`, `tests/backend/*`, `tests/programs/semantics_edge.{mini,expected}`.
Modified: `ir/{instructions,printer,parser,verify}.py` and `lowering.py` (ptradd element
type), `driver.py`, `cli/{main,ir_commands}.py`, `runtime/ast_interpreter.py`,
`pyproject.toml` / `uv.lock` (dependencies, mypy override), and docs: `LLVM_BACKEND.md`
(written), `THEORY.md` §11, `HOW_TO_STUDY.md` §11, `DECISIONS.md` (D-026–D-030),
`FAILURES.md` (F-012), `ARCHITECTURE.md`, `ROADMAP.md`, `HOW_TO_RUN.md`, `DEVELOPMENT.md`,
`README.md`.

## Commit
`phase-5: add LLVM backend, C runtime and native differential tests`

## Next phase
Phase 6: benchmarking infrastructure.
- Benchmark kernels covering arithmetic, branches, loops, memory, calls, vectors and matrices,
  sized for computation to dominate process startup.
- A runner with repeated timing, statistics and environment metadata.
- Code size, compile time, interpreter counts and pass statistics.
- **EXP-002:** does interpreter cost predict native runtime? (validating D-006).
