"""Post-hoc diagnostic: one-step decision quality of DQN checkpoints on the EXP-004 test states.

The supervised model's EXP-004 regret (0.0152 on test) was measured on recorded states with
complete one-step outcome tables. This script scores DQN checkpoints' argmax-Q decisions on
exactly those states, so the two learners' *one-step* choices can be compared like for like.

The DQN observation needs the step and the previous action: both are reconstructed from the
recorded trajectory (``step``; the previous record's ``taken``). A greedy DQN may choose
``stop`` (gain 0). Regret is defined as in ``ml/models.py``.

Usage::

    uv run python scripts/dqn_one_step_regret.py experiments/EXP-006-rl-scheduling/checkpoints/*.npz
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from forgecompile.ml.data_pipeline import DatasetConfig, build_dataset
from forgecompile.ml.dataset import STOP, StateRecord
from forgecompile.ml.features import FEATURE_NAMES
from forgecompile.rl.dqn import DQNAgent
from forgecompile.rl.env import ENV_ACTIONS

HORIZON = 12


def observations(records: list[StateRecord]) -> list[np.ndarray]:
    previous: dict[str, StateRecord] = {}
    out = []
    for record in sorted(records, key=lambda r: (r.program, r.step)):
        last = np.zeros(len(ENV_ACTIONS))
        before = previous.get(record.program)
        if before is not None and record.step > 0:
            last[ENV_ACTIONS.index(before.taken)] = 1.0
        remaining = (HORIZON - record.step) / HORIZON
        out.append(np.concatenate([np.array(record.features), [remaining], last]))
        previous[record.program] = record
    return out


def regret_of(agent: DQNAgent, records: list[StateRecord]) -> dict[str, float]:
    ordered = sorted(records, key=lambda r: (r.program, r.step))
    regrets, stops, correct = [], 0, 0
    for record, obs in zip(ordered, observations(records), strict=True):
        action = ENV_ACTIONS[int(np.argmax(agent.q_values(obs)))]
        gains = record.gains()
        best = max(max(gains.values()), 0.0)
        chosen = 0.0 if action == STOP else gains[action]
        regrets.append(best - chosen)
        stops += action == STOP
        correct += action == record.label
    return {
        "mean_regret": float(np.mean(regrets)),
        "accuracy": correct / len(ordered),
        "stop_rate": stops / len(ordered),
        "n": float(len(ordered)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoints", type=Path, nargs="+")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=None, help="write results as JSON")
    args = parser.parse_args()
    data = build_dataset(DatasetConfig(), workers=args.workers)  # cached EXP-004 dataset
    obs_size = len(FEATURE_NAMES) + 1 + len(ENV_ACTIONS)
    results = {}
    for path in args.checkpoints:
        agent = DQNAgent.load(path, obs_size, len(ENV_ACTIONS))
        results[str(path)] = {s: regret_of(agent, data[s]) for s in ("test", "ood")}
        print(path, json.dumps(results[str(path)]))
    if args.out:
        args.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
