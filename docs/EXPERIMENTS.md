# Experiment Log

Every significant experiment is recorded here **before** it is run (objective, hypothesis,
method) and completed **after** (results, interpretation). Raw outputs live in
`experiments/runs/<ID>_<timestamp>/` (created by `forgecompile.utils.experiment.ExperimentRun`).
Curated results are copied to `experiments/<ID>/` and summarized in [RESULTS.md](RESULTS.md).

Rules:
- No value appears here unless it came from a run directory that can be pointed to.
- Test-set results are computed once per final configuration. No tuning on the test set.
- Negative and null results are recorded with the same care as positive ones.

## Template

```
## EXP-NNN — <question>
- Date:
- Objective:
- Hypothesis:
- Configuration:          (config file / CLI command)
- Dataset / workloads:
- Environment:            (machine; see run metadata.json)
- Method:
- Baseline:
- Metrics:
- Results:                (link to run directory)
- Interpretation:
- Failure modes:
- Next action:
```

## Planned research questions (Phase 10)

1. Does ML-guided scheduling improve over fixed optimization pipelines?
2. Does RL improve over heuristic scheduling?
3. On which workload classes does it help?
4. When does it fail?
5. Does the optimization quality justify the inference overhead?
6. Does the learned policy generalize to unseen programs?
7. How sensitive is it to the benchmark distribution?
8. What happens when the action space changes?
9. How much training data is required?
10. What happens when the reward weights change?

Where each question is answered:

| # | Experiment(s) |
|---|---|
| 1 | EXP-005 (interpreter cost), EXP-008 (native time, code size) |
| 2 | EXP-006, EXP-008 |
| 3 | EXP-008 (per benchmark and workload class), EXP-005 (generated vs hand-written) |
| 4 | EXP-004 OOD diagnosis, EXP-005/006 worst cases, EXP-008 per-benchmark slowdowns |
| 5 | decision ms in EXP-005/006/008 vs measured savings |
| 6 | test split (unseen generated programs) and OOD split in EXP-004/005/006 |
| 7 | EXP-009 distribution conditions (train on one generator profile, test on another) |
| 8 | EXP-010 action-space conditions |
| 9 | EXP-009 data-size conditions |
| 10 | EXP-010 reward conditions (λ, γ, w_size) |

## Experiments

## EXP-001 — Effect of each pass and preset on IR-level work

- **Date:** 2026-10-02 (pre-registered before the measured run)
- **Objective:** Quantify what each Phase 4 pass does on its own, and what the presets
  do. This gives an evidence-based baseline for the ML/RL phases: which passes matter,
  and which depend on others.
- **Hypotheses.** Honesty note: H1, H2 and H4 were formed *after* informal exploratory runs
  during pass development (`scripts/fuzz_passes.py` printed per-pass dynamic counts). They
  are therefore not blind predictions. H3 and H5 were not examined beforehand.
  - H1: `copyprop` gives the largest standalone reduction in dynamic instructions, because
    lowering emits a copy for every assignment.
  - H2: `bce` and `strength` have *no* standalone effect. They only find induction variables
    after copy propagation (a phase-ordering dependency).
  - H3: `preset:O2` reduces weighted cost more than any single pass, on both groups.
  - H4: `inline` leaves dynamic instruction counts unchanged (call/ret become jumps) but
    reduces weighted cost.
  - H5: The effects are much smaller on generated programs than on examples, because
    generated programs have few loops (D-020).
- **Configuration:** `experiments/EXP-001-pass-effects/run.py --generated 200 --seed 0
  --repeats 3`. Configurations: each of the 11 passes alone; presets O1 and O2; and
  `copyprop+{bce,strength,licm}`.
- **Workloads:** the 7 example programs, and generated programs with seeds 0–199. The two
  groups are reported separately.
- **Environment:** development laptop (see the run's `metadata.json`).
- **Method:**
  - Build SSA IR, apply the configuration, and run it on the IR interpreter.
  - Every optimized run is asserted to match the unoptimized output.
  - Per program, compute the ratio optimized / unoptimized. Report the geometric mean over
    programs, plus the best and worst cost ratio.
  - Compile time is the median of 3 repeats (wall-clock, noisy; secondary metric).
- **Baseline:** unoptimized SSA IR (no passes).
- **Metrics:** dynamic IR instruction count (excluding phis); weighted cost (assumed
  latencies, not yet validated; see D-006); static instruction count; compile time.
- **Threats to validity:**
  - Interpreter cost is not native runtime. Phase 6 measures the relationship.
  - Generated programs are not representative of real code.
  - The examples are only 7 small programs.
- **Runs:**
  - *Run 1:* commit `6f13055` (clean). Results in
    `experiments/EXP-001-pass-effects/results_run1_before_sccp_fix.{md,json}` and
    `metadata_run1.json`.
  - *Run 2:* commit `453feab` (clean), after fixing F-010. Results in
    `experiments/EXP-001-pass-effects/results.{md,json}` and `metadata.json`. Raw run
    directories are under `experiments/runs/` (git-ignored).
- **Results** (run 2; geometric-mean ratio optimized/unoptimized; lower is better; selected
  rows, full table in `results.md`):

  | configuration | examples cost | generated cost | examples steps | generated steps | worst cost (gen) |
  |---|---:|---:|---:|---:|---:|
  | copyprop | 0.956 | 0.976 | 0.855 | 0.859 | 1.000 |
  | constfold | 0.995 | 0.627 | 0.988 | 0.514 | 0.963 |
  | sccp | 0.995 | 0.622 | 0.988 | 0.502 | 0.963 |
  | dce | 1.000 | 0.948 | 1.000 | 0.886 | 1.000 |
  | licm | 0.986 | 0.978 | 0.985 | 0.974 | **1.871** |
  | inline | 0.961 | 0.991 | 1.000 | 1.001 | 1.012 |
  | bce / strength (alone) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
  | copyprop+bce | 0.918 | 0.976 | 0.820 | 0.859 | 1.000 |
  | preset:O1 | 0.942 | 0.576 | 0.829 | 0.360 | 0.932 |
  | preset:O2 | **0.828** | **0.537** | **0.737** | **0.294** | 0.912 |

- **Interpretation, by hypothesis:**
  - **H1: partially supported.** On the examples, copyprop is the best single pass by dynamic
    instruction count (0.855). On generated programs, constfold and sccp are far stronger
    (about 0.5) because the generator is constant-heavy (D-020), and copyprop is only third.
  - **H2: supported.** bce and strength alone have exactly zero effect. After copyprop, bce
    cuts example cost from 0.956 to 0.918. A real phase-ordering dependency.
  - **H3: supported.** O2 has the lowest geometric-mean cost on both groups. On generated
    programs its best case equals O1's (0.143), because the big wins there come from constant
    folding, which both presets include. O2's later `constfold` also hid the F-010 SCCP bug:
    O2's numbers are identical in runs 1 and 2.
  - **H4: supported.** inline leaves dynamic counts unchanged (call/ret become jumps), lowers
    cost (examples 0.961), and grows static size by 1.52× on the examples. It can be slightly
    harmful (worst 1.012), because hoisted callee allocas run even when the call does not.
  - **H5: not supported as stated.** Effects on generated programs are *larger*, not smaller,
    because they are dominated by constant folding of generator-produced constant
    expressions. Loop passes do have smaller effects there (bce: 1.000 even after copyprop).
- **Unexpected findings:**
  1. **LICM can hurt badly.** Worst generated case: cost ×1.871. Investigated (seed 55): the
     hoisted `frem`/`fdiv` came from loop bodies that never execute, i.e. speculative
     hoisting out of zero-trip loops. The mean is still a gain (0.978). Recorded as D-024.
  2. **Run 1 showed constfold beating sccp** (0.627 vs 0.712 cost on generated), which
     contradicts the theory that SCCP finds a superset of constants. Investigation found an
     SCCP bug (F-010): dead divisions with known-constant divisors were kept, and in-range
     constant bounds checks were never folded. After the fix (run 2), sccp edges out
     constfold (0.622 vs 0.627), as expected. Only sccp's rows changed between the runs.
- **Failure modes:**
  - Every optimized run reproduced the unoptimized output: the script asserts this for every
    program and configuration.
  - No pass made any program fail.
  - Compile times are a few milliseconds per pipeline in Python and are noisy (median of 3).
- **Next action:**
  - Phase 6 must test whether interpreter cost predicts native runtime. If it does not, these
    rankings may not transfer.
  - The LICM downside and the copyprop→bce dependency are concrete targets for ML/RL
    scheduling (Phases 7–9).

## EXP-002 — Does the interpreter cost model predict native speedups?

- **Date:** 2026-10-02 (pre-registered before the run)
- **Objective:** Validate (or refute) DECISIONS D-006. The ML/RL phases want a cheap,
  deterministic reward. Is the IR-interpreter cost a usable proxy for native runtime?
- **Hypotheses** (stated before the run):
  - H1: The predicted cost ratio and the measured native ratio are positively rank-correlated
    across (benchmark, pipeline) pairs (pooled Spearman > 0.5).
  - H2: Weighted cost predicts better than raw dynamic instruction count.
  - H3: Correlation is weaker for passes whose savings are cheap natively (`strength`,
    `inline`), where the assumed weights exaggerate them.
- **Configuration:** `experiments/EXP-002-cost-model/run.py --repeats 5 --seed 0`.
  - 13 pipelines (O0, O1, O2, and single passes, with copyprop prepended for passes that need
    canonical IR), all at LLVM -O0 (D-028).
  - 10 benchmarks (`benchmarks/*.mini`).
  - Small instance for the interpreter, large instance for native timing.
- **Method:**
  - The runner's correctness gate checks native vs interpreter output.
  - One warm-up run, then 5 interleaved timed runs per configuration.
  - Ratios are taken against O0 per benchmark. Spearman and Pearson correlation are computed
    pooled and per benchmark.
- **Baseline:** perfect prediction would give Spearman = 1. No predictive power gives ≈ 0.
- **Metrics:** Spearman and Pearson correlation; per-point predicted vs measured ratios; CV of
  the timings.
- **Threats to validity:**
  - Laptop timing noise (CV is reported per point).
  - The ratios assume per-repetition work is size-independent. Only the repetition count
    differs between the small and large instances.
  - LLVM -O0 code generation (stack-heavy) differs from optimized code.
- **Runs:**
  - **First attempt (laptop, 2026-10-02): aborted** at benchmark 8/10 because of system memory
    pressure (F-015). Run directory `EXP-002-cost-model_20261002T130843234531Z`, status
    `aborted`. Not evidence.
  - Server sanity run (2 benchmarks, 2 repeats, commit `a253566`): not evidence.
  - **Evidence run:** new run `EXP-002-cost-model_20261003T134911906982Z`, commit `7ff2e07`,
    server (EPYC 7513, shared; load average about 20–30 from other users), full pre-registered
    configuration (13 pipelines × 10 benchmarks × 5 repeats, LLVM -O0). It took 15 min.
    Startup baseline: 0.9 ms. Curated results are in `experiments/EXP-002-cost-model/`.
- **Results** (120 points; ratios vs fc-O0 per benchmark; lower is better):
  - Pooled Spearman (cost vs measured) **0.286**, Pearson 0.325.
  - Raw dynamic instruction count: Spearman 0.308, Pearson 0.378.
  - Per-benchmark Spearman (cost):
    - arith_hash −0.16, loop_nest −0.26;
    - matrix_matmul 0.18, call_fib 0.28, branch_classify 0.33;
    - vector_saxpy 0.49, matrix_stencil 0.52, memory_sieve 0.56, memory_sort 0.59,
      call_helpers 0.65.
  - Timing noise: median CV 2.5%, maximum 11.4% (branch_classify).

  | pipeline | predicted (geomean) | measured native (geomean) | worst measured |
  |---|---:|---:|---:|
  | O2 | 0.741 | **0.849** | 1.088 (arith_hash) |
  | O1 | 0.925 | 0.882 | 1.028 |
  | licm | 0.871 | 1.004 | 1.051 |
  | strength | 0.942 | 1.008 | **1.190** |
  | cse | 0.948 | 1.007 | 1.106 |
  | bce | 0.906 | 0.960 | 1.017 |
  | simplifycfg | 0.985 | **0.913** | 1.033 |
  | inline | 0.961 | 0.985 | 1.056 |
  | copyprop / dce / sccp / constfold | 0.956 / 0.956 / 0.985 / 0.985 | 0.993 / 0.973 / 0.989 / 0.997 | ≤ 1.042 |

  O2 per benchmark (predicted → measured):
  - matmul 0.609 → 0.668, saxpy 0.856 → 0.698, stencil 0.658 → 0.739, sieve 0.839 → 0.754;
  - call_helpers 0.597 → 0.788, branch_classify 0.949 → 0.859, memory_sort 0.902 → 0.989;
  - call_fib 1.000 → 1.001, **loop_nest 0.362 → 1.029, arith_hash 0.938 → 1.088**.
- **Hypotheses.**
  - **H1 rejected:** pooled Spearman 0.286 < 0.5. The interpreter cost ranks native outcomes
    only weakly, and on two kernels the correlation is *negative*.
  - **H2 rejected:** the latency-weighted cost predicts no better than the raw instruction
    count (0.286 vs 0.308 Spearman). The assumed weights add nothing.
  - **H3 supported in a sharper form:**
    - The worst mispredictions are the loop passes: `licm` (predicted −13%, measured +0.4%)
      and `strength` (predicted −6%, measured +0.8%, worst +19%).
    - `cse` is also badly mispredicted. `inline` is only moderately off.
    - The cost model *underestimates* `simplifycfg` (predicted −1.5%, measured −8.7%).
- **Interpretation:**
  1. **ForgeCompile O2 makes native code about 15% faster at LLVM -O0** (geomean, 7 of 10
     kernels faster, up to 1.5× on matmul), but less than the interpreter predicts (26%).
  2. The model fails where the cost of an IR instruction depends on code generation. At LLVM
     -O0 every value lives in a stack slot, so removing or hoisting cheap register arithmetic
     saves little, and LICM and strength reduction add loop-carried values (extra stack
     traffic).
  3. Latency-bound loops (`arith_hash`: a chain of divisions) do not speed up when
     off-critical-path instructions disappear.
  4. Removing branches and jumps (simplifycfg) is worth more natively than one "instruction"
     each.
  5. **Consequence for Phases 7–10:** every learned scheduler optimized a proxy that is only
     weakly aligned with native time. EXP-008 measures the learned schedules natively. The
     interpreter-level conclusions (EXP-005/006/011) are statements about the proxy and must
     be read that way.
- **D-006 status:** the deterministic interpreter cost was kept as the training signal
  (exact, cheap, reproducible), with this documented limitation. A learned or native-time cost
  model is listed as future work.

## EXP-003 — ForgeCompile pipelines vs LLVM's optimizer, and reproducibility

- **Date:** 2026-10-02 (pre-registered before the run)
- **Objective:** Measure, natively:
  1. what ForgeCompile's presets achieve on their own (LLVM -O0);
  2. what LLVM -O2 achieves;
  3. whether ForgeCompile O2 adds anything on top of LLVM -O2;
  4. the run-to-run noise band (acceptance criterion of Phase 6).
- **Hypotheses:**
  - H1: LLVM -O2 is much faster than any ForgeCompile pipeline at LLVM -O0, because LLVM adds
    register allocation quality, instruction selection and vectorization that ForgeCompile
    does not attempt.
  - H2: fc-O2 at LLVM -O0 is faster than fc-O0 at LLVM -O0 on most benchmarks.
  - H3: fc-O2 + LLVM -O2 ≈ fc-O0 + LLVM -O2. LLVM redoes the same classical optimizations.
  - H4: Two runs agree within about 5% median relative difference.
- **Configuration:** `experiments/EXP-003-fc-vs-llvm/run.py --repeats 7 --seeds 0 1`
  (5 configurations, 10 benchmarks, 2 full runs).
- **Results / interpretation:** below, after the run.

## EXP-007 — Validation of the training-data generator (run before any model is trained)

- **Date:** 2026-10-03
- **Objective:** Establish that the ML/RL dataset is deterministic, leak-free and made of
  real, reproducible measurements, before any model is fit on it.
- **Method:** `scripts/validate_dataset.py`. The checks are listed in its docstring:
  determinism across worker counts, name and source disjointness of splits, program validity,
  record invariants, from-scratch replay of features and outcome tables, and output
  preservation of every replayed state and one-step outcome.
- **First attempt (local smoke run):** the validator stopped at once. Generated program
  `gen100002` traps, and about 10% of the training workload trapped (30/300 seeds). This led
  to D-036 (trap-free training profile). Datasets from before D-036 exist only as sanity runs.
- **Configuration (server, commit `46a5643`):** `--n-train 80 --n-val 20 --n-test 20
  --workers 8 --replay 24` (137 programs, 8 steps, ε = 0.3, seed 0). This is a medium-sized
  dataset. The full one (600 programs) is built by EXP-004 with the same code.
- **Results** (curated: `experiments/EXP-007-dataset-validation/`): all checks passed.
  - The 1-worker and 8-worker builds are byte-identical (same SHA-256). The parallel build was
    only 2.2× faster (379 s → 176 s): a few long OOD programs dominate the critical path.
  - Splits are disjoint by name and by source text. There are 0 trapping programs and 0
    programs without output.
  - The replay recomputed 179 states and 1,969 one-step outcomes from scratch. Features, costs
    and the complete outcome tables matched exactly, and every outcome preserved the program's
    output.
  - 1,021 records; mean trajectory length 7.45 of 8; 43/137 trajectories end in STOP.
  - **Distribution difference:** OOD programs are about 50× more expensive (median initial
    cost 307k vs 6.4k for train), and their labels differ. STOP is 21% of OOD labels vs 6% of
    train labels, and `bce`/`strength` appear mostly on OOD. Generated programs are dominated by
    `simplifycfg`, `dce`, `copyprop` and `sccp`.
- **Interpretation:** the labels are reproducible measurements and the splits are clean. The
  OOD split is genuinely out of distribution. That is its purpose, and it predicts that
  learned policies will transfer imperfectly.

### Pipeline sanity check (2026-10-03, laptop, commit `52a6abb`)

`uv run python scripts/e2e_sanity.py` runs every stage once on 10 generated programs (seed 0),
each with an assertion. All 8 stages passed in 31 s:

1. compile `gen100008` (2 functions, cost 6,761);
2. extract its 61 features;
3. build 24 train / 6 test oracle-labelled records;
4. fit a random forest (test regret 0.0048, accuracy 0.67);
5. let the model schedule 12 passes (cost 6,761 → 4,749);
6. compile natively, with output identical to the unoptimized interpreter run;
7. take one environment step (observation of size 74, reward +0.41 for `sccp`);
8. train DQN for 10 episodes (79 steps, 0 invalid transformations).

Two behaviours to watch in the full runs:
- the model policy cycles `simplifycfg/copyprop/simplify`;
- the barely-trained DQN repeats no-op passes until the horizon instead of choosing `stop`.

These are tiny-data results and are **not evidence** for any hypothesis.

## EXP-004 — Can a model predict the best next pass from static IR features?

- **Date:** 2026-10-03 (pre-registered before the full run; sanity runs only before this)
- **Hypotheses:**
  - H1: The selected model's test mean regret is below half that of the majority-class
    baseline.
  - H2: Tree ensembles (RF/GBDT) beat the decision tree and the MLP on validation regret,
    because the features are heterogeneous counts.
  - H3: On OOD (hand-written) programs the regret advantage shrinks. Their label distribution
    differs (copyprop-dominated in the sanity data, versus sccp/constfold on generated code).
- **Configuration:** `experiments/EXP-004-pass-prediction/run.py --workers 8` with 400/100/100
  generated programs (seeds 100000–100599, `LOOP_HEAVY`, trap-free per D-036), 17 OOD programs,
  8 steps, ε = 0.3 and model seed 0.
- **Metrics:** mean regret (primary), near-optimal rate, accuracy and top-2 accuracy.
- **Rule:** the model is selected on validation regret, and test/OOD are each scored once.
- **Runs:**
  - The first full run (commit `d051986`) **failed**: the dataset build crashed with
    `BrokenProcessPool`, caused by F-016 (unparseable register names). The run is preserved as
    failed and is not evidence.
  - The second run (commit `94b3649`, server, 16 workers) completed. Building the dataset
    took 245 s, and the whole run took 5 min.
- **Data:** 400/100/100 generated programs and 17 OOD programs, giving 2,966 / 736 / 734 / 113
  state records. Curated results are in `experiments/EXP-004-pass-prediction/`.
- **Results.**

  | model (validation) | accuracy | top-2 | mean regret | near-optimal |
  |---|---:|---:|---:|---:|
  | gradient boosting | 0.485 | 0.689 | **0.0148** | 0.573 |
  | random forest | 0.516 | 0.701 | 0.0150 | 0.601 |
  | MLP | 0.443 | 0.663 | 0.0195 | 0.519 |
  | decision tree | 0.418 | 0.530 | 0.0224 | 0.511 |
  | majority | 0.204 | 0.268 | 0.0554 | 0.265 |

  Gradient boosting was selected, refitted on train + val, and scored once:

  | split | model | accuracy | top-2 | mean regret | near-optimal |
  |---|---|---:|---:|---:|---:|
  | test (734 states) | gradient boosting | 0.525 | 0.719 | **0.0152** | 0.620 |
  | test | majority | 0.213 | 0.304 | 0.0670 | 0.290 |
  | OOD (113 states) | gradient boosting | 0.327 | 0.602 | 0.0277 | 0.513 |
  | OOD | majority | 0.248 | 0.292 | **0.0269** | 0.478 |

- **Hypotheses.**
  - **H1 supported:** test regret is 4.4× lower than the majority baseline.
  - **H2 supported:** both ensembles beat the single tree and the MLP on validation. GBDT and
    RF are effectively tied (0.0148 vs 0.0150).
  - **H3 supported, more strongly than predicted:** on OOD the model's regret advantage
    *disappears entirely* (0.0277 vs 0.0269).
- **Why OOD fails (diagnosis, from the label counts):**
  1. **`bce` is never a training label** (0 of 2,966), but it is the best pass in 10 of 113 OOD
     states. The generator always indexes arrays as `((e % n) + n) % n`, so generated code
     never has a check that `bce` can prove safe. The model cannot learn an action whose
     benefit never occurs in training data. This is a *coverage* gap in the workload
     generator, not a model failure.
  2. STOP is 21% of OOD labels vs 5% of train labels. Hand-written kernels reach a fixed point
     sooner.
  3. OOD programs are about 50× larger (EXP-007), which moves the size features outside the
     training range.
- **Feature importance** (random-forest impurity, biased toward groups with many features):
  opcodes 0.57, opportunities 0.18, cfg 0.08, size 0.06, loops 0.06, memory 0.04, calls 0.02.
  The causal test is the EXP-009 ablation.
- **Next action:** EXP-005 asks whether the model helps *end to end*. EXP-009 measures feature
  groups and distribution shift.

## EXP-005 — Does ML-guided scheduling beat fixed pipelines end to end?

- **Date:** 2026-10-03 (pre-registered)
- **Hypotheses:**
  - H1: On generated test programs the model policy reaches a lower geomean cost ratio than O2.
  - H2: Oracle-greedy ≤ model. The model recovers at least half of the gap between O2 and
    oracle-greedy.
  - H3: On OOD programs the model does *not* beat O2. O2 was hand-designed for code like
    the OOD set.
  - H4: The model's decision overhead (feature extraction + inference) is ≥ 10× smaller than
    oracle-greedy's, but not negligible next to running a pass.
- **Configuration:** same dataset as EXP-004. Budget of 12 passes. Policies: O1, O2,
  random-k12 × 3 seeds, frequency, model, oracle-greedy. Every final program's output is
  checked.
- **Metrics:** geomean final/initial interpreter cost, best and worst ratio, passes, decision
  ms, schedule ms. Native runtime is measured separately for the benchmark kernels (EXP-002
  covers the cost↔native relation).
- **Run:** commit `94b3649`, server. Same cached dataset as EXP-004. Every final program's
  output was checked (0 mismatches). Curated results are in `experiments/EXP-005-ml-scheduling/`.
- **Results** (geomean final/initial interpreter cost; lower is better):

  | policy | generated test (100) | benchmarks (10) | examples (7) | size ratio (all) | passes | decision ms |
  |---|---:|---:|---:|---:|---:|---:|
  | oracle-greedy | **0.553** | **0.741** | **0.825** | 0.320 | 7.1 | 2,650 |
  | O2 | 0.558 | **0.741** | 0.828 | **0.288** | 12.0 | 0 |
  | random-k12 (seeds 0/1/2) | 0.571 / 0.600 / 0.624 | 0.856 / 0.829 / 0.850 | 0.919 / 0.919 / 0.871 | 0.34–0.43 | 12.0 | 0 |
  | model (GBDT) | 0.580 | 0.815 | 0.867 | 0.343 | 8.1 | 1,086 |
  | frequency | 0.582 | 0.747 | 0.838 | 0.361 | 11.0 | 0 |
  | O1 | 0.602 | 0.925 | 0.942 | 0.397 | 5.0 | 0 |

- **Hypotheses.**
  - **H1 rejected:** the model is *worse* than O2 on generated test programs (0.580 vs 0.558).
    It was worse than O2 by > 1% on 35 programs and better on 12.
  - **H2 rejected:** the model does not close the O2 → oracle gap; it lands outside it.
  - **H3 supported:** on hand-written programs the model is 10% (benchmarks) and 5% (examples)
    worse than O2.
  - **H4 rejected:** the model's decisions cost 1.1 s per program, only 2.4× cheaper than the
    oracle; the model's total schedule time is 12× that of O2 (1,166 vs 96 ms).
- **Diagnosis** (per-program analysis of `outcomes.json`):
  1. **There is almost no headroom.** O2 is within 1.0% of the greedy oracle on generated
     programs and identical to it on benchmarks. A one-step-greedy learner can gain at most
     about 1% over O2 here.
  2. **Regret wins did not turn into schedule wins.**
     - The model is > 1% worse than the oracle on 43/100 programs while using as many passes
       (8.1 vs 8.2), so the problem is not stopping early.
     - It under-selects `licm`: the first action was `licm` 3 times, against 19 times for the
       oracle.
     - It omits late `simplify`/`cse`/`constfold` clean-ups.
     - Small per-step regrets compound over 8–12 greedy steps. This is exactly why per-decision
       accuracy is not compiler performance.
  3. **O2 beats the greedy oracle on 9 of 100 programs.** A fixed order sometimes wins through
     lookahead, which is evidence of non-greedy structure. That is the gap RL can target
     (EXP-006).
  4. **Where the overhead comes from:**
     - feature extraction takes about 4 ms;
     - a single-row `predict_proba` of scikit-learn's HistGradientBoosting (200 iterations ×
       12 classes = 2,400 trees) takes 24–50 ms on the server, depending on OpenMP threads;
     - IR hashing and Python overhead make up the rest.

     A compiled tree ensemble would be far cheaper. That was not done, and the reported
     overhead is what was measured. It does not change the conclusion: even at zero overhead
     the model loses to O2 on quality.
- **Interpretation (negative result):**
  - In this compiler, with 11 passes and a 12-pass budget, the hand-written O2 pipeline is
    already near the greedy optimum.
  - A supervised imitation of the greedy oracle with 61 static features is measurably worse
    than O2, and much more expensive.
  - The project's honest answer to research question 1 at the interpreter-cost level is **no**.
- **Next action:**
  - EXP-006 asks whether RL's lookahead finds the non-greedy wins in (3).
  - EXP-008 checks the same policies on native time.

## EXP-006 — Does a DQN agent beat greedy and fixed baselines?

- **Date:** 2026-10-03 (pre-registered)
- **Hypotheses:**
  - H1: DQN (best validation checkpoint) beats O2 on generated test programs.
  - H2: DQN does **not** beat oracle-greedy by a meaningful margin (> 1% geomean). EXP-001
    suggests most gains are available greedily, and lookahead is needed only for enabling
    pairs like copyprop→bce.
  - H3: DQN vs the supervised model: no prediction; this is the question.
  - H4: Zero invalid transformations during training and evaluation.
- **Configuration:** `experiments/EXP-006-rl-scheduling/run.py --episodes 3000 --seeds 0 1 2`.
  Horizon 12, λ = 0.002, γ = 1, warm-up 500, Double DQN 2 × 128, checkpoint selected on 40
  validation programs every 100 episodes.
- **Metrics:** as EXP-005, plus the training curves (return, cost ratio, ε, loss, validation
  geomean).
- **Runs:**
  - A sanity run at `039d03b` (2 seeds × 40 episodes) exercised the new parallel-seed code
    end to end.
  - The full run: commit `039d03b`, server, 3 seeds in parallel processes. Each seed took
    about 24 min of training (32k environment steps), plus evaluation. The machine load
    average was 30–38 from another user's jobs. Curated results, including checkpoints and
    per-episode training curves, are in `experiments/EXP-006-rl-scheduling/`.
- **Training:**
  - Best validation geomean per seed: 0.690, 0.695 and 0.691.
  - Validation stops improving after about 1,300 episodes, and the training-episode cost ratio
    only moves from about 0.745 (first 500 episodes) to about 0.71 (last 500).
  - Invalid transformations: 0, 0, 0.
- **Results** (held out; geomean final/initial cost; lower is better):

  | policy | generated test (100) | benchmarks (10) | examples (7) | size ratio (all) | passes | decision ms |
  |---|---:|---:|---:|---:|---:|---:|
  | oracle-greedy | 0.553 | 0.741 | 0.825 | 0.320 | 7.1 | 2,153 |
  | O2 | 0.558 | 0.741 | 0.828 | 0.288 | 12.0 | 0 |
  | model (GBDT) | 0.580 | 0.815 | 0.867 | 0.343 | 8.1 | 420 |
  | DQN seed 0 | 0.632 | 0.894 | 0.967 | 0.503 | 9.3 | 25 |
  | DQN seed 2 | 0.641 | 0.952 | 0.967 | 0.448 | 11.8 | 39 |
  | DQN seed 1 | 0.660 | 0.956 | 0.963 | 0.442 | 11.9 | 36 |

  The oracle, O2 and model rows reproduce EXP-005 exactly, which confirms that the
  evaluation is deterministic. The model's decision time differs (420 vs 1,086 ms) only
  because of machine load and OpenMP thread contention.
- **Hypotheses.**
  - **H1 rejected:** no DQN seed beats O2. DQN is 13–18% worse on generated programs and
    21–29% worse on benchmarks.
  - **H2 holds trivially:** DQN is far from the greedy oracle.
  - **H3 (open question) answered:** DQN is clearly worse than the supervised model.
  - **H4 supported:** 0 invalid transformations in training and evaluation.
- **Diagnosis** (per-program actions in `outcomes.json`):
  - **The policies degenerate into repeating one pass.** Seed 0 applies `licm` 533 times on
    100 programs, e.g. `licm × 12` on `gen100502`. Seed 1 repeats `simplifycfg`, seed 2
    `copyprop`. There are about 600 immediate repeats per seed, against 0 for the oracle.
  - After the first application a repeat is a no-op whose true value is
    Q(s, best) − λ, with λ = 0.002. That *action gap* is far smaller than the network's
    approximation error, so the greedy argmax falls on near-ties. The agent also rarely
    chooses `stop`: mean passes are 9–12.
  - Learning is sample-limited:
    - 32k transitions, about 80 per training program;
    - ε reaches its floor after only about 550 episodes;
    - each transition carries one action's outcome, while each supervised record carries all
      11 (EXP-004).
- **Methodological note found in the analysis:**
  - The supervised `ModelPolicy` has a "never retry a pass in an unchanged state" rule
    (`ml/policies.py`). `DQNPolicy` did not, so the wrappers were not equal.
  - EXP-006 is kept exactly as pre-registered and run.
  - The fair-wrapper comparison and a scaled-up training run are the pre-registered
    follow-up EXP-012.
- **Reproducibility (update):**
  - This run predates the per-process thread caps (F-017), so NumPy's BLAS may have run
    multithreaded. I first noted that retraining might differ in the last digits.
  - EXP-010's `base` condition then retrained seeds 0 and 1 under single-threaded BLAS and
    reproduced this run **bit-exactly**: identical best validation scores and test ratios.
  - The caveat does not apply in practice. These matrices are too small for BLAS to split
    across threads.
- **Next action:** EXP-012 (no-retry wrapper for DQN, validated on validation programs first,
  then 4× more training). EXP-010 (λ, γ, action space) tests whether a larger action gap
  (λ = 0.01) helps.

## EXP-011 — Headroom: how much better than O2 can any 12-pass schedule be?

- **Date:** 2026-10-03 (pre-registered; added after EXP-005, which motivated it)
- **Objective:**
  - EXP-005 showed O2 within 1% of the *greedy* oracle. That bounds one-step learners only.
  - Beam search over pass sequences (widths 1, 4, 16; budget 12; best cost at any depth;
    states deduplicated by IR hash) estimates how much any scheduler *with lookahead* could
    gain.
  - Beam search measures only. It is neither trained nor tuned, and it uses the test and OOD
    programs only as measurement targets.
- **Hypotheses:**
  - H1: beam-1 reproduces EXP-005's oracle-greedy ratios (sanity).
  - H2: beam-16 improves on O2 by less than 3% geomean on generated programs. Little headroom
    would mean a learned scheduler cannot win much on this action space and cost model,
    whatever the algorithm.
- **Configuration:** `experiments/EXP-011-headroom/run.py --widths 1 4 16 --workers 16`, on 100
  test programs and 17 OOD programs.
- **Run:** commit `dbabcbf`, server, 16 workers, 9.3 min. Curated results are in
  `experiments/EXP-011-headroom/`.
- **Results** (geomean final/initial interpreter cost):

  | programs | n | O2 | beam-1 | beam-4 | beam-16 |
  |---|---:|---:|---:|---:|---:|
  | generated | 100 | 0.558 | 0.552 | 0.552 | 0.552 |
  | benchmarks | 10 | 0.741 | 0.741 | 0.741 | 0.741 |
  | examples | 7 | 0.828 | 0.825 | 0.825 | 0.825 |

  Per program, on generated code:
  - beam-16 beats O2 by > 1% on 22/100 programs, by 12.1% at best;
  - beam-16 improves on beam-1 on 12 programs;
  - O2 never beats beam-16 (0/117).

  Search cost: median 351 distinct states and 7.7 s per program; at most 276 s.
- **Hypotheses.**
  - **H1 supported:** beam-1 (0.552) matches EXP-005's greedy oracle (0.553). It is slightly
    better because it may pass through a non-improving step and keeps the best state seen.
  - **H2 strongly supported:** even a 16-wide search over 12-pass sequences improves on O2 by
    only **1.1% geomean** on generated programs and **0%** on the hand-written kernels.
- **Interpretation (key finding):**
  - On this action space and cost model, *no* scheduler can do much better than O2 on
    average. That explains EXP-005 and EXP-006 better than any model deficiency would.
  - The realistic upper limit for a learned scheduler is about 1% on average, with
    occasional 5–12% wins on a minority of programs. Neither the supervised model nor the
    DQN reached even O2.
  - To make pass scheduling worth learning, the problem must change. The candidates are
    parameterized passes, passes with real trade-offs (unrolling, inlining thresholds),
    a native-time objective, or LLVM's much larger pass space (see ROADMAP "future work").

## EXP-012 — DQN follow-up: equal policy wrappers, then 4× more training

- **Date:** 2026-10-03 (pre-registered after EXP-006's diagnosis, before any EXP-012 number was
  seen)
- **Objective:** separate two explanations for EXP-006's poor DQN:
  - (a) the missing no-retry wrapper, which the supervised policy had;
  - (b) too little training.
- **Part A:**
  - The three EXP-006 checkpoints, with and without the no-retry wrapper, are evaluated on
    **all 100 validation programs**.
  - That validation comparison is the decision metric. Test and OOD are evaluated once
    afterwards.
- **Part B:**
  - 3 seeds × 12,000 episodes (4× EXP-006), with ε decaying over 24,000 steps (4×).
  - Checkpoints are selected on 40 validation programs *with* the no-retry wrapper.
  - Evaluated on test and OOD with and without the wrapper.
  - Everything else equals EXP-006.
- **Hypotheses:**
  - H1: the no-retry wrapper improves every EXP-006 checkpoint's validation geomean by
    ≥ 3% relative.
  - H2: even with the wrapper, no EXP-006 checkpoint beats O2 on test.
  - H3: scaled training improves the best validation geomean over EXP-006 by ≥ 2% relative.
  - H4: scaled DQN with the wrapper still does not beat O2 on generated test programs. EXP-011
    bounds what any schedule could gain.
- **Configuration:** `experiments/EXP-012-dqn-followup/run.py --part both --workers 3`.
- **Run:** commit `e37527c`, server, thread caps active (F-017).
  - Part A took about 4 min.
  - Part B: 3 seeds trained in parallel, 50–63 min each (111k–125k environment steps).
  - 0 invalid transformations.
  - Curated results, including the scaled checkpoints, are in
    `experiments/EXP-012-dqn-followup/`.
- **Part A results** (EXP-006 checkpoints; geomean cost ratio):

  | policy | validation (100) | generated test | benchmarks | examples |
  |---|---:|---:|---:|---:|
  | O2 | **0.619** | **0.558** | **0.741** | **0.828** |
  | seed 0 / +no-retry | 0.692 / 0.671 | 0.632 / 0.609 | 0.894 / 0.884 | 0.967 / 0.962 |
  | seed 1 / +no-retry | 0.720 / 0.673 | 0.660 / 0.625 | 0.956 / 0.896 | 0.963 / 0.932 |
  | seed 2 / +no-retry | 0.702 / 0.663 | 0.641 / 0.589 | 0.952 / 0.857 | 0.967 / 0.904 |

- **Part B results** (scaled training; checkpoints selected with no-retry validation):

  | policy | best validation (40) at episode | generated test | benchmarks | examples |
  |---|---|---:|---:|---:|
  | O2 | — | **0.558** | **0.741** | **0.828** |
  | scaled seed 0 / +no-retry | 0.657 at 100 | 0.650 / 0.604 | 0.966 / 0.906 | 0.983 / 0.926 |
  | scaled seed 1 / +no-retry | 0.661 at 1,800 | 0.679 / 0.632 | 0.928 / 0.813 | 0.958 / 0.860 |
  | scaled seed 2 / +no-retry | 0.663 at 1,800 | 0.681 / 0.631 | 0.970 / 0.866 | 0.982 / 0.956 |

- **Hypotheses.**
  - **H1 supported:** the no-retry wrapper improves every EXP-006 checkpoint on validation, by
    3.1%, 6.5% and 5.5% relative. It improves test results too, e.g. the best seed goes from
    0.641 to 0.589.
  - **H2 supported:** with the wrapper, the best EXP-006 checkpoint (0.589) is still 6% worse
    than O2 on generated programs and 16% worse on benchmarks.
  - **H3 rejected:** 4× more training did not help.
    - The best validation checkpoints came from episodes **100, 1,800 and 1,800 of 12,000**.
    - Validation in the last 10,000 episodes stayed at 0.68–0.72.
    - With the same no-retry wrapper, the scaled agents (0.604 / 0.632 / 0.631) are no better
      than the EXP-006 agents (0.609 / 0.625 / 0.589) on generated test programs.
  - **H4 supported:** no scaled agent beats O2.
- **Interpretation:**
  - 31–63% of EXP-006's gap to O2 (depending on the seed) was the missing no-retry rule, an inference-time
    wrapper rather than learning.
  - The remaining gap does not shrink with more data. The selected checkpoints are close to
    untrained networks, so the learned Q-values add little beyond "try passes in some order,
    never repeat one".
  - That is consistent with EXP-011: the value differences the agent must resolve are about
    1% of cost, below the noise in its Q estimates.
  - The DQN itself was checked on a two-step chain MDP that needs bootstrapping
    (`test_dqn_bootstraps_delayed_reward_on_a_chain`), so a TD-update bug is unlikely to be
    the explanation.
- **Post-hoc diagnostic** (not pre-registered; `scripts/dqn_one_step_regret.py`, src tree
  identical to `e37527c`; output in
  `experiments/EXP-012-dqn-followup/one_step_regret_posthoc.json`):
  - The DQN checkpoints' argmax-Q decisions were scored on exactly the 734 EXP-004 test states,
    whose complete one-step outcome tables are known.
  - Mean one-step regret: EXP-006 seeds 0.051 / 0.064 / 0.066; scaled seeds 0.037 / 0.063 /
    0.066.
  - For comparison: supervised GBDT **0.0152**, majority class 0.0670.
  - Most DQN checkpoints rank actions barely better than the majority baseline. The
    learned Q-function is a poor one-step ranker, which locates the failure in the value
    estimates rather than in the evaluation wrapper.

## EXP-009 — Ablations of the supervised scheduler (features, data size, distribution)

- **Date:** 2026-10-03 (pre-registered)
- **Protocol:** EXP-004 per condition: select on validation regret, refit on train + val,
  report test/OOD regret and end-to-end geomean cost ratio (greedy model policy, budget 12).
  O2 and oracle-greedy are evaluated on the same programs for reference.
- **Conditions:**
  - feature groups: all; minus each of 7 groups; only `opportunities`;
  - training programs: 25, 50, 100, 200, 400;
  - train profile `loop_heavy` vs `default`, each evaluated on both profiles' test programs and
    on OOD.
- **Hypotheses:**
  - H1: removing `opportunities` increases test regret the most. `only:opportunities` recovers
    ≥ 70% of the all-features regret reduction over the majority baseline (0.0670 → 0.0152).
  - H2: regret falls with more training programs, with diminishing returns beyond 200.
  - H3: cross-profile evaluation increases regret relative to in-profile evaluation.
  - H4: in no condition does the model policy beat O2 end to end on generated programs
    (follows from EXP-005).
- **Configuration:** `experiments/EXP-009-ml-ablations/run.py --workers 16`.
- **Runs:**
  - The first sanity run was **aborted** (F-017, thread oversubscription). It is preserved and
    is not evidence.
  - A second sanity run (20/5/5 programs) completed.
  - Full run: commit `e37527c`, server, 16 single-threaded workers, 9.5 min. Curated results
    are in `experiments/EXP-009-ml-ablations/`.
- **Results** (test = generated `loop_heavy` test programs unless stated; regret = mean one-step
  regret; e2e = geomean final/initial cost of the greedy model policy):

  | condition | selected | val regret | test regret | test e2e | OOD regret | OOD e2e |
  |---|---|---:|---:|---:|---:|---:|
  | all features | GBDT | 0.0148 | 0.0152 | 0.580 | 0.0277 | 0.836 |
  | − size | RF | 0.0143 | 0.0127 | 0.589 | 0.0240 | 0.904 |
  | − opcodes | RF | 0.0145 | 0.0133 | 0.586 | 0.0236 | 0.881 |
  | − cfg | RF | 0.0148 | 0.0131 | 0.585 | 0.0208 | 0.892 |
  | − loops | RF | 0.0137 | 0.0127 | 0.589 | 0.0238 | 0.894 |
  | − memory | RF | 0.0152 | 0.0144 | 0.587 | 0.0235 | 0.897 |
  | − calls | GBDT | 0.0144 | 0.0145 | 0.576 | 0.0279 | 0.836 |
  | − opportunities | RF | **0.0163** | 0.0140 | 0.592 | 0.0214 | 0.899 |
  | only opportunities | RF | 0.0165 | 0.0170 | 0.594 | 0.0355 | 0.911 |
  | 25 programs (188 states) | RF | 0.0173 | 0.0149 | 0.587 | 0.0213 | 0.894 |
  | 50 (373) | RF | 0.0188 | 0.0159 | 0.586 | 0.0209 | 0.906 |
  | 100 (740) | GBDT | 0.0195 | 0.0173 | 0.572 | 0.0258 | 0.832 |
  | 200 (1,470) | GBDT | 0.0147 | 0.0182 | 0.576 | 0.0262 | 0.848 |
  | 400 (2,966) | GBDT | 0.0148 | 0.0152 | 0.580 | 0.0277 | 0.836 |
  | *reference: O2* | — | — | — | **0.558** | — | **0.776** |
  | *reference: greedy oracle* | — | — | — | 0.553 | — | 0.775 |

  Distribution shift: rows are the training profile, columns the test programs.

  | trained on | test `loop_heavy`: regret / e2e | test `default`: regret / e2e |
  |---|---:|---:|
  | `loop_heavy` | 0.0152 / 0.580 | **0.0097** / 0.513 |
  | `default` | 0.0158 / 0.616 | 0.0117 / 0.519 |
  | *O2 / oracle* | 0.558 / 0.553 | 0.505 / 0.495 |

- **Hypotheses.**
  - **H1 partly supported.**
    - On validation, the decision metric, removing `opportunities` hurts most (0.0163 vs 0.0148).
      On test the ordering is within noise: several single-group removals score slightly better
      than "all", mostly because the selected model switches from GBDT to RF.
    - `only:opportunities` recovers **96%** of the all-features regret reduction over the
      majority baseline: (0.0670 − 0.0170) / (0.0670 − 0.0152).
    - The feature groups are highly redundant. The hand-made detectors carry nearly all the
      signal, and the generic counts carry nearly all of it too.
  - **H2 rejected: the learning curve is flat.** 25 programs (188 states) give test regret
    0.0149, against 0.0152 with 400 programs. Neither regret nor end-to-end quality improves
    monotonically with data. One-step pass choice saturates with very little data, and
    model-selection variance (RF vs GBDT) is larger than the data effect.
  - **H3 partly supported (asymmetric transfer).**
    - Training on `default` and testing on `loop_heavy` raises regret slightly (0.0158 vs
      0.0152) and end-to-end cost by 6% (0.616 vs 0.580).
    - The reverse transfers *better* than in-distribution training: the `loop_heavy` model
      scores 0.0097 on `default` programs, against 0.0117 for the `default`-trained model.
    - Training on the richer distribution generalizes to the simpler one, but not vice versa.
  - **H4 supported:** no condition beats O2 end to end. The best is 0.572 vs 0.558 on
    `loop_heavy` and 0.513 vs 0.505 on `default`. On OOD every condition is 7–17% worse than O2.
- **Interpretation:**
  - The supervised scheduler's quality is limited by neither features nor data quantity. Any
    reasonable feature subset and about 200 states already reach the plateau.
  - The binding constraints are the tiny headroom above O2 (EXP-011) and compounding greedy
    errors (EXP-005).
  - Workload *coverage* matters more than workload *quantity*: compare the asymmetric transfer
    and the missing `bce` labels (EXP-004).

## EXP-010 — Ablations of the RL formulation (reward, discount, action space)

- **Date:** 2026-10-03 (pre-registered)
- **Protocol:**
  - EXP-006 training (plain-argmax validation), 2 seeds × 2,000 episodes per condition.
  - Evaluated on test and OOD with the plain and the no-retry wrapper.
  - References: O2, and oracle-greedy restricted to each action space.
- **Conditions:**
  - base (λ = 0.002, γ = 1, w_size = 0, 11 passes);
  - λ = 0 and λ = 0.01;
  - γ = 0.9;
  - w_size = 0.5;
  - actions: O1 passes only;
  - actions: all passes but copyprop.
- **Hypotheses:**
  - H1: λ = 0.01 (5× larger action gap) reduces repeated passes and mean passes, and improves
    the plain DQN's cost ratio over base. λ = 0 makes repetition worse.
  - H2: γ = 0.9 changes the cost ratio by less than 2% relative to base, because the horizon is
    short and most gain comes early.
  - H3: w_size = 0.5 lowers the size ratio relative to base, at some cost-ratio penalty.
  - H4: removing copyprop worsens even the restricted oracle, because copyprop enables
    bce/strength (EXP-001). With the O1 action space, the DQN-to-oracle gap shrinks, since the
    problem is smaller.
  - H5: no condition beats O2 on generated test programs.
- **Configuration:** `experiments/EXP-010-rl-ablations/run.py --episodes 2000 --seeds 0 1 --workers 16`.
- **Run:** commit `e37527c`, server, 16 single-threaded workers, 19 min (14 DQN trainings plus 4
  references in parallel). 0 invalid transformations. Curated results are in
  `experiments/EXP-010-rl-ablations/`.
- **Reproducibility check (unplanned, positive):**
  - The `base` condition reproduced EXP-006 seeds 0 and 1 **bit-exactly**: best validation
    0.6898499144743802 and 0.6950184889877898, and generated-test ratios 0.632 / 0.660.
  - This held although EXP-010 trained 2,000 episodes instead of 3,000 (both best checkpoints
    came earlier) and ran with single-threaded BLAS (F-017).
- **Results** (generated test programs, geomean cost ratio; seeds 0 / 1; lower is better):

  | condition | plain DQN | + no-retry | size ratio (plain) | passes (plain) | benchmarks (plain) |
  |---|---:|---:|---:|---:|---:|
  | base (λ 0.002, γ 1, 11 passes) | 0.632 / 0.660 | 0.609 / 0.625 | 0.461 / 0.395 | 9.8 / 12.0 | 0.894 / 0.956 |
  | λ = 0 | 0.694 / 0.652 | 0.628 / 0.609 | 0.494 / 0.379 | 12.0 / 9.9 | 0.895 / 0.985 |
  | λ = 0.01 | 0.648 / 0.653 | 0.604 / 0.609 | 0.421 / 0.369 | 11.6 / 10.7 | 0.921 / 0.969 |
  | γ = 0.9 | 0.647 / 0.654 | 0.605 / 0.615 | 0.413 / 0.421 | 11.8 / 11.8 | 0.987 / 0.929 |
  | w_size = 0.5 | 0.655 / 0.643 | 0.601 / 0.611 | **0.369 / 0.349** | 11.5 / 11.6 | 0.980 / 0.879 |
  | actions: O1 only | 0.655 / 0.646 | 0.627 / 0.609 | 0.444 / 0.489 | 11.3 / 12.0 | 0.940 / 0.985 |
  | actions: − copyprop | 0.625 / 0.628 | 0.615 / 0.610 | 0.317 / 0.451 | 10.8 / 10.3 | 0.950 / 0.908 |
  | *O2* | *0.558* | | *0.241* | *12* | *0.741* |
  | *oracle (all 11 passes)* | *0.553* | | *0.265* | *7.5* | *0.741* |
  | *oracle (O1 passes)* | *0.596* | | *0.370* | *5.3* | *0.925* |
  | *oracle (− copyprop)* | *0.565* | | *0.289* | *6.6* | *0.856* |

- **Hypotheses.**
  - **H1 rejected:** λ = 0.01 does not improve the plain DQN (mean 0.650 vs 0.646 for base),
    and it does not consistently reduce passes. λ = 0 is somewhat worse (mean 0.673). A 5×
    larger action gap is still too small relative to Q-estimation error.
  - **H2 supported:** γ = 0.9 changes the cost ratio by < 1% (mean 0.650 vs 0.646).
  - **H3 supported:** w_size = 0.5 lowers the static size ratio (mean 0.359 vs 0.428) at a
    negligible cost-ratio change (0.649 vs 0.646). The multi-objective reward does steer the
    agent.
  - **H4 supported (both parts):**
    - Removing copyprop worsens even the greedy oracle: 0.565 vs 0.553, and on benchmarks
      0.856 vs 0.741, since copyprop enables bce/strength.
    - In the O1-only action space the plain DQN is about 9% from its oracle (0.655 / 0.646 vs
      0.596), against about 17% for base. With no-retry the gap is 2–5% vs 10–13%. A smaller
      action space is easier to learn.
  - **H5 supported:** no condition beats O2 (0.558). The best is 0.601 (w_size = 0.5 +
    no-retry).
- **Consistent across all 14 trainings:** the no-retry wrapper improves every condition, by
  1.6–9.5% on generated programs.
- **Interpretation:**
  - Reward shaping (λ, γ) barely matters, so the agent's limit is not the reward definition.
  - Action-space size matters a lot, both for what is achievable (removing copyprop) and for
    how close the agent gets (the O1 subset).
  - Multi-objective weights work as intended for code size.

## EXP-008 — Do learned schedules make native code faster or smaller, and at what overhead?

- **Date:** 2026-10-03 (pre-registered, before any EXP-008 number exists)
- **Protocol:**
  - For each of the 10 benchmark kernels, every policy chooses its pass list on the small
    instance (budget 12). The decision time is recorded.
  - The large instance is compiled with exactly that list at LLVM -O0 (D-028) and timed with
    the Phase 6 protocol (correctness gate, warm-up, interleaved seeded rounds, 10 repeats).
  - Also recorded: `.text` bytes, ForgeCompile pass time, native compile time. LLVM -O2
    without ForgeCompile passes is included as an external reference only.
- **Policies:** fc-O0, O1, O2, frequency, the supervised model, oracle-greedy, and DQN
  checkpoints chosen by validation score, each with and without the no-retry wrapper. The
  checkpoints are EXP-006 seed 0 (best validation 0.690) and the best-validation EXP-012
  scaled seed.
- **Hypotheses:**
  - H1: no learned policy beats O2 natively by more than EXP-003's noise band, consistent with
    EXP-005/006/011 at the interpreter level.
  - H2: at LLVM -O0, ForgeCompile O2's geomean native speedup over fc-O0 is small (< 10%), and
    smaller than its interpreter-cost reduction (EXP-002 sanity: flat native ratios).
  - H3: every learned policy's decision time exceeds O2's total ForgeCompile pass time.
- **Configuration:** `experiments/EXP-008-native-policies/run.py --repeats 10 --noretry --dqn
  <EXP-006 seed0> <EXP-012 best>`. It runs alone on the server, with the load average recorded.
