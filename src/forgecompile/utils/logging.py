"""Logging configuration shared by the compiler, benchmarks and experiments.

Two output formats are supported:

* ``text``  - human-readable lines for interactive CLI use.
* ``json``  - one JSON object per line, used by experiment runs so that logs
  can be parsed later (e.g. to recover per-episode statistics).

All ForgeCompile loggers live under the ``forgecompile`` namespace, so
``configure_logging`` never touches loggers belonging to other libraries.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

ROOT_LOGGER_NAME = "forgecompile"
LOG_LEVEL_ENV_VAR = "FORGECOMPILE_LOG_LEVEL"
_TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class JsonLineFormatter(logging.Formatter):
    """Format each record as a single JSON object (JSON Lines)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Structured fields can be attached with logger.info(..., extra={"data": {...}}).
        data = getattr(record, "data", None)
        if data is not None:
            payload["data"] = data
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a logger in the ForgeCompile namespace (``forgecompile.<name>``)."""
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def configure_logging(
    level: str | int | None = None,
    log_file: Path | None = None,
    fmt: str = "text",
) -> logging.Logger:
    """Configure the ``forgecompile`` root logger and return it.

    Precedence for the level: explicit argument, then the
    ``FORGECOMPILE_LOG_LEVEL`` environment variable, then ``WARNING``.
    Calling this repeatedly replaces previously installed handlers, so it is
    safe to call from both the CLI and tests.
    """
    if fmt not in ("text", "json"):
        raise ValueError(f"unknown log format {fmt!r}; expected 'text' or 'json'")

    resolved = level if level is not None else os.environ.get(LOG_LEVEL_ENV_VAR, "WARNING")
    if isinstance(resolved, str):
        resolved = resolved.upper()

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(resolved)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter: logging.Formatter = (
        JsonLineFormatter() if fmt == "json" else logging.Formatter(_TEXT_FORMAT)
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        # Files always get JSON lines: they are meant to be machine-read.
        file_handler.setFormatter(JsonLineFormatter())
        logger.addHandler(file_handler)

    return logger
