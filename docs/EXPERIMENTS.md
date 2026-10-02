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

_None yet. The first experiments arrive with the optimization passes (Phase 4) and the
benchmark harness (Phase 6)._
