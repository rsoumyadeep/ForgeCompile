"""Tests for the top-level CLI (Phase 0 surface: --version, info)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from forgecompile import __version__
from forgecompile.cli.main import EXIT_OK, EXIT_USAGE, main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help_and_returns_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == EXIT_USAGE
    assert "usage: forgecompile" in capsys.readouterr().err


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["definitely-not-a-command"])
    assert excinfo.value.code == EXIT_USAGE


def test_info_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info"]) == EXIT_OK
    out = capsys.readouterr().out
    assert f"ForgeCompile {__version__}" in out
    assert "Toolchain:" in out
    assert "llvmlite" in out


def test_info_json_is_valid(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", "--json"]) == EXIT_OK
    env = json.loads(capsys.readouterr().out)
    assert env["forgecompile_version"] == __version__
    assert {tool["name"] for tool in env["tools"]} == {"llvmlite", "zig", "clang"}


def test_python_dash_m_entry_point() -> None:
    """`python -m forgecompile` must work in a fresh interpreter, not just in-process."""
    result = subprocess.run(
        [sys.executable, "-m", "forgecompile", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout
