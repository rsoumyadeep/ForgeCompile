| family | condition | model | val regret | loop_heavy regret | loop_heavy e2e | default regret | default e2e | ood regret | ood e2e |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| features | all | gradient_boosting | 0.0148 | 0.0152 | 0.580 | - | - | 0.0277 | 0.836 |
| features | -size | random_forest | 0.0143 | 0.0127 | 0.589 | - | - | 0.0240 | 0.904 |
| features | -opcodes | random_forest | 0.0145 | 0.0133 | 0.586 | - | - | 0.0236 | 0.881 |
| features | -cfg | random_forest | 0.0148 | 0.0131 | 0.585 | - | - | 0.0208 | 0.892 |
| features | -loops | random_forest | 0.0137 | 0.0127 | 0.589 | - | - | 0.0238 | 0.894 |
| features | -memory | random_forest | 0.0152 | 0.0144 | 0.587 | - | - | 0.0235 | 0.897 |
| features | -calls | gradient_boosting | 0.0144 | 0.0145 | 0.576 | - | - | 0.0279 | 0.836 |
| features | -opportunities | random_forest | 0.0163 | 0.0140 | 0.592 | - | - | 0.0214 | 0.899 |
| features | only:opportunities | random_forest | 0.0165 | 0.0170 | 0.594 | - | - | 0.0355 | 0.911 |
| data | n=25 | random_forest | 0.0173 | 0.0149 | 0.587 | - | - | 0.0213 | 0.894 |
| data | n=50 | random_forest | 0.0188 | 0.0159 | 0.586 | - | - | 0.0209 | 0.906 |
| data | n=100 | gradient_boosting | 0.0195 | 0.0173 | 0.572 | - | - | 0.0258 | 0.832 |
| data | n=200 | gradient_boosting | 0.0147 | 0.0182 | 0.576 | - | - | 0.0262 | 0.848 |
| data | n=400 | gradient_boosting | 0.0148 | 0.0152 | 0.580 | - | - | 0.0277 | 0.836 |
| distribution | train:loop_heavy | gradient_boosting | 0.0148 | 0.0152 | 0.580 | 0.0097 | 0.513 | 0.0277 | 0.836 |
| distribution | train:default | random_forest | 0.0118 | 0.0158 | 0.616 | 0.0117 | 0.519 | 0.0234 | 0.885 |
| reference | O2 | - | - | - | 0.558 | - | 0.505 | - | 0.776 |
| reference | oracle | - | - | - | 0.553 | - | 0.495 | - | 0.775 |
