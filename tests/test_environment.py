"""Tests for environment capture and toolchain detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forgecompile.utils import environment
from forgecompile.utils.environment import ToolStatus, collect_environment, git_revision


def test_collect_environment_is_json_serialisable() -> None:
    env = collect_environment()
    round_tripped = json.loads(json.dumps(env))
    assert round_tripped["python"]["version"]
    assert isinstance(round_tripped["cpu_count"], int)


def test_detect_tools_returns_one_status_per_tool() -> None:
    tools = environment.detect_tools()
    assert [tool.name for tool in tools] == ["llvmlite", "zig", "clang"]
    for tool in tools:
        assert isinstance(tool, ToolStatus)
        # An unavailable tool must explain why (actionable `info` output).
        if not tool.available:
            assert tool.detail


def test_git_revision_outside_repo_is_none(tmp_path: Path) -> None:
    assert git_revision(tmp_path) is None


def test_missing_zig_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "_run", lambda cmd, cwd=None: None)
    monkeypatch.setattr(environment.shutil, "which", lambda name: None)
    status = environment.detect_zig()
    assert not status.available
    assert "ziglang" in (status.detail or "")
