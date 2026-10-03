# Phase 6 Report — Benchmarking Infrastructure

**PHASE:** 6 — reproducible native benchmarking
**STATUS:** ✅ Complete (2026-10-03).
- The infrastructure was built in commit `2f952e2` (2026-10-02).
- Its two experiments were completed on the server after an aborted laptop attempt (F-015).
- The acceptance criterion (agreement within a measured noise band) is met: median run-to-run
  difference 0.53%.

## Implemented
- **10 benchmark kernels** (`benchmarks/*.mini`):
  - arithmetic, branch, loop, memory (×2), call (×2), vector, matrix (×2);
  - each with a small instance (interpreter) and a large one (native), differing only in the
    repetition count (D-031).
- **`benchmarking/` package:**
  - suite discovery;
  - static metrics: IR size, LLVM IR lines, `.text` bytes via llvmlite (D-033), pass time;
  - interpreter metrics: steps, weighted cost, opcode counts;
  - native build and timing;
  - statistics (median, minimum, IQR, CV, Spearman/Pearson);
  - Markdown/CSV reports.
- **Runner protocol (D-032):**
  1. correctness gate: native output equals interpreter output on the small instance;
  2. build once, warm up;
  3. interleaved, seeded rounds;
  4. a startup baseline (empty program);
  5. all large-instance outputs must agree.
- **`forgecompile bench` CLI** (custom configurations, `--no-native`).
- **Server execution tooling** (this session):
  - `scripts/resources.py`;
  - `scripts/server/launch.sh` (tmux, clean-tree and memory checks, thread caps per F-017);
  - `scripts/server/fetch_results.sh`;
  - load averages recorded in every run's metadata.

## Tests
`tests/benchmarking/test_benchmarking.py`, 12 tests: suite loading and size substitution,
statistics, correctness gate, report generation, the native path, and the CLI.

## Experiments
- **EXP-002** (interpreter cost vs native time):
  - pooled Spearman 0.286 and Pearson 0.325, so the cost model is a weak predictor;
  - raw instruction count is no worse than the weighted cost;
  - the loop passes (licm, strength) are overrated and simplifycfg underrated;
  - ForgeCompile O2 is 15% faster natively at LLVM -O0.
- **EXP-003** (vs LLVM, reproducibility):
  - fc-O2 1.18× at LLVM -O0 and LLVM -O2 7.4×;
  - fc-O2 adds nothing to LLVM -O2's run time but shrinks its code by 8.9%;
  - the two runs agree to a median of 0.53% (p90 2.7%).

## Results
See RESULTS.md (EXP-002, EXP-003).

## Important decisions
- D-028: measure ForgeCompile decisions at LLVM -O0.
- D-031: two instance sizes.
- D-032: timing protocol.
- D-033: `.text` bytes as code size.
- D-034: server-first execution.
- D-035: failed and aborted runs are preserved.
- D-038/D-040: worker policy and the meaning of "dirty".

## Problems encountered → how they were solved
- **F-014:** first-run cost was misattributed to process startup. Fixed by the warm-up run;
  warm startup is 5 ms on the laptop and 0.9 ms on the Linux server.
- **F-015:** a laptop run was killed under memory pressure. This led to server execution,
  resource checks, sanity runs, and aborted-run markers. The aborted run is preserved, and a
  *new* run supplied the evidence.
- **F-017:** thread oversubscription on the shared server. Fixed with thread caps.
- **Noise from a shared machine:** recorded loads, interleaving, CVs and a measured noise
  band. Effects under about 3% are not claimed.

## Known limitations
- One machine, shared with other users. Within-session reproducibility only.
- LLVM -O0 code generation is stack-heavy, so native effects of IR changes are muted and
  latency-dominated (arith_hash).
- Short LLVM -O2 runs (about 0.1 s) are noisy (CV up to 10%).
- Arrays are kept small: they must fit the 1 MiB Windows stack.

## Files changed (this session)
`scripts/server/*`, `scripts/resources.py` (unchanged), `utils/environment.py` (load averages,
dirty semantics), curated `experiments/EXP-002-cost-model/` and `experiments/EXP-003-fc-vs-llvm/`,
EXPERIMENTS.md, RESULTS.md, DEVELOPMENT.md, HOW_TO_RUN.md.

## Next phase
Phase 7 (already complete).
