"""Helpers for pass tests written directly in IR text."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from forgecompile.ir.function import Module
from forgecompile.ir.interpreter import IRExecutionResult, run_module
from forgecompile.ir.parser import parse_module
from forgecompile.ir.printer import format_module
from forgecompile.ir.verify import verify_module
from forgecompile.optimization.pass_manager import PipelineReport, optimize


@dataclass
class Optimized:
    module: Module
    report: PipelineReport
    before: IRExecutionResult
    after: IRExecutionResult

    @property
    def text(self) -> str:
        return format_module(self.module)

    def opcodes(self, fn: str = "main") -> list[str]:
        return [inst.opcode.value for inst in self.module.functions[fn].instructions()]

    def stats(self, name: str) -> dict[str, int]:
        merged: dict[str, int] = {}
        for record in self.report.records:
            if record.name == name:
                for key, value in record.stats.items():
                    merged[key] = merged.get(key, 0) + value
        return merged


def run_passes(ir_text: str, passes: list[str]) -> Optimized:
    """Parse IR, run passes (verifying SSA after each), and run before/after for comparison."""
    module = parse_module(ir_text)
    verify_module(module, ssa=True)
    before = run_module(parse_module(ir_text))
    report = optimize(module, passes)
    after = run_module(module)
    assert after.observable == before.observable, "pass changed observable behaviour"
    return Optimized(module, report, before, after)


@pytest.fixture
def opt() -> object:
    return run_passes
