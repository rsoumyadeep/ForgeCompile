| model | val accuracy | val top-2 | val mean regret | val near-optimal |
|---|---:|---:|---:|---:|
| gradient_boosting | 0.485 | 0.689 | 0.0148 | 0.573 |
| random_forest | 0.516 | 0.701 | 0.0150 | 0.601 |
| mlp | 0.443 | 0.663 | 0.0195 | 0.519 |
| decision_tree | 0.418 | 0.530 | 0.0224 | 0.511 |
| majority | 0.204 | 0.268 | 0.0554 | 0.265 |

Selected: **gradient_boosting** (refit on train+val).

| split | model | accuracy | top-2 | mean regret | near-optimal | n |
|---|---|---:|---:|---:|---:|---:|
| test | gradient_boosting | 0.525 | 0.719 | 0.0152 | 0.620 | 734 |
| test | majority | 0.213 | 0.304 | 0.0670 | 0.290 | 734 |
| ood | gradient_boosting | 0.327 | 0.602 | 0.0277 | 0.513 | 113 |
| ood | majority | 0.248 | 0.292 | 0.0269 | 0.478 | 113 |

Label distribution (train): {"constfold": 251, "copyprop": 418, "cse": 112, "dce": 420, "inline": 117, "licm": 268, "sccp": 366, "simplify": 222, "simplifycfg": 604, "stop": 162, "strength": 26}

Random-forest impurity importance by feature group: opcodes=0.57, opportunities=0.18, cfg=0.08, size=0.06, loops=0.06, memory=0.04, calls=0.02
