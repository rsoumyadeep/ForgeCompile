## Part A: EXP-006 checkpoints, with and without the no-retry wrapper

Validation (geomean cost ratio):

- O2: 0.6186
- exp006-seed0: 0.6924
- exp006-seed0+noretry: 0.6706
- exp006-seed1: 0.7204
- exp006-seed1+noretry: 0.6735
- exp006-seed2: 0.7021
- exp006-seed2+noretry: 0.6633

Test + OOD:

| programs | policy | geomean cost ratio | best | worst | size ratio | mean passes | decision ms | schedule ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | O2 | 0.586 | 0.051 | 1.000 | 0.288 | 12.0 | 0.0 | 55.8 |
| all | exp006-seed2+noretry | 0.624 | 0.051 | 1.000 | 0.355 | 11.3 | 32.2 | 98.2 |
| all | exp006-seed0+noretry | 0.646 | 0.063 | 1.000 | 0.434 | 9.2 | 25.1 | 79.2 |
| all | exp006-seed1+noretry | 0.660 | 0.063 | 1.000 | 0.372 | 11.8 | 31.3 | 98.3 |
| all | exp006-seed0 | 0.667 | 0.088 | 1.000 | 0.503 | 9.3 | 20.1 | 77.7 |
| all | exp006-seed2 | 0.680 | 0.072 | 1.000 | 0.448 | 11.8 | 26.9 | 98.1 |
| all | exp006-seed1 | 0.697 | 0.063 | 1.000 | 0.442 | 11.9 | 24.6 | 95.1 |
| benchmark | O2 | 0.741 | 0.362 | 1.000 | 0.707 | 12.0 | 0.0 | 16.4 |
| benchmark | exp006-seed2+noretry | 0.857 | 0.471 | 1.000 | 0.777 | 11.5 | 7.2 | 19.7 |
| benchmark | exp006-seed0+noretry | 0.884 | 0.435 | 1.000 | 0.792 | 6.0 | 3.9 | 9.9 |
| benchmark | exp006-seed0 | 0.894 | 0.471 | 1.000 | 0.818 | 6.1 | 3.1 | 9.6 |
| benchmark | exp006-seed1+noretry | 0.896 | 0.597 | 1.000 | 0.734 | 11.6 | 7.0 | 18.6 |
| benchmark | exp006-seed2 | 0.952 | 0.858 | 1.000 | 0.821 | 12.0 | 7.3 | 22.1 |
| benchmark | exp006-seed1 | 0.956 | 0.890 | 1.000 | 0.822 | 11.8 | 6.0 | 17.4 |
| example | O2 | 0.828 | 0.607 | 0.996 | 1.039 | 12.0 | 0.0 | 17.2 |
| example | exp006-seed2+noretry | 0.904 | 0.790 | 0.997 | 1.024 | 11.6 | 6.6 | 17.9 |
| example | exp006-seed1+noretry | 0.932 | 0.886 | 1.000 | 0.965 | 11.3 | 6.5 | 17.4 |
| example | exp006-seed0+noretry | 0.962 | 0.918 | 0.998 | 0.846 | 6.1 | 3.3 | 8.6 |
| example | exp006-seed1 | 0.963 | 0.916 | 1.000 | 0.886 | 11.9 | 5.0 | 15.5 |
| example | exp006-seed0 | 0.967 | 0.918 | 1.000 | 0.881 | 6.3 | 3.0 | 8.5 |
| example | exp006-seed2 | 0.967 | 0.918 | 1.000 | 0.866 | 12.0 | 5.0 | 16.3 |
| generated | O2 | 0.558 | 0.051 | 0.872 | 0.241 | 12.0 | 0.0 | 62.4 |
| generated | exp006-seed2+noretry | 0.589 | 0.051 | 0.929 | 0.305 | 11.3 | 36.5 | 111.6 |
| generated | exp006-seed0+noretry | 0.609 | 0.063 | 0.908 | 0.390 | 9.7 | 28.7 | 91.1 |
| generated | exp006-seed1+noretry | 0.625 | 0.063 | 0.989 | 0.326 | 11.8 | 35.4 | 111.9 |
| generated | exp006-seed0 | 0.632 | 0.088 | 0.909 | 0.461 | 9.8 | 22.9 | 89.3 |
| generated | exp006-seed2 | 0.641 | 0.072 | 0.995 | 0.402 | 11.8 | 30.4 | 111.4 |
| generated | exp006-seed1 | 0.660 | 0.063 | 0.997 | 0.395 | 12.0 | 27.8 | 108.4 |

## Part B: scaled training (no-retry validation)

```
{
 "scaled-seed2": {
  "train_seconds": 3009.521200040006,
  "env_steps": 111261,
  "best_validation": 0.663226280837489,
  "invalid_transformations": 0
 },
 "scaled-seed1": {
  "train_seconds": 3110.1813327239943,
  "env_steps": 115914,
  "best_validation": 0.6614291889657112,
  "invalid_transformations": 0
 },
 "scaled-seed0": {
  "train_seconds": 3779.301630130969,
  "env_steps": 125344,
  "best_validation": 0.6568198381273257,
  "invalid_transformations": 0
 }
}
```

| programs | policy | geomean cost ratio | best | worst | size ratio | mean passes | decision ms | schedule ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | O2 | 0.586 | 0.051 | 1.000 | 0.288 | 12.0 | 0.0 | 55.5 |
| all | scaled-seed0+noretry | 0.641 | 0.072 | 1.000 | 0.356 | 12.0 | 24.0 | 75.4 |
| all | scaled-seed1+noretry | 0.658 | 0.051 | 1.056 | 0.384 | 11.8 | 36.1 | 112.3 |
| all | scaled-seed2+noretry | 0.665 | 0.075 | 1.000 | 0.383 | 11.2 | 30.1 | 93.0 |
| all | scaled-seed0 | 0.689 | 0.078 | 1.000 | 0.464 | 12.0 | 19.3 | 75.0 |
| all | scaled-seed1 | 0.712 | 0.072 | 1.130 | 0.451 | 11.8 | 27.8 | 111.4 |
| all | scaled-seed2 | 0.717 | 0.139 | 1.000 | 0.419 | 11.7 | 24.0 | 91.8 |
| benchmark | O2 | 0.741 | 0.362 | 1.000 | 0.707 | 12.0 | 0.0 | 16.4 |
| benchmark | scaled-seed1+noretry | 0.813 | 0.435 | 1.000 | 0.723 | 11.5 | 7.0 | 19.6 |
| benchmark | scaled-seed2+noretry | 0.866 | 0.543 | 1.000 | 0.833 | 11.5 | 7.2 | 19.4 |
| benchmark | scaled-seed0+noretry | 0.906 | 0.749 | 1.000 | 0.750 | 12.0 | 6.9 | 18.6 |
| benchmark | scaled-seed1 | 0.928 | 0.749 | 1.000 | 0.777 | 11.2 | 5.3 | 18.7 |
| benchmark | scaled-seed0 | 0.966 | 0.890 | 1.000 | 0.839 | 12.0 | 5.4 | 17.2 |
| benchmark | scaled-seed2 | 0.970 | 0.858 | 1.000 | 0.841 | 11.9 | 5.7 | 18.3 |
| example | O2 | 0.828 | 0.607 | 0.996 | 1.039 | 12.0 | 0.0 | 14.5 |
| example | scaled-seed1+noretry | 0.860 | 0.624 | 1.000 | 1.180 | 11.7 | 7.1 | 20.2 |
| example | scaled-seed0+noretry | 0.926 | 0.821 | 0.996 | 0.869 | 12.0 | 6.1 | 16.5 |
| example | scaled-seed2+noretry | 0.956 | 0.882 | 1.000 | 0.980 | 11.6 | 6.7 | 19.4 |
| example | scaled-seed1 | 0.958 | 0.886 | 1.000 | 0.885 | 11.9 | 4.7 | 16.9 |
| example | scaled-seed2 | 0.982 | 0.913 | 1.000 | 0.942 | 12.0 | 4.8 | 15.9 |
| example | scaled-seed0 | 0.983 | 0.954 | 1.000 | 0.903 | 12.0 | 6.7 | 17.2 |
| generated | O2 | 0.558 | 0.051 | 0.872 | 0.241 | 12.0 | 0.0 | 62.3 |
| generated | scaled-seed0+noretry | 0.604 | 0.072 | 0.980 | 0.311 | 12.0 | 27.0 | 85.2 |
| generated | scaled-seed2+noretry | 0.631 | 0.075 | 0.977 | 0.332 | 11.2 | 34.1 | 105.5 |
| generated | scaled-seed1+noretry | 0.632 | 0.051 | 1.056 | 0.333 | 11.8 | 41.1 | 128.0 |
| generated | scaled-seed0 | 0.650 | 0.078 | 1.000 | 0.418 | 12.0 | 21.6 | 84.8 |
| generated | scaled-seed1 | 0.679 | 0.072 | 1.130 | 0.408 | 11.8 | 31.7 | 127.3 |
| generated | scaled-seed2 | 0.681 | 0.139 | 1.000 | 0.369 | 11.6 | 27.2 | 104.4 |
