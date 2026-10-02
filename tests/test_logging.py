"""Tests for logging configuration."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from forgecompile.utils.logging import ROOT_LOGGER_NAME, configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_logger() -> Iterator[None]:
    yield
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_get_logger_is_namespaced() -> None:
    assert get_logger("frontend").name == "forgecompile.frontend"
    assert get_logger("forgecompile.ir").name == "forgecompile.ir"


def test_reconfiguring_does_not_duplicate_handlers() -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    assert len(logging.getLogger(ROOT_LOGGER_NAME).handlers) == 1


def test_env_var_controls_default_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGECOMPILE_LOG_LEVEL", "debug")
    assert configure_logging().level == logging.DEBUG


def test_invalid_format_rejected() -> None:
    with pytest.raises(ValueError, match="unknown log format"):
        configure_logging(fmt="xml")


def test_log_file_contains_json_lines_with_structured_data(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "run.log"
    configure_logging("INFO", log_file=log_file)
    get_logger("test").info("episode done", extra={"data": {"episode": 3, "reward": 0.5}})
    for handler in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        handler.flush()

    record = json.loads(log_file.read_text("utf-8").strip().splitlines()[-1])
    assert record["message"] == "episode done"
    assert record["logger"] == "forgecompile.test"
    assert record["data"] == {"episode": 3, "reward": 0.5}
