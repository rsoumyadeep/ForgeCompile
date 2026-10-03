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
- **Results / interpretation:** below, after the run.

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
- **Results:** below, after the run.

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
