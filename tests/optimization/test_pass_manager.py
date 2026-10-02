"""Pass registry, pipeline parsing, statistics, and verification after each pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.driver import build_ir
from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import ReturnInst
from forgecompile.optimization.pass_manager import (
    PRESETS,
    FunctionPass,
    PassManager,
    PassResult,
    available_passes,
    optimize,
    parse_pipeline,
)

EXPECTED_PASSES = {
    "bce", "constfold", "copyprop", "cse", "dce", "inline",
    "licm", "sccp", "simplify", "simplifycfg", "strength",
}  # fmt: skip


def test_registry_contains_all_passes_with_descriptions() -> None:
    passes = available_passes()
    assert set(passes) == EXPECTED_PASSES
    assert all(cls.description for cls in passes.values())


def test_presets_only_name_real_passes() -> None:
    for names in PRESETS.values():
        assert set(names) <= EXPECTED_PASSES


def test_parse_pipeline_forms(tmp_path: Path) -> None:
    assert parse_pipeline("dce,cse, licm") == ["dce", "cse", "licm"]
    assert parse_pipeline("O1") == PRESETS["O1"]
    file = tmp_path / "my.pipeline"
    file.write_text("# custom\nconstfold, dce\ncse  # trailing comment\n", "utf-8")
    assert parse_pipeline(str(file)) == ["constfold", "dce", "cse"]
    assert parse_pipeline("") == []


def test_unknown_pass_is_reported_with_alternatives() -> None:
    with pytest.raises(ValueError, match=r"unknown pass 'dcee'.*available passes: bce"):
        parse_pipeline("dce,dcee")


def test_report_records_per_pass_statistics() -> None:
    module = build_ir("fn main() { let x = 2 * 3; print(x + 0); }")
    report = optimize(module, ["copyprop", "constfold", "simplify", "dce"])
    assert [r.name for r in report.records] == ["copyprop", "constfold", "simplify", "dce"]
    first = report.records[0]
    assert first.changed and first.instructions_after < first.instructions_before
    assert first.stats["copies"] >= 1
    assert "copyprop" in report.summary()


def test_running_a_pass_twice_is_safe() -> None:
    module = build_ir("fn main() { let x = 1; for i in 0..3 { x = x + i; } print(x); }")
    report = optimize(module, ["copyprop", "copyprop", "dce", "dce"])
    assert not report.records[1].changed and not report.records[3].changed


class _BreaksIR(FunctionPass):
    name = "breaks-ir"
    description = "test-only pass that deletes a terminator"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        term = fn.entry.terminator
        assert isinstance(term, ReturnInst | object)
        if term is not None:
            fn.entry.remove(term)
        return PassResult(changed=True)


def test_verifier_catches_a_broken_pass_and_names_it() -> None:
    module = build_ir("fn main() { print(1); }")
    manager = PassManager([])
    manager.passes = [_BreaksIR()]
    with pytest.raises(RuntimeError, match="IR invalid after pass 'breaks-ir'"):
        manager.run(module)
