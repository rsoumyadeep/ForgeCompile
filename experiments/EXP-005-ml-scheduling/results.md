| programs | policy | geomean cost ratio | best | worst | size ratio | mean passes | decision ms | schedule ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | oracle-greedy | 0.580 | 0.051 | 1.000 | 0.320 | 7.1 | 2650.2 | 2714.2 |
| all | O2 | 0.586 | 0.051 | 1.000 | 0.288 | 12.0 | 0.0 | 96.4 |
| all | random-k12-s0 | 0.608 | 0.051 | 1.000 | 0.335 | 12.0 | 0.1 | 133.7 |
| all | frequency | 0.608 | 0.075 | 1.000 | 0.361 | 11.0 | 0.0 | 91.2 |
| all | model:gradient_boosting | 0.611 | 0.063 | 1.000 | 0.343 | 8.1 | 1086.1 | 1166.4 |
| all | random-k12-s1 | 0.633 | 0.075 | 1.000 | 0.337 | 12.0 | 0.0 | 93.1 |
| all | O1 | 0.642 | 0.063 | 1.000 | 0.397 | 5.0 | 0.0 | 61.4 |
| all | random-k12-s2 | 0.653 | 0.063 | 1.000 | 0.425 | 12.0 | 0.0 | 116.4 |
| benchmark | O2 | 0.741 | 0.362 | 1.000 | 0.707 | 12.0 | 0.0 | 18.2 |
| benchmark | oracle-greedy | 0.741 | 0.362 | 1.000 | 0.844 | 4.5 | 17284.6 | 17294.6 |
| benchmark | frequency | 0.747 | 0.362 | 1.000 | 0.785 | 11.0 | 0.0 | 15.2 |
| benchmark | model:gradient_boosting | 0.815 | 0.435 | 1.000 | 0.779 | 5.1 | 664.0 | 677.1 |
| benchmark | random-k12-s1 | 0.829 | 0.364 | 1.000 | 0.722 | 12.0 | 0.0 | 15.5 |
| benchmark | random-k12-s2 | 0.850 | 0.597 | 1.000 | 0.743 | 12.0 | 0.0 | 16.8 |
| benchmark | random-k12-s0 | 0.856 | 0.506 | 1.000 | 0.844 | 12.0 | 0.0 | 32.5 |
| benchmark | O1 | 0.925 | 0.749 | 1.000 | 0.701 | 5.0 | 0.0 | 7.3 |
| example | oracle-greedy | 0.825 | 0.599 | 0.996 | 1.199 | 4.6 | 1993.8 | 2002.6 |
| example | O2 | 0.828 | 0.607 | 0.996 | 1.039 | 12.0 | 0.0 | 21.2 |
| example | frequency | 0.838 | 0.608 | 0.996 | 1.262 | 11.0 | 0.0 | 15.6 |
| example | model:gradient_boosting | 0.867 | 0.722 | 0.996 | 1.206 | 5.9 | 1016.4 | 1032.7 |
| example | random-k12-s2 | 0.871 | 0.750 | 0.996 | 1.061 | 12.0 | 0.0 | 16.9 |
| example | random-k12-s1 | 0.919 | 0.791 | 0.996 | 0.773 | 12.0 | 0.0 | 14.3 |
| example | random-k12-s0 | 0.919 | 0.793 | 0.999 | 1.262 | 12.0 | 0.0 | 18.4 |
| example | O1 | 0.942 | 0.886 | 0.996 | 0.779 | 5.0 | 0.0 | 7.3 |
| generated | oracle-greedy | 0.553 | 0.051 | 0.872 | 0.265 | 7.5 | 1232.8 | 1306.0 |
| generated | O2 | 0.558 | 0.051 | 0.872 | 0.241 | 12.0 | 0.0 | 109.5 |
| generated | random-k12-s0 | 0.571 | 0.051 | 0.891 | 0.278 | 12.0 | 0.1 | 151.9 |
| generated | model:gradient_boosting | 0.580 | 0.063 | 0.906 | 0.289 | 8.5 | 1133.1 | 1224.7 |
| generated | frequency | 0.582 | 0.075 | 0.875 | 0.306 | 11.0 | 0.0 | 104.1 |
| generated | random-k12-s1 | 0.600 | 0.075 | 0.882 | 0.294 | 12.0 | 0.0 | 106.4 |
| generated | O1 | 0.602 | 0.063 | 0.928 | 0.358 | 5.0 | 0.0 | 70.6 |
| generated | random-k12-s2 | 0.624 | 0.063 | 0.929 | 0.377 | 12.0 | 0.0 | 133.4 |

Model: gradient_boosting. Frequency order: simplifycfg, dce, copyprop, sccp, licm, constfold, simplify, inline, cse, strength, bce.
