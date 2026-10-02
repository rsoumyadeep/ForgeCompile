"""Benchmark runner: correctness checks, interpreter metrics and interleaved native timing.

Protocol for one invocation:

1. **Correctness.** For every (benchmark, configuration) pair, run the small
   instance natively and on the IR interpreter. Outputs must be identical. The
   unoptimized interpreter output is the reference, and any disagreement
   aborts the run. Timing an incorrect program would be meaningless.
2. **Static and interpreter metrics** on the small instance.
3. **Native timing** of the large instance. Executables are built once. After
   one warm-up run each, ``repeats`` rounds are executed, and every round runs
   all configurations of a benchmark in a freshly shuffled (seeded) order. This
   interleaving spreads slow drifts (thermal throttling, background load)
   evenly across configurations rather than penalizing whichever runs last.
   All large-instance outputs of a benchmark must agree.
4. A **startup baseline** (an empty program) is timed with the same protocol,
   so the fixed process-creation cost is reported, not hidden.

Everything is recorded through :class:`~forgecompile.utils.experiment.ExperimentRun`.
"""

from __future__ import annotations

import random
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from forgecompile.backend.native import build_and_run
from forgecompile.benchmarking.measure import (
    BenchConfig,
    InterpMetrics,
    NativeMetrics,
    StaticMetrics,
    build_native,
    compile_config,
    interpret,
    sha1,
    time_native,
)
from forgecompile.benchmarking.suite import Benchmark
from forgecompile.optimization.pass_manager import PRESETS
from forgecompile.utils.logging import get_logger

log = get_logger("benchmarking")

DEFAULT_CONFIGS: list[BenchConfig] = [
    BenchConfig("fc-O0.llvm-O0", tuple(PRESETS["O0"]), 0),
    BenchConfig("fc-O1.llvm-O0", tuple(PRESETS["O1"]), 0),
    BenchConfig("fc-O2.llvm-O0", tuple(PRESETS["O2"]), 0),
    BenchConfig("fc-O0.llvm-O2", tuple(PRESETS["O0"]), 2),
    BenchConfig("fc-O2.llvm-O2", tuple(PRESETS["O2"]), 2),
]

STARTUP_PROGRAM = "fn main() { }"


class BenchmarkMismatch(Exception):
    """Two configurations produced different output: a compiler bug, so the run is aborted."""


@dataclass
class TimingSummary:
    times: list[float]

    @property
    def median(self) -> float:
        return statistics.median(self.times)

    @property
    def minimum(self) -> float:
        return min(self.times)

    @property
    def iqr(self) -> float:
        if len(self.times) < 4:
            return max(self.times) - min(self.times)
        q = statistics.quantiles(self.times, n=4)
        return q[2] - q[0]

    @property
    def cv(self) -> float:
        """Coefficient of variation (stdev / mean): the relative noise of this measurement."""
        if len(self.times) < 2:
            return 0.0
        return statistics.stdev(self.times) / statistics.mean(self.times)


@dataclass
class BenchRecord:
    benchmark: str
    workload_class: str
    config: str
    passes: list[str]
    llvm_opt: int
    static: StaticMetrics
    interp: InterpMetrics
    native_compile_seconds: float = 0.0
    native_times: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        timing = TimingSummary(self.native_times) if self.native_times else None
        return {
            "benchmark": self.benchmark,
            "class": self.workload_class,
            "config": self.config,
            "llvm_opt": self.llvm_opt,
            "interp_steps": self.interp.steps,
            "interp_cost": self.interp.cost,
            "ir_instructions": self.static.ir_instructions,
            "text_bytes": self.static.text_bytes,
            "pass_ms": round(self.static.pass_ms, 3),
            "native_compile_s": round(self.native_compile_seconds, 3),
            "native_median_s": timing.median if timing else None,
            "native_min_s": timing.minimum if timing else None,
            "native_iqr_s": timing.iqr if timing else None,
            "native_cv": timing.cv if timing else None,
        }


@dataclass
class SuiteResult:
    records: list[BenchRecord]
    startup: TimingSummary | None
    repeats: int
    seed: int

    def to_json(self) -> dict[str, Any]:
        return {
            "repeats": self.repeats,
            "seed": self.seed,
            "startup_times": self.startup.times if self.startup else None,
            "records": [asdict(r) | {"summary": r.summary()} for r in self.records],
        }


def _check_small_instance(
    bench: Benchmark, configs: list[BenchConfig], native: bool
) -> dict[str, tuple[str, StaticMetrics, InterpMetrics]]:
    """Correctness gate: every config's interpreted (and, if ``native``, native) output must
    equal the reference: the first configuration's interpreter output."""
    source = bench.instantiate("small")
    reference: str | None = None
    results: dict[str, tuple[str, StaticMetrics, InterpMetrics]] = {}
    for config in configs:
        llvm_ir, static = compile_config(source, config)
        interp = interpret(source, config)
        if reference is None:
            reference = interp.stdout_sha1
        if interp.stdout_sha1 != reference:
            raise BenchmarkMismatch(
                f"{bench.name}/{config.name}: output differs from the reference"
            )
        if native:
            _, result = build_and_run(llvm_ir, config.llvm_opt)
            if result.exit_code != 0 or sha1(result.stdout) != reference:
                raise BenchmarkMismatch(
                    f"{bench.name}/{config.name}: native output differs from the reference "
                    f"(exit {result.exit_code}) {result.stderr}"
                )
        results[config.name] = (llvm_ir, static, interp)
    return results


def run_suite(
    benchmarks: list[Benchmark],
    configs: list[BenchConfig] | None = None,
    repeats: int = 5,
    seed: int = 0,
    native: bool = True,
    work_dir: Path | None = None,
) -> SuiteResult:
    configs = configs or DEFAULT_CONFIGS
    rng = random.Random(seed)
    records: list[BenchRecord] = []
    owned_tmp = (
        tempfile.TemporaryDirectory(prefix="forgecompile-bench-") if work_dir is None else None
    )
    out_dir = Path(owned_tmp.name) if owned_tmp else work_dir
    assert out_dir is not None
    try:
        startup = _time_startup(out_dir, repeats) if native else None
        for bench in benchmarks:
            log.info("benchmark %s", bench.name)
            checked = _check_small_instance(bench, configs, native)
            bench_records = {
                c.name: BenchRecord(
                    bench.name, bench.workload_class, c.name, list(c.passes), c.llvm_opt,
                    checked[c.name][1], checked[c.name][2],
                )
                for c in configs
            }  # fmt: skip
            if native:
                _time_large_instance(bench, configs, bench_records, repeats, rng, out_dir)
            records.extend(bench_records.values())
    finally:
        if owned_tmp:
            owned_tmp.cleanup()
    return SuiteResult(records, startup, repeats, seed)


def _time_large_instance(
    bench: Benchmark,
    configs: list[BenchConfig],
    records: dict[str, BenchRecord],
    repeats: int,
    rng: random.Random,
    out_dir: Path,
) -> None:
    source = bench.instantiate("large")
    builds: dict[str, NativeMetrics] = {}
    for config in configs:
        llvm_ir, _ = compile_config(source, config)
        builds[config.name] = build_native(llvm_ir, config, out_dir, bench.name)
        records[config.name].native_compile_seconds = builds[config.name].compile_seconds
    outputs = set()
    for config in configs:  # warm-up (file cache, page faults); not recorded
        _, digest = time_native(builds[config.name])
        outputs.add(digest)
    if len(outputs) != 1:
        raise BenchmarkMismatch(
            f"{bench.name}: large-instance outputs differ between configurations"
        )
    order = [c.name for c in configs]
    for _ in range(repeats):
        rng.shuffle(order)
        for name in order:
            seconds, _ = time_native(builds[name])
            records[name].native_times.append(seconds)


def _time_startup(out_dir: Path, repeats: int) -> TimingSummary:
    from forgecompile.driver import compile_to_llvm

    llvm_ir, _ = compile_to_llvm(STARTUP_PROGRAM)
    metrics = build_native(llvm_ir, BenchConfig("startup", (), 0), out_dir, "empty")
    time_native(metrics)  # warm-up
    return TimingSummary([time_native(metrics)[0] for _ in range(repeats)])
