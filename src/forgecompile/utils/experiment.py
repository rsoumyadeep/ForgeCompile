"""Experiment-run bookkeeping.

An *experiment* (e.g. ``EXP-003``) is a question with a hypothesis, documented
in docs/EXPERIMENTS.md. A *run* is one execution of the code that answers it.
Each run gets its own directory::

    experiments/runs/<EXP-ID>_<UTC timestamp>/
        metadata.json   # id, seed, config, environment, git commit, status
        config.json     # the exact configuration used
        run.log         # JSON-lines log
        <artifacts>     # results written via ExperimentRun.save_json

The goal is that every number reported in docs/RESULTS.md can be traced back
to a run directory containing the configuration, seed and environment that
produced it.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forgecompile.utils.environment import collect_environment
from forgecompile.utils.logging import configure_logging, get_logger

_EXPERIMENT_ID_PATTERN = re.compile(r"^EXP-\d{3}[A-Za-z0-9_-]*$")
DEFAULT_RUNS_DIR = Path("experiments") / "runs"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", "utf-8")


@dataclass
class ExperimentRun:
    """A single experiment run with its own output directory."""

    experiment_id: str
    seed: int
    config: dict[str, Any]
    run_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        experiment_id: str,
        config: dict[str, Any],
        seed: int,
        runs_dir: Path = DEFAULT_RUNS_DIR,
        repo_dir: Path | None = None,
    ) -> ExperimentRun:
        """Create the run directory, record metadata, seed RNGs, start logging."""
        if not _EXPERIMENT_ID_PATTERN.match(experiment_id):
            raise ValueError(
                f"invalid experiment id {experiment_id!r}; expected e.g. 'EXP-001' or 'EXP-001-cse'"
            )
        started = _utc_now()
        run_dir = runs_dir / f"{experiment_id}_{started.strftime('%Y%m%dT%H%M%S%fZ')}"
        run_dir.mkdir(parents=True, exist_ok=False)

        # Seed every RNG we control. Libraries added later (numpy, torch)
        # must also be seeded from `seed` by the code that imports them.
        random.seed(seed)

        metadata: dict[str, Any] = {
            "experiment_id": experiment_id,
            "seed": seed,
            "started_utc": started.isoformat(),
            "status": "running",
            "environment": collect_environment(repo_dir),
        }
        run = cls(experiment_id, seed, dict(config), run_dir, metadata)
        _write_json(run_dir / "config.json", run.config)
        run._write_metadata()

        configure_logging(level="INFO", log_file=run_dir / "run.log")
        get_logger("experiment").info(
            "started run", extra={"data": {"experiment_id": experiment_id, "seed": seed}}
        )
        return run

    def save_json(self, name: str, obj: Any) -> Path:
        """Write an artifact into the run directory and return its path."""
        if Path(name).name != name:
            raise ValueError(f"artifact name must be a plain file name, got {name!r}")
        path = self.run_dir / name
        _write_json(path, obj)
        return path

    def finalize(self, status: str = "completed", summary: dict[str, Any] | None = None) -> None:
        """Mark the run finished. ``status`` should be 'completed' or 'failed'.

        Failed runs are kept, not deleted: they are evidence (docs/FAILURES.md).
        """
        self.metadata["status"] = status
        self.metadata["finished_utc"] = _utc_now().isoformat()
        if summary is not None:
            self.metadata["summary"] = summary
        self._write_metadata()

    def _write_metadata(self) -> None:
        _write_json(self.run_dir / "metadata.json", self.metadata)
