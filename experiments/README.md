# Experiments

- `docs/EXPERIMENTS.md` is the log of record: questions, hypotheses, methods and results.
- `experiments/runs/` holds raw per-run outputs created by
  `forgecompile.utils.experiment.ExperimentRun` (`metadata.json`, `config.json`, `run.log` and
  artifacts). It is git-ignored because runs are numerous and large.
- `experiments/EXP-NNN-<name>/` (committed) holds the configuration plus the curated results
  of runs cited in `docs/RESULTS.md`, copied together with their `metadata.json` so each
  reported number stays traceable.

```python
from forgecompile.utils.experiment import ExperimentRun

run = ExperimentRun.create("EXP-001-cse", config={"passes": ["cse"]}, seed=0)
try:
    ...  # do the work
    run.save_json("results.json", results)
    run.finalize("completed", summary={...})
except Exception:
    run.finalize("failed")
    raise
```
