"""Benchmark suite discovery, measurement plumbing, correctness gate and reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.benchmarking import runner as runner_module
from forgecompile.benchmarking.measure import BenchConfig, compile_config, interpret, text_bytes
from forgecompile.benchmarking.report import (
    geomean,
    geomean_speedups,
    markdown_table,
    speedups,
    to_csv,
)
from forgecompile.benchmarking.runner import BenchmarkMismatch, TimingSummary, run_suite
from forgecompile.benchmarking.suite import BenchmarkError, load_benchmark, load_suite
from forgecompile.cli.bench_commands import parse_config
from forgecompile.cli.common import CliError
from forgecompile.driver import check_source

EXPECTED_CLASSES = {"arith", "branch", "call", "loop", "matrix", "memory", "vector"}


def write_bench(directory: Path, name: str, body: str) -> Path:
    path = directory / f"{name}.mini"
    path.write_text(body, "utf-8")
    return path


TINY = """
fn main() -> int {
    let reps = 3; // @size small=1 large=2
    let s = 0;
    for r in 0..reps { for i in 0..10 { s = s + i * 2 + 0; } }
    print(s);
    return 0;
}
"""


def test_suite_covers_required_workload_classes_and_type_checks() -> None:
    suite = load_suite()
    assert len(suite) >= 10
    assert {b.workload_class for b in suite} >= EXPECTED_CLASSES
    for bench in suite:
        assert bench.small < bench.large
        check_source(bench.instantiate("small"))
        check_source(bench.instantiate("large"))


def test_instantiate_replaces_only_the_size(tmp_path: Path) -> None:
    bench = load_benchmark(write_bench(tmp_path, "loop_tiny", TINY))
    assert "let reps = 1; // @size small=1 large=2" in bench.instantiate("small")
    assert "let reps = 2;" in bench.instantiate("large")
    assert "let reps = 99;" in bench.instantiate(99)
    with pytest.raises(BenchmarkError):
        bench.instantiate("huge")


def test_missing_or_duplicate_size_annotation(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="exactly one"):
        load_benchmark(write_bench(tmp_path, "x_none", "fn main() { }"))
    doubled = TINY.replace("let s = 0;", "let t = 1; // @size small=1 large=2\n    let s = 0;")
    with pytest.raises(BenchmarkError, match="exactly one"):
        load_benchmark(write_bench(tmp_path, "x_two", doubled))


def test_unknown_benchmark_name() -> None:
    with pytest.raises(BenchmarkError, match="unknown benchmarks: nope"):
        load_suite(names=["nope"])


def test_static_and_interpreter_metrics() -> None:
    o0 = BenchConfig("O0", (), 0)
    o1 = BenchConfig("O1", ("copyprop", "constfold", "dce"), 0)
    llvm_ir, static0 = compile_config(TINY, o0)
    _, static1 = compile_config(TINY, o1)
    assert static1.ir_instructions < static0.ir_instructions
    assert text_bytes(llvm_ir, 0) == static0.text_bytes > 0
    i0, i1 = interpret(TINY, o0), interpret(TINY, o1)
    assert i1.cost < i0.cost and i0.stdout_sha1 == i1.stdout_sha1


def test_parse_config() -> None:
    config = parse_config("mine=copyprop,bce@2")
    assert config == BenchConfig("mine", ("copyprop", "bce"), 2)
    assert parse_config("o2=O2@0").passes[0] == "inline"
    with pytest.raises(CliError):
        parse_config("broken")


def test_report_helpers() -> None:
    rows = [
        {"benchmark": "b", "config": "fc-O0.llvm-O0", "native_median_s": 2.0, "native_cv": 0.01,
         "interp_cost": 10.0, "ir_instructions": 5, "text_bytes": 100, "pass_ms": 0.0},
        {"benchmark": "b", "config": "fast", "native_median_s": 0.5, "native_cv": 0.02,
         "interp_cost": 8.0, "ir_instructions": 4, "text_bytes": 90, "pass_ms": 1.0},
    ]  # fmt: skip
    assert speedups(rows) == {"b": {"fc-O0.llvm-O0": 1.0, "fast": 4.0}}
    assert geomean_speedups(rows)["fast"] == pytest.approx(4.0)
    assert "| b | fast | 0.5000 | 2.0% | 4.00x |" in markdown_table(rows)
    assert to_csv(rows).splitlines()[0].startswith("benchmark,config")
    assert geomean([1.0, 4.0]) == pytest.approx(2.0)


def test_timing_summary_statistics() -> None:
    summary = TimingSummary([1.0, 2.0, 3.0, 4.0, 100.0])
    assert summary.median == 3.0 and summary.minimum == 1.0
    assert summary.cv > 1.0  # one outlier dominates: the CV makes this visible


def test_run_suite_interpreter_only(tmp_path: Path) -> None:
    write_bench(tmp_path, "loop_tiny", TINY)
    configs = [BenchConfig("fc-O0.llvm-O0", (), 0), BenchConfig("o1", ("copyprop", "dce"), 0)]
    result = run_suite(load_suite(tmp_path), configs, repeats=1, native=False)
    assert [r.config for r in result.records] == ["fc-O0.llvm-O0", "o1"]
    assert result.records[1].interp.cost <= result.records[0].interp.cost
    assert result.startup is None and not result.records[0].native_times


@pytest.mark.native
def test_run_suite_native_timing(tmp_path: Path) -> None:
    write_bench(tmp_path, "loop_tiny", TINY)
    configs = [BenchConfig("fc-O0.llvm-O0", (), 0), BenchConfig("fast", ("copyprop",), 2)]
    result = run_suite(load_suite(tmp_path), configs, repeats=2, seed=1)
    assert all(len(r.native_times) == 2 for r in result.records)
    assert result.startup is not None and len(result.startup.times) == 2
    summary = result.records[1].summary()
    assert summary["native_median_s"] > 0 and summary["text_bytes"] > 0
    assert "records" in result.to_json()


def test_correctness_gate_aborts_on_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_bench(tmp_path, "loop_tiny", TINY)
    real_interpret = runner_module.interpret

    def lying_interpret(source: str, config: BenchConfig) -> object:
        metrics = real_interpret(source, config)
        if config.name == "o1":
            metrics.stdout_sha1 = "0" * 16  # pretend this configuration miscompiled
        return metrics

    monkeypatch.setattr(runner_module, "interpret", lying_interpret)
    configs = [BenchConfig("fc-O0.llvm-O0", (), 0), BenchConfig("o1", ("dce",), 0)]
    with pytest.raises(BenchmarkMismatch, match="o1"):
        run_suite(load_suite(tmp_path), configs, repeats=1, native=False)


def test_correlation_helpers_against_known_values() -> None:
    from forgecompile.benchmarking.stats import pearson, ranks, spearman

    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0]
    # Monotone but non-linear: Spearman is exactly 1, Pearson is below 1.
    xs, ys = [1, 2, 3, 4, 5], [1, 4, 9, 16, 100]
    assert spearman(xs, ys) == pytest.approx(1.0)
    assert pearson(xs, ys) < 0.95
