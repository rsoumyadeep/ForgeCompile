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
- **Results / interpretation:** see below, after the run.
