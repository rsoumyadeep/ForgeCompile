# LLVM Backend

ForgeCompile compiles MiniLang to native executables through LLVM:

```
MiniLang ─► AST ─► SSA IR ─► ForgeCompile passes ─► LLVM IR text ─► llvmlite verify
        ─► zig cc (clang + lld + libc) + fc_runtime.c ─► native executable
```

```bash
uv run forgecompile llvm examples/gcd.mini                  # LLVM IR as emitted
uv run forgecompile llvm --llvm-opt 2 examples/gcd.mini     # ...after LLVM's own -O2 (inspection)
uv run forgecompile build -O 2 -o gcd.exe examples/gcd.mini # executable (LLVM -O0 by default)
uv run forgecompile run --engine native -O 2 --llvm-opt 2 examples/gcd.mini
```

Code: `src/forgecompile/backend/llvm_emitter.py`, `backend/native.py`,
`backend/runtime/fc_runtime.c`.

## 1. What ForgeCompile implements vs what LLVM provides

This split is the key to interpreting any performance number in this project.

| Stage | Who | Notes |
|-------|-----|-------|
| Lexing, parsing, type checking | ForgeCompile | Phases 1–2 |
| IR design, lowering, SSA construction | ForgeCompile | Phase 3 |
| **All optimizations studied in this project** (11 passes, scheduling, ML/RL) | ForgeCompile | Phase 4 onward; they run *before* LLVM sees the code |
| Translation to LLVM IR | ForgeCompile | nearly 1:1 notation change (§2), no optimization decisions |
| LLVM IR parsing and verification | LLVM (llvmlite) | catches emitter bugs |
| Instruction selection, register allocation, scheduling, machine code | LLVM (via clang in `zig cc`) | always, even at `-O0` |
| LLVM IR optimization (inlining, GVN, LICM, vectorization, ...) | LLVM | **only if `--llvm-opt` > 0**; off by default |
| Linking, C library | lld + zig's bundled libc | |
| Output formatting and runtime errors | ForgeCompile C runtime (`fc_runtime.c`) | defines the observable behaviour |

**The default is LLVM `-O0`.** Experiments that measure ForgeCompile's passes compile the
result with `--llvm-opt 0`, so LLVM contributes code generation but **no** IR optimization.
`--llvm-opt 1..3` produces the "what would LLVM do" comparison baselines (D-028).
`forgecompile llvm --llvm-opt 2` shows LLVM's optimized IR. In the gcd example, LLVM turns our
inlined checked-remainder helper into a `switch` on the divisor, which is a concrete example of
something LLVM adds.

## 2. Translation rules

| ForgeCompile IR | LLVM IR | Why |
|-----------------|---------|-----|
| `i64` `f64` `i1` `ptr` | `i64` `double` `i1` `ptr` | opaque pointers (LLVM ≥ 15) |
| `add/sub/mul` | `add/sub/mul` **without** `nsw` | MiniLang ints wrap. `nsw` would make overflow poison and let LLVM assume it never happens. |
| `sdiv/srem x, c` (c ≠ 0, −1) | `sdiv/srem` | safe divisor |
| other `sdiv/srem` | `call @__fc_sdiv/@__fc_srem` | division by zero must trap, and `INT_MIN / -1` is UB in LLVM but defined (wraps) in MiniLang |
| `fcmp ne` | `fcmp une` | NaN ≠ NaN is *true* in MiniLang/IEEE/Python; `one` would be wrong |
| other `fcmp` | `fcmp oeq/olt/ole/ogt/oge` | ordered |
| `fptosi` | `@llvm.fptosi.sat.i64.f64` | saturating with NaN → 0. A plain `fptosi` out of range is poison. |
| `frem` | `frem` | C `fmod` semantics |
| `copy` | *(nothing)* | uses are forwarded to the source value; LLVM has no copy instruction |
| `alloca T, n` / `load p[i]` / `store` | `alloca T, i64 n` / `getelementptr T` + `load`/`store` | element-indexed |
| `ptradd p, k, T` | `getelementptr T, ptr p, i64 k` | this is why `ptradd` carries its element type |
| `memzero p, T, n` | `@llvm.memset.p0.i64(p, 0, n·sizeof(T))` | |
| `boundscheck i, n` | `call @__fc_boundscheck(i, n)` | one unsigned compare covers `i < 0` and `i ≥ n` |
| `print` | `call @fc_print_{i64,f64,bool}` | C runtime; bool widened to `i32` for a clean C ABI |
| `phi/br/jump/ret/unreachable` | same | blocks map 1:1 |

The checking helpers are `internal alwaysinline` functions in the emitted module. They are
not branches emitted inline because:
- ForgeCompile basic blocks then map **1:1** to LLVM blocks, so phi predecessor labels never
  need rewriting;
- LLVM inlines them anyway at any optimization level above 0.

**Names:**
- registers become `%v.<name>`;
- labels become `b.<label>`;
- address temporaries become `%a.<n>`;
- functions become `@mini_<name>`.

LLVM locals and labels share one namespace, so a user variable named `entry` would collide
with the `entry` block. User functions named `abs`, `sqrt` or `printf` would collide with libc
symbols. `tests/programs/semantics_edge.mini` covers both cases.

## 3. Runtime (`fc_runtime.c`)

The runtime is about 60 lines of C, linked into every executable. It defines observable
behaviour exactly as the IR interpreter does:

- `print(int)` uses `%lld`. `print(bool)` prints `true`/`false`. `print(float)` uses
  `printf("%.6f")`, except that NaN is always `nan` and infinities are `inf`/`-inf`, because
  C libraries disagree on these spellings (`-nan`, `1.#INF`).
- Runtime errors flush stdout (partial output is observable behaviour), print
  `runtime error: <message>` to stderr, and `exit(101)`.
- On Windows, stdout is switched to binary mode. Otherwise every `\n` becomes `\r\n` and
  native output would differ from the interpreters.
- The C `main` wrapper calls `mini_main` and returns its result `& 255`, which equals
  Python's `r % 256` in two's complement.

**Floating-point formatting check.** Before relying on `printf("%.6f")`, I compared it with
Python's `f"{x:.6f}"` on **4,022 values**: specials, subnormals, 1e300, 4,000 random bit
patterns and random magnitudes, plus `%lld` extremes. The C library linked by `zig cc` on
Windows (UCRT, correctly rounding) gave **0 mismatches**. Older Windows CRTs (msvcrt) are
known to differ for large values, so this was worth checking rather than assuming.

## 4. Toolchain (`backend/native.py`)

- The compiler is `python -m ziglang cc` (the pip-installed `ziglang` wheel, D-002), or
  `clang` if the environment variable `FORGECOMPILE_CC=clang` is set and clang is on PATH.
- Command: `zig cc -O<llvm_opt> -Wno-override-module program.ll fc_runtime.c -o program[.exe]`.
- The first build on a machine compiles zig's libc into its cache, which takes about 70 s.
  After that, builds take about 0.3 s.
- Executables run with captured *bytes*, so there is no newline translation, and the exit
  code is masked to 32 bits for Windows.

## 5. Validation

| Check | Scope | Result |
|-------|-------|--------|
| llvmlite verification | every emitted module in tests (examples, edge cases, 60 generated programs at O0/O2) | passes |
| Examples vs golden output | ForgeCompile O0/O2 × LLVM O0/O2 | identical |
| Semantic corner cases (`semantics_edge.mini`, 42 outputs + exit 44) | AST interpreter, IR interpreter, native LLVM -O0 and **-O3** | byte-identical |
| Runtime errors (div, rem, bounds) | exit 101, partial stdout, stderr message | identical to interpreters |
| Generated programs, random pass sequences, random LLVM level | 12 per test run + 120 under `-m slow` (plus 360 during development) | 0 mismatches |

The `-O3` corner-case run is the important one. If the emitter had leaked undefined behaviour
(`nsw`, plain `fptosi`, unchecked `INT_MIN / -1`), LLVM's optimizer would be entitled to
change the output, and that test would catch it.

## 6. Limitations

- Tiny programs cannot measure generated-code speed. A *warm* process start costs about
  5 ms on the development laptop (measured by `forgecompile bench`). The *first* run of a
  freshly built executable took 50–90 ms, most likely because Windows scans new binaries
  on first execution (FAILURES F-014). The benchmark runner therefore always does a
  warm-up run, and Phase 6 sizes kernels so computation dominates.
- No debug info, and no separate compilation or linking of multiple MiniLang files.
- 64-bit x86 Windows is tested. Linux is supported by the same code path (zig/clang + glibc),
  and CI runs on Ubuntu, but it has not been run locally.
- Stack depth is the OS default (1 MiB main thread on Windows). Very deep recursion can
  overflow natively before the interpreter's limits apply. 5,000 levels are tested.
