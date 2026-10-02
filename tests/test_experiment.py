"""Tests for experiment-run bookkeeping."""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Iterator
from pathlib import Path

import pytest

from forgecompile.utils.experiment import ExperimentRun
from forgecompile.utils.logging import ROOT_LOGGER_NAME


@pytest.fixture(autouse=True)
def _close_log_handlers() -> Iterator[None]:
    # ExperimentRun opens a log file; close it so tmp_path can be removed on Windows.
    yield
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _read(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def test_create_writes_metadata_and_config(tmp_path: Path) -> None:
    run = ExperimentRun.create("EXP-000-smoke", {"passes": ["dce"]}, seed=7, runs_dir=tmp_path)

    assert run.run_dir.parent == tmp_path
    assert run.run_dir.name.startswith("EXP-000-smoke_")
    assert _read(run.run_dir / "config.json") == {"passes": ["dce"]}

    metadata = _read(run.run_dir / "metadata.json")
    assert metadata["experiment_id"] == "EXP-000-smoke"
    assert metadata["seed"] == 7
    assert metadata["status"] == "running"
    assert "python" in metadata["environment"]


def test_create_seeds_python_random(tmp_path: Path) -> None:
    ExperimentRun.create("EXP-000", {}, seed=123, runs_dir=tmp_path / "a")
    first = [random.random() for _ in range(3)]
    ExperimentRun.create("EXP-000", {}, seed=123, runs_dir=tmp_path / "b")
    second = [random.random() for _ in range(3)]
    assert first == second


def test_finalize_records_status_and_summary(tmp_path: Path) -> None:
    run = ExperimentRun.create("EXP-000", {}, seed=0, runs_dir=tmp_path)
    run.finalize("failed", {"reason": "verifier error"})
    metadata = _read(run.run_dir / "metadata.json")
    assert metadata["status"] == "failed"
    assert metadata["summary"] == {"reason": "verifier error"}
    assert "finished_utc" in metadata


def test_save_json_artifact(tmp_path: Path) -> None:
    run = ExperimentRun.create("EXP-000", {}, seed=0, runs_dir=tmp_path)
    path = run.save_json("results.json", {"speedup": None})
    assert _read(path) == {"speedup": None}


def test_save_json_rejects_paths(tmp_path: Path) -> None:
    run = ExperimentRun.create("EXP-000", {}, seed=0, runs_dir=tmp_path)
    with pytest.raises(ValueError):
        run.save_json("../escape.json", {})


def test_run_log_is_written(tmp_path: Path) -> None:
    run = ExperimentRun.create("EXP-000", {}, seed=0, runs_dir=tmp_path)
    for handler in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        handler.flush()
    lines = (run.run_dir / "run.log").read_text("utf-8").strip().splitlines()
    assert json.loads(lines[0])["message"] == "started run"


@pytest.mark.parametrize("bad_id", ["exp-001", "EXP-1", "EXP-001/../x", "results"])
def test_invalid_experiment_id_rejected(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(ValueError, match="invalid experiment id"):
        ExperimentRun.create(bad_id, {}, seed=0, runs_dir=tmp_path)
