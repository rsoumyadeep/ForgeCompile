"""CLI tests for `opt`, `passes`, and `run -O`."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.cli.main import EXIT_COMPILE_ERROR, EXIT_OK, main

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_passes_lists_everything(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["passes"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "constfold" in out and "licm" in out and "O2" in out


def test_opt_with_passes_and_stats(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["opt", "--passes", "copyprop,dce", "--stats", str(EXAMPLES / "gcd.mini")]) == EXIT_OK
    )
    captured = capsys.readouterr()
    assert "func @gcd" in captured.out and "copy" not in captured.out
    assert "copyprop" in captured.err and "insts" in captured.err


def test_run_with_opt_level(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "-O", "2", str(EXAMPLES / "primes.mini")]) == EXIT_OK
    assert capsys.readouterr().out == "25\n53\n"


def test_conflicting_options(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["opt", "--passes", "dce", "-O", "1", str(EXAMPLES / "gcd.mini")])
    assert code == EXIT_COMPILE_ERROR
    assert "either --passes or -O" in capsys.readouterr().err


def test_unknown_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["opt", "--passes", "magic", str(EXAMPLES / "gcd.mini")]) == EXIT_COMPILE_ERROR
    assert "unknown pass 'magic'" in capsys.readouterr().err


def test_run_with_oracle_schedule(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--schedule", "oracle", str(EXAMPLES / "primes.mini")]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "25\n53\n" and "schedule (oracle):" in captured.err


def test_opt_with_dqn_checkpoint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import numpy as np

    from forgecompile.ml.features import FEATURE_NAMES
    from forgecompile.rl.dqn import DQNAgent, DQNConfig, Normalizer
    from forgecompile.rl.env import ENV_ACTIONS

    n = len(ENV_ACTIONS)
    agent = DQNAgent(len(FEATURE_NAMES) + 1 + n, n, DQNConfig())
    agent.normalizer = Normalizer(np.zeros(agent.online.params["W1"].shape[0]), np.ones(1))
    agent.save(tmp_path / "agent.npz")
    args = ["opt", "--schedule", "dqn", "--checkpoint", str(tmp_path / "agent.npz")]
    assert main([*args, "--max-passes", "3", str(EXAMPLES / "gcd.mini")]) == EXIT_OK
    assert "schedule (dqn):" in capsys.readouterr().err


def test_schedule_conflicts_with_passes(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["opt", "--schedule", "oracle", "-O", "2", str(EXAMPLES / "gcd.mini")])
    assert code != EXIT_OK
    assert "either --schedule or --passes/-O" in capsys.readouterr().err
