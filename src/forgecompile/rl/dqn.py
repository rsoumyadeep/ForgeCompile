"""Deep Q-learning (Double DQN) in plain NumPy.

**Why DQN.** The action space is small and discrete (12 actions), observations
are fixed-length vectors, and environment steps are expensive but cacheable.
Off-policy value learning with a replay buffer reuses every expensive
transition many times. A policy-gradient method would discard its experience
after each update. No deep-learning framework is used: the network is a 2-layer
MLP whose backward pass fits in a screen, which keeps the dependency footprint
small (D-007, D-039) and every line explainable.

**Algorithm** (Mnih et al. 2015; van Hasselt et al. 2016, Double DQN)::

    Q(o, a; θ)             online network
    Q(o, a; θ⁻)            target network, a copy of θ refreshed every `target_update` steps
    a* = argmax_a Q(o', a; θ)                  # select with the online net
    y  = r + gamma · (1 - done) · Q(o', a*; θ⁻)    # evaluate with the target net
    loss = Huber(Q(o, a; θ) - y)               # only the taken action's output gets a gradient

Exploration is ε-greedy, with ε decaying linearly. Observations go through
``log1p`` (counts span orders of magnitude) and a fixed standardization fitted
on observations from an initial random-exploration phase. A fixed normalizer
avoids the non-stationarity of running statistics.
"""

from __future__ import annotations

import json
import math
import random
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from forgecompile.ir.function import Module
from forgecompile.ml.features import feature_vector
from forgecompile.rl.env import ENV_ACTIONS, PassSchedulingEnv
from forgecompile.utils.logging import get_logger

_log = get_logger("rl")


@dataclass(frozen=True)
class DQNConfig:
    hidden: int = 128
    learning_rate: float = 1e-3
    gamma: float = 1.0  # undiscounted finite-horizon objective (RL_FORMULATION.md)
    batch_size: int = 64
    buffer_size: int = 50_000
    target_update: int = 250  # steps between target-network refreshes
    train_every: int = 1
    warmup_steps: int = 500  # random actions before learning; also fits the normalizer
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    epsilon_decay_steps: int = 6000
    huber_delta: float = 1.0
    seed: int = 0


class MLP:
    """Two hidden ReLU layers. Forward caches activations; backward returns parameter gradients."""

    def __init__(self, n_in: int, n_hidden: int, n_out: int, rng: np.random.Generator) -> None:
        def he(fan_in: int, fan_out: int) -> np.ndarray:
            return rng.normal(0.0, math.sqrt(2.0 / fan_in), size=(fan_in, fan_out))

        self.params: dict[str, np.ndarray] = {
            "W1": he(n_in, n_hidden), "b1": np.zeros(n_hidden),
            "W2": he(n_hidden, n_hidden), "b2": np.zeros(n_hidden),
            "W3": he(n_hidden, n_out) * 0.1, "b3": np.zeros(n_out),
        }  # fmt: skip

    def forward(self, x: np.ndarray) -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
        p = self.params
        z1 = x @ p["W1"] + p["b1"]
        h1 = np.maximum(z1, 0.0)
        z2 = h1 @ p["W2"] + p["b2"]
        h2 = np.maximum(z2, 0.0)
        out = h2 @ p["W3"] + p["b3"]
        return out, (x, z1, h1, z2, h2)

    def backward(
        self, grad_out: np.ndarray, cache: tuple[np.ndarray, ...]
    ) -> dict[str, np.ndarray]:
        p = self.params
        x, z1, h1, z2, h2 = cache
        grads = {"W3": h2.T @ grad_out, "b3": grad_out.sum(axis=0)}
        d_h2 = grad_out @ p["W3"].T
        d_z2 = d_h2 * (z2 > 0)
        grads["W2"] = h1.T @ d_z2
        grads["b2"] = d_z2.sum(axis=0)
        d_h1 = d_z2 @ p["W2"].T
        d_z1 = d_h1 * (z1 > 0)
        grads["W1"] = x.T @ d_z1
        grads["b1"] = d_z1.sum(axis=0)
        return grads

    def copy_from(self, other: MLP) -> None:
        self.params = {k: v.copy() for k, v in other.params.items()}


class Adam:
    def __init__(self, params: dict[str, np.ndarray], lr: float) -> None:
        self.lr, self.b1, self.b2, self.eps, self.t = lr, 0.9, 0.999, 1e-8, 0
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}

    def step(self, params: dict[str, np.ndarray], grads: dict[str, np.ndarray]) -> None:
        self.t += 1
        for k, g in grads.items():
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * g * g
            m_hat = self.m[k] / (1 - self.b1**self.t)
            v_hat = self.v[k] / (1 - self.b2**self.t)
            params[k] -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


@dataclass
class Normalizer:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, observations: np.ndarray) -> Normalizer:
        logged = np.log1p(np.maximum(observations, 0.0))
        return cls(logged.mean(axis=0), logged.std(axis=0) + 1e-6)

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        return (np.log1p(np.maximum(obs, 0.0)) - self.mean) / self.std


@dataclass
class TrainingLog:
    episode_returns: list[float] = field(default_factory=list)
    episode_ratios: list[float] = field(default_factory=list)
    losses: list[float] = field(default_factory=list)
    epsilons: list[float] = field(default_factory=list)
    validation: list[tuple[int, float]] = field(default_factory=list)  # (episode, geomean ratio)
    invalid_transformations: int = 0


class DQNAgent:
    def __init__(self, obs_size: int, n_actions: int, config: DQNConfig) -> None:
        self.config = config
        self.n_actions = n_actions
        self.np_rng = np.random.default_rng(config.seed)
        self.rng = random.Random(config.seed)
        self.online = MLP(obs_size, config.hidden, n_actions, self.np_rng)
        self.target = MLP(obs_size, config.hidden, n_actions, self.np_rng)
        self.target.copy_from(self.online)
        self.optimizer = Adam(self.online.params, config.learning_rate)
        self.buffer: deque[tuple[np.ndarray, int, float, np.ndarray, bool]] = deque(
            maxlen=config.buffer_size
        )
        self.normalizer: Normalizer | None = None
        self.steps = 0

    def q_values(self, obs: np.ndarray) -> np.ndarray:
        assert self.normalizer is not None
        out, _ = self.online.forward(self.normalizer(obs)[None, :])
        return out[0]

    def act(self, obs: np.ndarray, epsilon: float) -> int:
        if self.normalizer is None or self.rng.random() < epsilon:
            return self.rng.randrange(self.n_actions)
        return int(np.argmax(self.q_values(obs)))

    def epsilon(self) -> float:
        c = self.config
        progress = min(1.0, max(0, self.steps - c.warmup_steps) / c.epsilon_decay_steps)
        return c.epsilon_start + progress * (c.epsilon_end - c.epsilon_start)

    def learn(self) -> float:
        c = self.config
        assert self.normalizer is not None
        batch = self.rng.sample(self.buffer, c.batch_size)
        obs = self.normalizer(np.array([b[0] for b in batch]))
        actions = np.array([b[1] for b in batch])
        rewards = np.array([b[2] for b in batch])
        next_obs = self.normalizer(np.array([b[3] for b in batch]))
        done = np.array([b[4] for b in batch], dtype=float)

        q_next_online, _ = self.online.forward(next_obs)
        q_next_target, _ = self.target.forward(next_obs)
        best_next = np.argmax(q_next_online, axis=1)  # Double DQN: select with online...
        bootstrap = q_next_target[np.arange(len(batch)), best_next]  # ...evaluate with target
        targets = rewards + c.gamma * (1.0 - done) * bootstrap

        q, cache = self.online.forward(obs)
        error = q[np.arange(len(batch)), actions] - targets
        # Huber loss gradient: linear beyond delta keeps rare large errors from dominating.
        grad_error = np.clip(error, -c.huber_delta, c.huber_delta) / len(batch)
        grad_out = np.zeros_like(q)
        grad_out[np.arange(len(batch)), actions] = grad_error
        self.optimizer.step(self.online.params, self.online.backward(grad_out, cache))
        abs_err = np.abs(error)
        loss = np.where(
            abs_err <= c.huber_delta,
            0.5 * error**2,
            c.huber_delta * (abs_err - 0.5 * c.huber_delta),
        )
        return float(loss.mean())

    # ------------------------------------------------------------------ persistence

    def save(self, path: Path) -> None:
        assert self.normalizer is not None
        arrays = {f"param_{k}": v for k, v in self.online.params.items()}
        arrays["norm_mean"], arrays["norm_std"] = self.normalizer.mean, self.normalizer.std
        np.savez(str(path), **arrays)  # type: ignore[arg-type]  # numpy stub mis-types **kwargs
        path.with_suffix(".json").write_text(json.dumps(asdict(self.config)), "utf-8")

    @classmethod
    def load(cls, path: Path, obs_size: int, n_actions: int) -> DQNAgent:
        config = DQNConfig(**json.loads(path.with_suffix(".json").read_text("utf-8")))
        agent = cls(obs_size, n_actions, config)
        data = np.load(path)
        agent.online.params = {
            k[len("param_") :]: data[k] for k in data.files if k.startswith("param_")
        }
        agent.normalizer = Normalizer(data["norm_mean"], data["norm_std"])
        return agent


def train(
    env: PassSchedulingEnv,
    agent: DQNAgent,
    episodes: int,
    validate: Any = None,  # callable(agent) -> geomean ratio on validation programs
    validate_every: int = 100,
    checkpoint: Path | None = None,
) -> TrainingLog:
    """Train for ``episodes`` episodes. If ``validate`` is given, keep the best checkpoint."""
    log = TrainingLog()
    warm_obs: list[np.ndarray] = []
    best_val = math.inf
    for episode in range(episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            epsilon = agent.epsilon()
            action = agent.act(obs, epsilon)
            next_obs, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
            agent.buffer.append((obs, action, reward, next_obs, done))
            agent.steps += 1
            if agent.normalizer is None:
                warm_obs.append(obs)
                if agent.steps >= agent.config.warmup_steps:
                    agent.normalizer = Normalizer.fit(np.array(warm_obs))
            elif (
                len(agent.buffer) >= agent.config.batch_size
                and agent.steps % agent.config.train_every == 0
            ):
                log.losses.append(agent.learn())
            if agent.steps % agent.config.target_update == 0:
                agent.target.copy_from(agent.online)
            obs = next_obs
        log.episode_returns.append(env.stats.total_reward)
        log.episode_ratios.append(env.stats.final_cost / env.stats.initial_cost)
        log.epsilons.append(agent.epsilon())
        if (
            validate is not None
            and agent.normalizer is not None
            and (episode + 1) % validate_every == 0
        ):
            score = float(validate(agent))
            log.validation.append((episode + 1, score))
            if score < best_val:
                best_val = score
                if checkpoint is not None:
                    agent.save(checkpoint)
            recent = log.episode_ratios[-validate_every:]
            _log.info(  # continuous progress for long runs (one line per validation)
                "episode %d steps %d epsilon %.3f train-ratio %.4f val %.4f best %.4f",
                episode + 1,
                agent.steps,
                agent.epsilon(),
                sum(recent) / len(recent),
                score,
                best_val,
            )
    if agent.normalizer is None and warm_obs:
        # Training ended inside the warm-up (very short runs): fit on what was seen,
        # so the agent is still usable and savable.
        agent.normalizer = Normalizer.fit(np.array(warm_obs))
    log.invalid_transformations = env.invalid_transformations
    return log


@dataclass
class DQNPolicy:
    """Greedy policy from a trained agent, usable with ``ml.policies.schedule``."""

    agent: DQNAgent
    horizon: int = 12
    name: str = "dqn"
    actions: list[str] = field(default_factory=lambda: list(ENV_ACTIONS))  # as in the env
    _t: int = 0
    _last: int | None = None

    def reset(self) -> None:
        self._t, self._last = 0, None

    def choose(self, module: Module) -> str:
        last = np.zeros(len(self.actions))
        if self._last is not None:
            last[self._last] = 1.0
        remaining = (self.horizon - self._t) / self.horizon
        obs = np.concatenate([np.array(feature_vector(module)), [remaining], last])
        action = int(np.argmax(self.agent.q_values(obs)))
        self._t += 1
        self._last = action
        return self.actions[action]
