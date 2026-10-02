"""Turn benchmark results into tables (markdown/CSV) and derived statistics.

Speedups are always relative to a named baseline configuration (by default
``fc-O0.llvm-O0``: no optimization by anyone) and are computed from *median*
native times. The coefficient of variation (CV) is reported next to every
time, so that a 3% "speedup" with 5% noise can be seen for what it is.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from typing import Any

BASELINE = "fc-O0.llvm-O0"


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def by_benchmark(summaries: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    table: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in summaries:
        table[row["benchmark"]][row["config"]] = row
    return table


def speedups(
    summaries: list[dict[str, Any]], baseline: str = BASELINE
) -> dict[str, dict[str, float]]:
    """{benchmark: {config: baseline_median / config_median}} (higher is faster)."""
    result: dict[str, dict[str, float]] = {}
    for bench, configs in by_benchmark(summaries).items():
        base = configs.get(baseline, {}).get("native_median_s")
        if not base:
            continue
        result[bench] = {
            name: base / row["native_median_s"]
            for name, row in configs.items()
            if row.get("native_median_s")
        }
    return result


def markdown_table(summaries: list[dict[str, Any]], baseline: str = BASELINE) -> str:
    speed = speedups(summaries, baseline)
    header = [
        "benchmark", "config", "native median s", "CV", f"speedup vs {baseline}",
        "interp cost (small)", "IR insts", ".text bytes", "pass ms",
    ]  # fmt: skip
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for bench, configs in by_benchmark(summaries).items():
        for name, row in configs.items():
            median = row.get("native_median_s")
            cells = [
                bench,
                name,
                f"{median:.4f}" if median else "-",
                f"{row['native_cv']:.1%}" if row.get("native_cv") is not None else "-",
                f"{speed[bench][name]:.2f}x" if bench in speed and name in speed[bench] else "-",
                f"{row['interp_cost']:.0f}",
                str(row["ir_instructions"]),
                str(row["text_bytes"]),
                f"{row['pass_ms']:.1f}",
            ]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def geomean_speedups(summaries: list[dict[str, Any]], baseline: str = BASELINE) -> dict[str, float]:
    per_config: dict[str, list[float]] = defaultdict(list)
    for configs in speedups(summaries, baseline).values():
        for name, value in configs.items():
            per_config[name].append(value)
    return {name: geomean(values) for name, values in per_config.items()}


def to_csv(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(summaries[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(summaries)
    return buffer.getvalue()
