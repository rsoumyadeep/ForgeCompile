# Results

Only measured results appear here. Each one is linked to its experiment in
[EXPERIMENTS.md](EXPERIMENTS.md) and to a curated results directory with full metadata (git
commit, clean/dirty flag, environment, seed). Negative results are included.

## Summary: the ten research questions

| # | Question | Answer (evidence) |
|---|---|---|
| 1 | Does ML-guided scheduling beat fixed pipelines? | **No.** The supervised model loses to O2 on interpreter cost (0.580 vs 0.558, EXP-005) and ties within noise natively (0.855 vs 0.850, EXP-008). |
| 2 | Does RL beat heuristic scheduling? | **No.** DQN is worse than O2, the supervised model and the greedy oracle on every program group (EXP-006). A no-retry wrapper and 4× training do not change that (EXP-012). |
| 3 | On which workload classes does it help? | Only where the proxy misleads O2: model and DQN are 32% faster than O2 natively on `loop_nest` and 8% on `arith_hash`, because they avoid strength reduction (EXP-008). They are 12–17% worse on stencil, sieve and memory_sort. |
| 4 | When does it fail? | Out of distribution (EXP-004: no better than the majority baseline). On passes absent from training (`bce`: 0 training labels). Through compounding greedy errors (EXP-005). When the action gap is tiny (DQN repeats no-op passes, EXP-006). |
| 5 | Does quality justify the inference overhead? | **No.** Decision time is 3 ms (DQN) to 93 ms (model) to 12 s (oracle) per program, against 2.3 ms for O2's *entire* pass pipeline on the kernels, with no native gain (EXP-008). |
| 6 | Does the learned policy generalize to unseen programs? | To unseen generated programs, partly (regret 4.4× below majority, EXP-004). To hand-written kernels, no (OOD regret ≈ majority). |
| 7 | How sensitive is it to the benchmark distribution? | Asymmetric. Training on the richer `loop_heavy` profile transfers to `default`; the reverse costs 6% end to end (EXP-009). |
| 8 | What happens when the action space changes? | It matters more than anything else tested. Removing copyprop hurts even the oracle (benchmarks 0.856 vs 0.741). A smaller action space (O1) halves DQN's gap to its oracle (EXP-010). |
| 9 | How much training data is required? | Very little. The learning curve is flat from 25 to 400 programs (EXP-009). |
| 10 | What happens when reward weights change? | λ and γ barely matter. A code-size weight works as intended: static size ratio 0.36 vs 0.43 at no cost penalty (EXP-010). |

**Why the answers are mostly negative:**
- Even beam search over all 12-pass schedules finds only about 1% headroom above O2 on the
  interpreter cost (EXP-011).
- That cost is itself only weakly aligned with native time: Spearman 0.29 (EXP-002).
- Pass *scheduling* in this compiler is a second-order effect. ForgeCompile O2 is 1.18× faster
  than no passes at LLVM -O0, while LLVM -O2 is 7.4× faster (EXP-003).

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

## EXP-004 — Next-pass prediction from static IR features (Phase 7)

**Setup:** 400/100/100 generated programs (2,966/736/734 states) + 17 hand-written OOD programs
(113 states); model selected on validation regret; commit `94b3649`. Data:
`experiments/EXP-004-pass-prediction/`.

| split | model | mean regret | near-optimal | accuracy |
|---|---|---:|---:|---:|
| test | gradient boosting (selected) | **0.0152** | 0.620 | 0.525 |
| test | majority class | 0.0670 | 0.290 | 0.213 |
| OOD | gradient boosting | 0.0277 | 0.513 | 0.327 |
| OOD | majority class | **0.0269** | 0.478 | 0.248 |

- In distribution, the model has 4.4× lower regret than the majority baseline.
- **Out of distribution it is no better than the majority baseline.** The main cause is
  coverage: `bce` is the best pass in 10 of 113 OOD states but never in training, because the
  generator never emits induction-variable array indexing.

## EXP-005 — End-to-end ML-guided scheduling vs fixed pipelines (Phase 7–8) — negative result

**Setup:** greedy application of the EXP-004 model, budget 12 passes, all outputs checked;
geomean final/initial interpreter cost. Data: `experiments/EXP-005-ml-scheduling/`.

| policy | generated test (100) | benchmarks (10) | examples (7) | decision ms / program |
|---|---:|---:|---:|---:|
| oracle-greedy (upper bound for greedy) | 0.553 | 0.741 | 0.825 | 2,650 |
| **O2** | **0.558** | **0.741** | **0.828** | 0 |
| model (GBDT) | 0.580 | 0.815 | 0.867 | 1,086 |
| frequency order | 0.582 | 0.747 | 0.838 | 0 |
| best of 3 random 12-pass schedules | 0.571 | 0.829 | 0.871 | 0 |

- **The learned scheduler does not beat O2. It is 4% worse on generated programs and 10% worse
  on benchmarks, at about 1 s of decision time per program.**
- O2 is within 1% of the greedy oracle, so the headroom for any one-step-greedy policy is about
  1%.
- O2 beats the greedy oracle on 9/100 programs, which is evidence that some gains need
  lookahead (EXP-006).

## EXP-006 — Double DQN pass scheduling (Phase 9) — negative result

**Setup:** 3 seeds × 3,000 episodes on 400 training programs; best checkpoint chosen on 40
validation programs; held-out evaluation with outputs checked. Commit `039d03b`. Data:
`experiments/EXP-006-rl-scheduling/` (including checkpoints and training curves).

| policy | generated test (100) | benchmarks (10) | examples (7) | decision ms |
|---|---:|---:|---:|---:|
| oracle-greedy | 0.553 | 0.741 | 0.825 | 2,153 |
| **O2** | **0.558** | **0.741** | **0.828** | 0 |
| supervised model | 0.580 | 0.815 | 0.867 | 420 |
| DQN (seeds 0 / 1 / 2) | 0.632 / 0.660 / 0.641 | 0.894 / 0.956 / 0.952 | 0.967 / 0.963 / 0.967 | 25–39 |

- **DQN does not beat O2, the supervised model or the greedy oracle on any program group.** All
  three seeds agree.
- There were 0 invalid transformations.
- Diagnosed failure: the policies repeat one no-op pass (e.g. `licm` ×12). The −0.002 per-step
  penalty is a smaller action gap than the Q-function's error. The DQN also lacked the supervised
  policy's no-retry rule; that follow-up is EXP-012.

## EXP-011 — Headroom: how much better than O2 can any 12-pass schedule be? (Phase 10)

**Setup:** beam search over pass sequences (widths 1/4/16, budget 12, best-at-any-depth, IR-hash
deduplication), on 100 test + 17 OOD programs. Measurement only. Commit `dbabcbf`. Data:
`experiments/EXP-011-headroom/`.

| programs | O2 | beam-1 (greedy) | beam-4 | beam-16 |
|---|---:|---:|---:|---:|
| generated (100) | 0.558 | 0.552 | 0.552 | **0.552** |
| benchmarks (10) | 0.741 | 0.741 | 0.741 | 0.741 |
| examples (7) | 0.828 | 0.825 | 0.825 | 0.825 |

- **The best schedules that beam search finds are only about 1% better than O2 on average**
  (0% on the hand-written kernels). They are > 1% better on 22/100 generated programs (up to
  12%), and never worse.
- The learnable headroom in this action space is therefore tiny. That is the main reason the
  supervised (EXP-005) and RL (EXP-006) schedulers cannot beat O2.

## EXP-012 — DQN follow-up: equal wrappers and 4× training (Phase 9) — negative result

**Setup:** EXP-006 checkpoints re-evaluated with the supervised policy's no-retry rule (Part A).
Then 3 seeds × 12,000 episodes, selected on validation with that rule (Part B). Commit
`e37527c`. Data: `experiments/EXP-012-dqn-followup/`.

| policy (generated test, geomean cost ratio) | plain | + no-retry |
|---|---:|---:|
| O2 | 0.558 | — |
| EXP-006 DQN (seeds 0/1/2) | 0.632 / 0.660 / 0.641 | 0.609 / 0.625 / **0.589** |
| scaled DQN, 4× training (seeds 0/1/2) | 0.650 / 0.679 / 0.681 | 0.604 / 0.632 / 0.631 |

- The no-retry rule closes 31%, 34% and 63% of DQN's gap to O2 (seeds 0, 1, 2).
- **4× more training does not help:**
  - the best validation checkpoints came from episodes 100, 1,800 and 1,800 of 12,000;
  - scaled agents are no better than the EXP-006 agents.
- No DQN variant beats O2. There were 0 invalid transformations in about 350k training steps.

## EXP-009 — Supervised-scheduler ablations: features, data, distribution (Phase 10)

**Setup:** EXP-004 protocol per condition (selection on validation), plus end-to-end greedy
scheduling; 17 conditions; commit `e37527c`. Data: `experiments/EXP-009-ml-ablations/`.

| question | finding |
|---|---|
| Which features matter? | They are highly redundant. Dropping any one group barely moves test regret (0.0127–0.0152). The hand-made `opportunities` group *alone* recovers 96% of the regret reduction over majority. On validation, dropping it hurts most. |
| How much data? | **Flat learning curve.** 25 programs (188 states) give regret 0.0149 vs 0.0152 with 400 programs; there is no monotonic trend. |
| Distribution shift? | **Asymmetric.** `loop_heavy` → `default` transfers well (regret 0.0097, better than the in-distribution `default` model's 0.0117). `default` → `loop_heavy` costs 6% end to end (0.616 vs 0.580). |
| Beats O2 anywhere? | **No.** Best end-to-end 0.572 vs O2 0.558 (`loop_heavy`) and 0.513 vs 0.505 (`default`). OOD: 7–17% worse than O2. |

## EXP-010 — RL formulation ablations: reward, discount, action space (Phase 10)

**Setup:** 7 conditions × 2 seeds × 2,000 episodes; evaluated plain and with no-retry; references
O2 and oracle-greedy restricted to each action space; commit `e37527c`. Data:
`experiments/EXP-010-rl-ablations/`.

| question | finding (generated test, geomean cost ratio) |
|---|---|
| Does a larger step penalty help (λ 0.002 → 0.01)? | **No** (0.650 vs 0.646, mean of seeds). λ = 0 is slightly worse (0.673). |
| Does discounting matter (γ 1 → 0.9)? | **No** (< 1% change). |
| Does a size term steer the agent (w_size = 0.5)? | **Yes:** static size ratio 0.359 vs 0.428 at no cost penalty. |
| Does the action space matter? | **Yes.** Without copyprop, even the greedy oracle drops (0.565 vs 0.553; benchmarks 0.856 vs 0.741). With only the O1 passes, DQN gets much closer to its oracle (≈ 9% vs ≈ 17%). |
| Does any variant beat O2 (0.558)? | **No.** Best 0.601. The no-retry wrapper helps in all 14 trainings (1.6–9.5%). |

EXP-010's base condition reproduced EXP-006's seeds 0 and 1 bit-exactly: identical validation
scores and test ratios.

## EXP-002 — Does the interpreter cost predict native speedups? (Phase 6) — mostly no

**Setup:** 13 ForgeCompile pipelines × 10 kernels at LLVM -O0, 5 interleaved repeats, correctness
gate; server; commit `7ff2e07`. A new run replaces the aborted laptop attempt (F-015). Data:
`experiments/EXP-002-cost-model/`.

| predictor | pooled Spearman | pooled Pearson |
|---|---:|---:|
| weighted interpreter cost (the RL/ML reward) | **0.286** | 0.325 |
| raw dynamic instruction count | 0.308 | 0.378 |

| pipeline | predicted ratio (geomean) | measured native ratio (geomean) |
|---|---:|---:|
| O2 | 0.741 | **0.849** (faster beyond noise on 6 kernels, e.g. matmul 0.668; memory_sort, call_fib and loop_nest within noise; arith_hash reproducibly 1.088) |
| licm | 0.871 | 1.004 |
| strength | 0.942 | 1.008 (worst 1.190) |
| simplifycfg | 0.985 | 0.913 |

- ForgeCompile O2 gives a real **~15% native speedup at LLVM -O0**, but the cost model ranks
  outcomes only weakly.
- The cost model overrates loop-code motion (licm, strength) and underrates branch removal.
- The latency weights add nothing over plain instruction counts.
- Every learned-scheduler result measured with this proxy (EXP-004–012) must be read as a
  statement about the proxy. EXP-008 re-measures the schedules natively.

## EXP-003 — ForgeCompile vs LLVM's optimizer, and reproducibility (Phase 6)

**Setup:** 5 configurations × 10 kernels × 7 repeats, run twice back to back; server; commit
`7ff2e07`. **Speedups** vs fc-O0 + LLVM -O0 (higher is better). Data:
`experiments/EXP-003-fc-vs-llvm/`.

| configuration | geomean speedup (run 1 / run 2) | `.text` size vs fc-O0 |
|---|---:|---:|
| fc-O1 + LLVM -O0 | 1.135 / 1.128 | — |
| **fc-O2 + LLVM -O0** | **1.178 / 1.170** | **0.870** |
| fc-O0 + LLVM -O2 | 7.36 / 7.32 (4.67 without the closed-form loop_nest) | — |
| fc-O2 + LLVM -O2 | 7.48 / 7.36 | **0.911** (vs fc-O0 + LLVM -O2) |

- **Reproducibility:** the median run-to-run difference of the medians is 0.53% (p90 2.7%), so
  the noise band for claims is about 3%. Phase 6 acceptance is met.
- ForgeCompile O2 is a real native win at LLVM -O0: +18% geomean, up to 1.50× on matmul,
  reproducibly −8% on the latency-bound arith_hash.
- LLVM -O2 subsumes it for run time (ratio 1.016, within noise). ForgeCompile O2 still makes
  the final code **8.9% smaller** after LLVM -O2.

## EXP-008 — Learned schedules measured natively (Phase 10)

**Setup:** every policy schedules each of the 10 kernels (small instance), and the large
instance is compiled with that exact pass list at LLVM -O0 and timed with the Phase 6 protocol
(10 repeats). Commit `7ff2e07`. Data: `experiments/EXP-008-native-policies/`.

| policy | native time vs fc-O0 (geomean) | `.text` size | decision ms |
|---|---:|---:|---:|
| frequency order | 0.837 | 0.929 | 0 |
| **O2** | **0.850** | **0.870** | 0 |
| supervised model | 0.855 | 0.969 | 93 |
| greedy oracle (best on the proxy) | 0.861 | 1.019 | 12,447 |
| best DQN (EXP-012 + no-retry) | 0.945 | 0.912 | 8 |
| *LLVM -O2 alone (reference)* | *0.137* | *0.604* | — |

- **Natively, no learned scheduler beats O2 beyond the ~3% noise band.** O2 also produces the
  smallest code.
- The proxy's blind spot: strength reduction looks good on the interpreter but slows LLVM -O0
  code. Policies that rarely use it (model, DQN) are 32% faster than O2 on `loop_nest` while
  worse on the proxy. This is an accident of a misaligned objective, not learned insight.
- Decision time alone (3 ms to 12 s) exceeds O2's entire pass time on these kernels (2.3 ms).
