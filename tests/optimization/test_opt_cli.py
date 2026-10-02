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
