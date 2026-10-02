"""RL environment semantics and the NumPy DQN (gradient check, learning on a toy MDP)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from forgecompile.ml.dataset import ProgramSpec
from forgecompile.rl import env as env_module
from forgecompile.rl.dqn import MLP, Adam, DQNAgent, DQNConfig, DQNPolicy, Normalizer, train
from forgecompile.rl.env import ENV_ACTIONS, STOP_INDEX, PassSchedulingEnv, RewardConfig

LOOPY = """
fn main() -> int {
    let a: [int; 8];
    let s = 0;
    for i in 0..8 { a[i] = i * 3; s = s + a[i] + 2 * 5; }
    print(s);
    return 0;
}
"""


def make_env(**kwargs: object) -> PassSchedulingEnv:
    return PassSchedulingEnv([ProgramSpec("loopy", LOOPY, "generated")], **kwargs)  # type: ignore[arg-type]


def test_reset_and_observation_shape() -> None:
    env = make_env()
    obs, info = env.reset()
    assert obs.shape == (env.obs_size,) and info["program"] == "loopy"
    assert obs[-env.n_actions :].sum() == 0  # no previous action yet


def test_rewards_telescope_to_total_improvement() -> None:
    penalty = 0.01
    env = make_env(reward=RewardConfig(step_penalty=penalty))
    env.reset()
    total = 0.0
    for name in ["copyprop", "constfold", "bce", "dce", "simplifycfg"]:
        _, reward, terminated, truncated, _ = env.step(ENV_ACTIONS.index(name))
        total += reward
        assert not terminated and not truncated
    improvement = (env.stats.initial_cost - env.stats.final_cost) / env.stats.initial_cost
    assert total == pytest.approx(improvement - penalty * 5)
    assert improvement > 0


def test_stop_and_horizon() -> None:
    env = make_env(horizon=2)
    env.reset()
    _, _, terminated, _, info = env.step(STOP_INDEX)
    assert terminated and info["stop"]
    env.reset()
    env.step(0)
    _, _, terminated, truncated, _ = env.step(0)
    assert truncated and not terminated


def test_invalid_transformation_is_penalized_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_pass(module: object, name: str) -> object:
        raise RuntimeError("simulated miscompile")

    monkeypatch.setattr(env_module, "apply_pass", broken_pass)
    env = make_env(reward=RewardConfig(invalid_penalty=2.0))
    env.reset()
    _, reward, terminated, _, info = env.step(0)
    assert terminated and reward == -2.0 and "simulated" in info["invalid"]
    assert env.invalid_transformations == 1


def test_mlp_backward_matches_numerical_gradient() -> None:
    rng = np.random.default_rng(0)
    net = MLP(5, 7, 3, rng)
    x = rng.normal(size=(4, 5))
    upstream = rng.normal(size=(4, 3))

    def loss() -> float:
        out, _ = net.forward(x)
        return float((out * upstream).sum())

    _, cache = net.forward(x)
    grads = net.backward(upstream, cache)
    eps = 1e-6
    for name, param in net.params.items():
        for idx in [(0,) * param.ndim, tuple(s - 1 for s in param.shape)]:
            original = param[idx]
            param[idx] = original + eps
            plus = loss()
            param[idx] = original - eps
            minus = loss()
            param[idx] = original
            numeric = (plus - minus) / (2 * eps)
            assert grads[name][idx] == pytest.approx(numeric, rel=1e-4, abs=1e-6), name


def test_adam_fits_a_linear_target() -> None:
    rng = np.random.default_rng(1)
    net = MLP(2, 16, 1, rng)
    optimizer = Adam(net.params, 1e-2)
    x = rng.normal(size=(64, 2))
    y = 2 * x[:, :1] - x[:, 1:]
    for _ in range(400):
        out, cache = net.forward(x)
        optimizer.step(net.params, net.backward(2 * (out - y) / len(x), cache))
    out, _ = net.forward(x)
    assert float(((out - y) ** 2).mean()) < 0.01


class _BanditEnv:
    """Toy MDP: action 3 gives +1 and ends the episode; any other action gives 0 and ends it."""

    obs_size, n_actions = 4, 5

    def __init__(self) -> None:
        self.invalid_transformations = 0
        self.stats = type("S", (), {"total_reward": 0.0, "final_cost": 1.0, "initial_cost": 1.0})()

    def reset(self) -> tuple[np.ndarray, dict[str, object]]:
        self.stats.total_reward = 0.0
        return np.ones(4), {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, object]]:
        reward = 1.0 if action == 3 else 0.0
        self.stats.total_reward = reward
        return np.ones(4), reward, True, False, {}


def test_dqn_learns_the_best_action_on_a_toy_problem() -> None:
    config = DQNConfig(
        hidden=16, warmup_steps=50, epsilon_decay_steps=200, target_update=20, batch_size=16
    )
    env = _BanditEnv()
    agent = DQNAgent(env.obs_size, env.n_actions, config)
    log = train(env, agent, episodes=400)  # type: ignore[arg-type]
    q = agent.q_values(np.ones(4))
    assert int(np.argmax(q)) == 3
    assert q[3] == pytest.approx(1.0, abs=0.15)
    assert len(log.episode_returns) == 400 and log.losses


def test_agent_save_load_round_trip(tmp_path: Path) -> None:
    agent = DQNAgent(4, 3, DQNConfig(hidden=8))
    agent.normalizer = Normalizer.fit(np.abs(np.random.default_rng(0).normal(size=(10, 4))))
    path = tmp_path / "agent.npz"
    agent.save(path)
    loaded = DQNAgent.load(path, 4, 3)
    obs = np.array([1.0, 2.0, 0.0, 5.0])
    assert np.allclose(loaded.q_values(obs), agent.q_values(obs))


def test_dqn_policy_runs_on_real_programs() -> None:
    env = make_env()
    agent = DQNAgent(
        env.obs_size, env.n_actions, DQNConfig(warmup_steps=20, epsilon_decay_steps=50)
    )
    train(env, agent, episodes=6)  # type: ignore[arg-type]
    from forgecompile.driver import build_ir
    from forgecompile.ml.policies import schedule

    result = schedule(DQNPolicy(agent), build_ir(LOOPY), max_steps=5)
    assert len(result.actions) <= 5
    assert math.isfinite(float(agent.q_values(env.reset()[0]).max()))


def test_training_shorter_than_warmup_still_yields_a_usable_agent(tmp_path: Path) -> None:
    """Regression: a run ending inside the warm-up left the normalizer unset (save failed)."""
    env = _BanditEnv()
    agent = DQNAgent(env.obs_size, env.n_actions, DQNConfig(warmup_steps=1000))
    train(env, agent, episodes=5)  # type: ignore[arg-type]
    agent.save(tmp_path / "short.npz")
    assert np.isfinite(agent.q_values(np.ones(4))).all()
