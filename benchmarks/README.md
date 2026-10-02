# Benchmarks

Ten MiniLang kernels covering the workload classes required by the project. The class is the
file-name prefix.

| Benchmark | Class | What it stresses | Optimization opportunities |
|-----------|-------|------------------|----------------------------|
| `arith_hash` | arithmetic | multiply/add/constant-modulo integer mixing | constant folding; division by constants |
| `branch_classify` | branch | data-dependent if/else chains on a pseudo-random sequence | simplifycfg, sccp |
| `loop_nest` | loop | triple loop with invariant arithmetic and IV multiplies | licm, strength, copyprop (LLVM -O2 closes it into a formula) |
| `memory_sieve` | memory | sieve of Eratosthenes on a bool array, re-zeroed every repetition | bounds checks on `a[i]` (bce) and `a[j]` (not removable) |
| `memory_sort` | memory | insertion sort: data-dependent loads/stores | bounds checks on non-IV indices |
| `call_fib` | call | naive recursive Fibonacci | call overhead (recursive, so never inlined) |
| `call_helpers` | call | small helpers in a hot loop | inline, then constant propagation and CSE |
| `vector_saxpy` | vector | element-wise float array ops, dot product | bce, licm |
| `matrix_matmul` | matrix | 40×40 float matmul with 2-D arrays | strength (`i*C`), licm (row offsets), bce, cse |
| `matrix_stencil` | matrix | 48×48 five-point Jacobi stencil | cse of row offsets; `i±1` checks stay |

## Size annotation

Each file has exactly one line of the form

```
let reps = 10; // @size small=1 large=4000
```

The runner rewrites that literal:
- **`small`** is used for IR-interpreter measurements. These are deterministic, at roughly 10⁶
  IR instructions per second in Python.
- **`large`** is used for native timing. It is chosen so the fastest configuration runs
  ≳ 0.1 s, far above the ~5 ms process startup. `loop_nest` is the exception: LLVM -O2
  computes it in closed form.

Only the repetition count changes, never array sizes. Arrays live on the 1 MiB Windows main
stack, so they are kept small.

## Running

```bash
uv run forgecompile bench                                   # all benchmarks, 5 default configs
uv run forgecompile bench --benchmarks arith_hash --repeats 7
uv run forgecompile bench --config "mine=copyprop,bce@0" --config "base=O0@0"
uv run forgecompile bench --no-native                       # interpreter metrics only
```

Every run first checks **correctness**: each configuration's native and interpreted outputs
on the small instance must match the reference. It then times the large instance with
interleaved, seeded run orders after a warm-up. Results go to
`experiments/runs/<EXP-ID>_<time>/` (`results.json`, `summary.csv`, `summary.md`).
