# How to Run

## 1. Install

Prerequisites: Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
No system compiler or LLVM installation is required (DECISIONS D-002).

```bash
git clone <repo-url> ForgeCompile
cd ForgeCompile
uv sync
```

Without uv: `python -m venv .venv`, activate it, then `pip install -e . pytest ruff mypy`.

## 2. Verify

```bash
uv run forgecompile --version
uv run forgecompile info        # shows Python/OS and backend tool availability
uv run pytest
```

## 3. Compile programs

This section grows with each phase. Currently the frontend is available:

```bash
uv run forgecompile lex examples/gcd.mini              # token stream with line:column
uv run forgecompile parse examples/gcd.mini            # AST tree
uv run forgecompile parse --format examples/gcd.mini   # canonical source (round-trippable)
uv run forgecompile check examples/gcd.mini            # parse + type-check
uv run forgecompile check --dump examples/gcd.mini     # AST annotated with types
uv run forgecompile ir --no-ssa examples/gcd.mini      # IR straight from lowering
uv run forgecompile ir examples/gcd.mini               # SSA IR
uv run forgecompile run examples/gcd.mini              # execute (SSA IR interpreter)
uv run forgecompile run --engine ast examples/gcd.mini # execute (reference AST interpreter)
uv run forgecompile run --stats examples/gcd.mini      # + dynamic instruction counts (stderr)
uv run forgecompile passes                             # list optimization passes and presets
uv run forgecompile opt -O 2 --stats examples/gcd.mini # optimized IR + per-pass report
uv run forgecompile opt --passes copyprop,bce examples/matmul.mini
uv run forgecompile run -O 2 examples/matmul.mini      # execute optimized IR
uv run forgecompile llvm -O 2 examples/gcd.mini        # LLVM IR (add --llvm-opt 2 to see LLVM's -O2)
uv run forgecompile build -O 2 -o gcd.exe examples/gcd.mini   # native executable
uv run forgecompile run --engine native -O 2 examples/gcd.mini
```

Native builds need no system compiler: the `ziglang` package provides `zig cc`. **The first
native build on a machine takes about a minute**, because zig compiles its libc into a
cache. After that each build takes about 0.3 s. Native tests are marked `native`
(`uv run pytest -m "not native"` skips them).

`run` exits with the program's own exit status: main's return value mod 256, or 101 after a
runtime error such as division by zero or an out-of-bounds index.

The extended differential fuzz test (940 generated programs) is marked `slow`:
`uv run pytest -m slow`.

Syntax and type errors are printed to stderr with source excerpts, and the exit code is 1.

## 4. Reproduce experiments

Each experiment is a single command. Its run directory (`experiments/runs/<ID>_<time>/`,
git-ignored) records the config, seed, environment (including load averages), git commit and
status. A curated copy of the results is committed in `experiments/<ID>/`. Every script accepts
`--sanity` for a tiny run under a separate `-sanity` id, which never overwrites curated results.
Run a sanity run first.

**Before anything expensive:** `uv run python scripts/e2e_sanity.py` (about 30 s) exercises
the whole pipeline once, from program to native execution to RL reward.

The server times below come from the recorded runs (AMD EPYC 7513, shared machine).

| Experiment | Command | Approx. time |
|---|---|---|
| EXP-001 per-pass effects | `uv run python experiments/EXP-001-pass-effects/run.py --generated 200 --seed 0 --repeats 3` | ~8 min (laptop) |
| EXP-002 cost model vs native | `uv run python experiments/EXP-002-cost-model/run.py --repeats 5 --seed 0` | see EXPERIMENTS.md |
| EXP-003 ForgeCompile vs LLVM, reproducibility | `uv run python experiments/EXP-003-fc-vs-llvm/run.py --repeats 7 --seeds 0 1` | see EXPERIMENTS.md |
| EXP-007 dataset validation | `uv run python scripts/validate_dataset.py --n-train 80 --n-val 20 --n-test 20 --workers 8 --replay 24` | 15 min (server) |
| EXP-004 next-pass prediction | `uv run python experiments/EXP-004-pass-prediction/run.py --workers 16` | 5 min (server; builds the cached dataset) |
| EXP-005 ML-guided scheduling | `uv run python experiments/EXP-005-ml-scheduling/run.py --workers 16` | ~45 min (server; the oracle dominates) |
| EXP-006 DQN | `uv run python experiments/EXP-006-rl-scheduling/run.py --episodes 3000 --seeds 0 1 2 --seed-workers 3 --workers 16` | see EXPERIMENTS.md |
| EXP-008 native policies | `uv run python experiments/EXP-008-native-policies/run.py --repeats 10 --workers 16` | see EXPERIMENTS.md |
| EXP-009 ML ablations | `uv run python experiments/EXP-009-ml-ablations/run.py --workers 16` | see EXPERIMENTS.md |
| EXP-010 RL ablations | `uv run python experiments/EXP-010-rl-ablations/run.py --episodes 2000 --seeds 0 1 --workers 16` | see EXPERIMENTS.md |
| EXP-011 headroom (beam search) | `uv run python experiments/EXP-011-headroom/run.py --widths 1 4 16 --workers 16` | see EXPERIMENTS.md |

**Order matters for two of them:**
- EXP-008 loads the DQN checkpoints that EXP-006 writes to
  `experiments/EXP-006-rl-scheduling/checkpoints/` (committed, about 0.2 MB each).
- The ML experiments share a dataset cache in `experiments/data/` (git-ignored). It is keyed by
  the configuration and the git tree hash of `src/forgecompile` (D-037), so a compiler change
  rebuilds it automatically. If you edit `benchmarks/*.mini` or `examples/*.mini` (the OOD
  programs), delete `experiments/data/` by hand.

**On a shared server** use `scripts/server/launch.sh <name> <command...>`. It runs the job in
tmux and refuses to start on a dirty tree or low memory. Check `scripts/resources.py` first,
and run native-timing experiments (EXP-002/003/008) alone (D-038).

Optimization-correctness fuzzing (not an experiment, a test at scale):
`uv run python scripts/fuzz_passes.py --programs 300 --sequences 3` (~2 min).
