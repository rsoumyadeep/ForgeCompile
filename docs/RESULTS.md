# Results

Only measured results appear here. Each one is linked to its experiment in
[EXPERIMENTS.md](EXPERIMENTS.md) and to a curated results directory with full metadata (git
commit, clean/dirty flag, environment, seed). Negative results are included.

## EXP-001 — Per-pass effects on IR-level work (Phase 4)

**Setup:** 7 example programs and 200 generated programs (seeds 0–199). Metrics come from the
deterministic IR interpreter: dynamic instruction count, and a weighted cost under *assumed*
latencies. These are **not** native runtimes; Phase 6 will measure those. Data:
`experiments/EXP-001-pass-effects/results.md` (run 2, commit `453feab`).

Geometric-mean ratio, optimized / unoptimized (lower is better):

| configuration | examples: cost | generated: cost | worst single program (generated) |
|---|---:|---:|---:|
| preset:O2 | **0.828** | **0.537** | 0.912 |
| preset:O1 | 0.942 | 0.576 | 0.932 |
| sccp | 0.995 | 0.622 | 0.963 |
| constfold | 0.995 | 0.627 | 0.963 |
| copyprop | 0.956 | 0.976 | 1.000 |
| copyprop+bce | 0.918 | 0.976 | 1.000 |
| inline | 0.961 | 0.991 | 1.012 (worse) |
| licm | 0.986 | 0.978 | **1.871 (worse)** |
| bce alone, strength alone | 1.000 | 1.000 | 1.000 |

**Main findings**

1. O2 is best on average on both workload groups.
2. **Phase ordering matters measurably.** `bce` and `strength` do nothing unless `copyprop`
   runs first.
3. **Negative result: LICM can make code worse.** One program got 1.87× more costly, because
   code was hoisted out of loops that never execute (speculation without loop rotation).
4. **Negative result: inlining increases static code size** by 52% on the examples, and can
   slightly increase work.
5. Effects depend strongly on the workload distribution. Constant folding dominates on
   generated programs, while copy propagation and loop passes matter on hand-written code.
6. The experiment itself found a missed-optimization bug in SCCP (F-010). The run-1 data
   showing it is kept.

## EXP-007 — The ML/RL training data are deterministic, leak-free and reproducible (Phase 7)

**Setup:** 137 programs (80/20/20 generated + 17 hand-written OOD), commit `46a5643`, server.
Data: `experiments/EXP-007-dataset-validation/report.json`.

| check | result |
|---|---|
| 1-worker vs 8-worker build | identical (SHA-256 `016551c9…`) |
| split disjointness (names and source text) | disjoint |
| trapping programs / programs without output | 0 / 0 |
| from-scratch replay: states, one-step outcomes | 179 states, 1,969 outcomes: all features, costs and outcomes identical; output preserved in every case |
| median initial cost, train vs OOD | 6.4k vs 307k |
| STOP share of labels, train vs OOD | 6% vs 21% |

The first (local) validation attempt found that 10% of training programs trapped; fixed by D-036.
