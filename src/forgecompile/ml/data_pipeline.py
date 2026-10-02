"""Dataset construction shared by the ML (Phase 7) and RL (Phases 8-10) experiments.

**Splits, chosen to prevent leakage.** Every state recorded from a program
lands in the same split as that program. States from one program are highly
correlated, so splitting by *state* would leak near-duplicates into the test
set.

* ``train`` / ``val`` / ``test``: generated programs (``LOOP_HEAVY`` profile)
  with disjoint seed ranges;
* ``ood``: out-of-distribution, hand-written programs: the benchmark kernels
  (small instances) and the examples. They are never used for training or model
  selection. They answer "does it generalize beyond the generator?".

**Determinism.** Each program has its own trajectory RNG seed, derived from
the dataset seed and the program's identity. Results therefore do not depend on
how programs are distributed over worker processes.

**Caching.** Datasets are cached as JSON-lines under ``experiments/data/``
(git-ignored). The cache key includes the configuration *and* the git commit,
so a changed compiler never silently reuses stale labels. Without a clean
commit, nothing is cached.
"""

from __future__ import annotations

import hashlib
import json
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from forgecompile.benchmarking.suite import load_suite
from forgecompile.ml.dataset import (
    CostEvaluator,
    ProgramSpec,
    StateRecord,
    record_from_json,
    record_to_json,
    trajectory,
)
from forgecompile.testing.program_generator import LOOP_HEAVY, GeneratorConfig, generate_program
from forgecompile.utils.environment import git_revision

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = REPO / "experiments" / "data"
SPLITS = ("train", "val", "test", "ood")


@dataclass(frozen=True)
class DatasetConfig:
    n_train: int = 400
    n_val: int = 100
    n_test: int = 100
    first_seed: int = 100_000  # disjoint from seeds used by the correctness tests
    steps: int = 8
    epsilon: float = 0.3
    metric: str = "cost"
    seed: int = 0

    def key(self) -> str:
        revision = git_revision(REPO)
        commit = revision["commit"] if revision and not revision["dirty"] else None
        payload = json.dumps({"config": asdict(self), "commit": commit}, sort_keys=True)
        return hashlib.sha1(payload.encode()).hexdigest()[:16] if commit else ""


def program_splits(
    config: DatasetConfig, profile: GeneratorConfig = LOOP_HEAVY
) -> dict[str, list[ProgramSpec]]:
    seeds = {
        "train": range(config.first_seed, config.first_seed + config.n_train),
        "val": range(
            config.first_seed + config.n_train, config.first_seed + config.n_train + config.n_val
        ),
    }
    start_test = config.first_seed + config.n_train + config.n_val
    seeds["test"] = range(start_test, start_test + config.n_test)
    splits = {
        name: [ProgramSpec(f"gen{s}", generate_program(s, profile), "generated") for s in rng]
        for name, rng in seeds.items()
    }
    ood = [ProgramSpec(b.name, b.instantiate("small"), "benchmark") for b in load_suite()]
    ood += [
        ProgramSpec(p.stem, p.read_text("utf-8"), "example")
        for p in sorted((REPO / "examples").glob("*.mini"))
    ]
    splits["ood"] = ood
    return splits


def _program_seed(config: DatasetConfig, program: ProgramSpec) -> int:
    digest = hashlib.sha1(f"{config.seed}:{program.origin}:{program.name}".encode()).hexdigest()
    return int(digest[:12], 16)


def _worker(args: tuple[DatasetConfig, list[ProgramSpec]]) -> list[dict[str, object]]:
    config, programs = args
    evaluator = CostEvaluator(config.metric)
    out: list[dict[str, object]] = []
    for program in programs:
        rng = random.Random(_program_seed(config, program))
        out.extend(
            record_to_json(r)
            for r in trajectory(program, config.steps, config.epsilon, rng, evaluator)
        )
    return out


def build_dataset(
    config: DatasetConfig,
    workers: int = 4,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, list[StateRecord]]:
    key = config.key()
    cache_file = cache_dir / f"dataset-{key}.jsonl" if key else None
    if cache_file is not None and cache_file.exists():
        return _load(cache_file)
    splits = program_splits(config)
    result: dict[str, list[StateRecord]] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for name, programs in splits.items():
            chunks = [programs[i::workers] for i in range(workers) if programs[i::workers]]
            raw = [r for chunk in pool.map(_worker, [(config, c) for c in chunks]) for r in chunk]
            # Canonical order (program, step), independent of the chunking.
            raw.sort(key=lambda r: (str(r["program"]), int(str(r["step"]))))
            result[name] = [record_from_json(r) for r in raw]
    if cache_file is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with cache_file.open("w", encoding="utf-8", newline="\n") as fh:
            for name, records in result.items():
                for record in records:
                    fh.write(json.dumps({"split": name, **record_to_json(record)}) + "\n")
    return result


def _load(path: Path) -> dict[str, list[StateRecord]]:
    result: dict[str, list[StateRecord]] = {name: [] for name in SPLITS}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            data = json.loads(line)
            split = data.pop("split")
            result[split].append(record_from_json(data))
    return result
