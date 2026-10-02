"""Supervised models for next-pass prediction, and how they are scored.

Candidates (chosen by validation evidence, not novelty):

* ``majority``: always predicts the most frequent label (sanity floor);
* ``decision_tree``: interpretable, and its splits can be read;
* ``random_forest``: bagged trees, robust with little tuning;
* ``gradient_boosting``: scikit-learn's histogram GBDT;
* ``mlp``: a small neural network (2 x 64 ReLU) on log-scaled, standardized features.

**Why accuracy is not enough.** Often several passes give the *same* one-step
improvement (for example, constfold and sccp both fold everything foldable).
Predicting the "wrong" one of two equal passes costs nothing. The primary
metric is therefore **regret**::

    regret(state) = best_gain(state) - gain(predicted_pass, state)     (>= 0)

in units of relative cost reduction, with ``gain(STOP) = 0``. Also reported:
accuracy, top-2 accuracy, and *near-optimal rate* (regret at most 10% of the
best gain).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from sklearn.tree import DecisionTreeClassifier

from forgecompile.ml.dataset import LABELS, STOP, StateRecord
from forgecompile.ml.features import FEATURE_GROUPS, FEATURE_NAMES


def make_models(seed: int) -> dict[str, Any]:
    return {
        "majority": DummyClassifier(strategy="most_frequent"),
        "decision_tree": DecisionTreeClassifier(
            max_depth=10, min_samples_leaf=2, random_state=seed
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200, min_samples_leaf=2, random_state=seed, n_jobs=-1
        ),
        "gradient_boosting": HistGradientBoostingClassifier(max_iter=200, random_state=seed),
        "mlp": make_pipeline(
            FunctionTransformer(np.log1p),  # counts span orders of magnitude; all features >= 0
            StandardScaler(),
            MLPClassifier(hidden_layer_sizes=(64, 64), max_iter=800, random_state=seed),
        ),
    }


def feature_columns(exclude_groups: tuple[str, ...] = ()) -> list[int]:
    """Indices into the feature vector, optionally without some groups (for ablations)."""
    unknown = set(exclude_groups) - set(FEATURE_GROUPS)
    if unknown:
        raise ValueError(f"unknown feature groups: {sorted(unknown)}")
    excluded = {name for group in exclude_groups for name in FEATURE_GROUPS[group]}
    return [i for i, name in enumerate(FEATURE_NAMES) if name not in excluded]


def to_arrays(records: list[StateRecord], columns: list[int]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[r.features[i] for i in columns] for r in records], dtype=float)
    y = np.array([r.label for r in records])
    return x, y


@dataclass
class TrainedModel:
    """A fitted classifier plus the feature columns it expects; ranks labels best-first."""

    name: str
    estimator: Any
    columns: list[int]

    def rank(self, features: list[float]) -> list[str]:
        x = np.array([[features[i] for i in self.columns]], dtype=float)
        probabilities = self.estimator.predict_proba(x)[0]
        classes = list(self.estimator.classes_)
        order = np.argsort(-probabilities, kind="stable")
        ranked = [str(classes[i]) for i in order]
        # Labels never seen in training are ranked last, so a pass stays selectable.
        return ranked + [label for label in LABELS if label not in ranked]

    def predict(self, records: list[StateRecord]) -> list[str]:
        x, _ = to_arrays(records, self.columns)
        return [str(p) for p in self.estimator.predict(x)]


def fit(name: str, estimator: Any, records: list[StateRecord], columns: list[int]) -> TrainedModel:
    x, y = to_arrays(records, columns)
    estimator.fit(x, y)
    return TrainedModel(name, estimator, columns)


def score(model: TrainedModel, records: list[StateRecord]) -> dict[str, float]:
    """Decision-quality metrics on labelled records (see the module docstring)."""
    if not records:
        raise ValueError("no records to score")
    predictions = model.predict(records)
    x, _ = to_arrays(records, model.columns)
    probabilities = model.estimator.predict_proba(x)
    classes = list(model.estimator.classes_)
    regrets, correct, top2, near = [], 0, 0, 0
    for record, predicted, probs in zip(records, predictions, probabilities, strict=True):
        gains = record.gains()
        best = max(max(gains.values()), 0.0)
        chosen = 0.0 if predicted == STOP else gains[predicted]
        regret = best - chosen
        regrets.append(regret)
        correct += predicted == record.label
        top = [classes[i] for i in np.argsort(-probs)[:2]]
        top2 += record.label in top
        near += regret <= 0.1 * best + 1e-12
    n = len(records)
    return {
        "accuracy": correct / n,
        "top2_accuracy": top2 / n,
        "mean_regret": float(np.mean(regrets)),
        "near_optimal_rate": near / n,
        "n": float(n),
    }


def select_model(
    train: list[StateRecord],
    val: list[StateRecord],
    seed: int,
    exclude_groups: tuple[str, ...] = (),
) -> tuple[TrainedModel, dict[str, dict[str, float]]]:
    """Fit every candidate on ``train``; choose by validation regret (never by test data).

    Returns the selected model *refitted on train + val*, and every candidate's
    validation scores. Ties on regret are broken by the near-optimal rate.
    """
    columns = feature_columns(exclude_groups)
    val_scores: dict[str, dict[str, float]] = {}
    for name, estimator in make_models(seed).items():
        val_scores[name] = score(fit(name, estimator, train, columns), val)
    best = min(
        val_scores,
        key=lambda n: (val_scores[n]["mean_regret"], -val_scores[n]["near_optimal_rate"]),
    )
    final = fit(best, make_models(seed)[best], train + val, columns)
    return final, val_scores
