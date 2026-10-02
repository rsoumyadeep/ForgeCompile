"""Report machine resources and recommend a safe worker count (resource policy).

Run before every expensive experiment::

    uv run python scripts/resources.py            # human-readable report
    uv run python scripts/resources.py --workers  # prints only the recommended worker count

The recommendation is deliberately conservative. It leaves headroom for other
users (the server is shared), caps at ``--max-workers`` (default 8), and
assumes ``--gb-per-worker`` of RAM per worker process (default 2 GB; the
dataset workers measured well below that).
Exit status 1 if available memory is below ``--min-free-gb`` (default 8):
launchers use this to refuse to start.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def available_ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            info = {line.split(":")[0]: line.split()[1] for line in fh}
        return int(info["MemAvailable"]) / 1024**2
    except (OSError, KeyError):  # non-Linux: fall back to "unknown, assume small"
        return 4.0


def load_average() -> float:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return 0.0


def gpu_summary() -> str:
    if shutil.which("nvidia-smi") is None:
        return "no nvidia-smi"
    query = "--query-gpu=index,memory.used,memory.total,utilization.gpu"
    out = subprocess.run(
        ["nvidia-smi", query, "--format=csv,noheader"], capture_output=True, text=True
    )
    return out.stdout.strip().replace("\n", " | ") or "unavailable"


def busy_processes(limit: int = 5) -> str:
    if shutil.which("ps") is None:
        return ""
    out = subprocess.run(
        ["ps", "-eo", "user,pcpu,pmem,comm", "--sort=-pcpu"], capture_output=True, text=True
    )
    return "\n".join(out.stdout.splitlines()[: limit + 1])


def recommend_workers(cpus: int, load: float, ram_gb: float, gb_per_worker: float, cap: int) -> int:
    idle_cpus = max(cpus - load, 0)
    by_cpu = int(idle_cpus * 0.5)  # never take more than half of the currently idle CPUs
    by_ram = int(ram_gb * 0.25 / gb_per_worker)  # never plan to use more than 25% of free RAM
    return max(1, min(cap, by_cpu, by_ram))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", action="store_true", help="print only the recommendation")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--gb-per-worker", type=float, default=2.0)
    parser.add_argument("--min-free-gb", type=float, default=8.0)
    args = parser.parse_args()
    cpus = os.cpu_count() or 1
    ram = available_ram_gb()
    load = load_average()
    workers = recommend_workers(cpus, load, ram, args.gb_per_worker, args.max_workers)
    if args.workers:
        print(workers)
    else:
        print(f"cpus={cpus} load1={load:.2f} available_ram_gb={ram:.1f}")
        print(f"gpus: {gpu_summary()}")
        print(busy_processes())
        print(f"recommended workers: {workers}")
    if ram < args.min_free_gb:
        print(f"refusing: only {ram:.1f} GB available (< {args.min_free_gb})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
