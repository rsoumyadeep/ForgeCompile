"""Benchmark discovery and size instantiation.

A benchmark is a MiniLang file in ``benchmarks/`` with exactly one *size
annotation* on the line that sets its repetition count::

    let reps = 10; // @size small=1 large=400

The integer literal on that line is replaced by the requested size:

* ``small``: interpreter measurements (the Python IR interpreter executes on
  the order of 10^6 instructions per second);
* ``large``: native timing, which must run long enough that process startup
  (about 50-90 ms on the development laptop) is a small fraction of the total.

Only the repetition count changes, never array sizes, so the work per
repetition and the optimization opportunities are the same at both sizes.
The workload class is the file-name prefix (``arith_``, ``branch_``, ...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SIZE_LINE = re.compile(
    r"^(?P<head>\s*let\s+\w+\s*=\s*)(?P<value>\d+)(?P<mid>\s*;\s*//\s*@size\s+)"
    r"small=(?P<small>\d+)\s+large=(?P<large>\d+)\s*$",
    re.MULTILINE,
)

DEFAULT_SUITE_DIR = Path(__file__).resolve().parents[3] / "benchmarks"


class BenchmarkError(Exception):
    pass


@dataclass(frozen=True)
class Benchmark:
    name: str
    path: Path
    source: str
    small: int
    large: int

    @property
    def workload_class(self) -> str:
        return self.name.split("_", 1)[0]

    def instantiate(self, size: str | int) -> str:
        """Source with the repetition count set to ``small``, ``large`` or an explicit integer."""
        value = (
            {"small": self.small, "large": self.large}.get(size, size)
            if isinstance(size, str)
            else size
        )
        if not isinstance(value, int):
            raise BenchmarkError(f"unknown size {size!r}; use 'small', 'large' or an integer")
        return _SIZE_LINE.sub(
            lambda m: f"{m['head']}{value}{m['mid']}small={m['small']} large={m['large']}",
            self.source,
        )


def load_benchmark(path: Path) -> Benchmark:
    source = path.read_text("utf-8")
    matches = list(_SIZE_LINE.finditer(source))
    if len(matches) != 1:
        raise BenchmarkError(f"{path.name}: expected exactly one '// @size small=N large=M' line")
    match = matches[0]
    return Benchmark(path.stem, path, source, int(match["small"]), int(match["large"]))


def load_suite(
    directory: Path = DEFAULT_SUITE_DIR, names: list[str] | None = None
) -> list[Benchmark]:
    benchmarks = [load_benchmark(p) for p in sorted(directory.glob("*.mini"))]
    if names:
        known = {b.name for b in benchmarks}
        missing = [n for n in names if n not in known]
        if missing:
            raise BenchmarkError(f"unknown benchmarks: {', '.join(missing)}")
        benchmarks = [b for b in benchmarks if b.name in names]
    if not benchmarks:
        raise BenchmarkError(f"no benchmarks found in {directory}")
    return benchmarks
