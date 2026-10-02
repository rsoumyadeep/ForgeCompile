# Decision Log

Each important architectural decision is recorded with its context, the alternatives and the
trade-offs. Entries are append-only. If a decision is reversed, a new entry supersedes the old
one and links back to it.

---

## D-001 — Implement the compiler in Python

- **Date:** 2026-10-02
- **Context:** The project combines a compiler (frontend, IR, passes) with ML/RL experiments
  (feature extraction, scikit-learn models, RL training). It has to be readable enough to
  study and defend in an interview.
- **Alternatives:** C++ (the "industrial" choice, with native LLVM C++ APIs); Rust (inkwell);
  OCaml.
- **Chosen:** Python ≥ 3.11 with type hints, checked by mypy.
- **Why:**
  - The ML/RL stack (scikit-learn, PyTorch) is native to Python, so there is no FFI boundary
    between the compiler and the learner. The RL environment calls passes directly.
  - Iteration speed: the core work is designing IR and passes, not raw compiler throughput.
  - Readability for study.
- **Trade-offs:** The compiler runs ~10–100× slower than a C++ equivalent. This limits how
  many compile/evaluate steps fit into RL training. It is mitigated by keeping benchmark
  programs small and by using an interpreter-based cost metric (D-006). Generated code speed
  is unaffected, because native code comes from LLVM.
- **Consequences:** Compile time must be measured honestly as *Python* compile time. It should
  not be compared directly against clang's compile time.

## D-002 — LLVM backend via llvmlite, linking with `zig cc`

- **Date:** 2026-10-02
- **Context:** The development machine (Windows 10, i5-8300H) has **no** system clang, gcc,
  MSVC or LLVM, and no admin-level toolchain install is assumed. Native executables are
  required (Phase 5).
- **Alternatives:**
  1. Write an x86-64 backend by hand. This is outside the project's focus (optimization and
     ML), and a large amount of work.
  2. Install LLVM/clang system-wide. Not reproducible via `pip`/`uv`, and differs per OS.
  3. Emit textual LLVM IR only and require users to bring clang.
  4. **llvmlite** (pip wheel bundling LLVM) for IR verification, LLVM's own optimization
     pipeline (as a baseline) and object emission, together with the **ziglang** pip wheel
     (bundles clang and lld) for linking.
- **Chosen:** Option 4. Verified on 2026-10-02: llvmlite 0.50.0 (LLVM 22.1.0) installs on this
  machine. `python -m ziglang cc -O2 t.ll -o t.exe` compiled a hand-written LLVM IR
  `printf` program into a native Windows executable that printed the expected `42`.
- **Why:** The whole toolchain installs through `uv sync` on Windows and Linux. The project
  still emits real LLVM IR and produces real native binaries.
- **Trade-offs:** llvmlite exposes only part of the LLVM API, so ForgeCompile builds textual
  LLVM IR and parses/verifies it with llvmlite rather than using the C++ IRBuilder. zig cc
  targets `x86_64-windows-gnu` (MinGW ABI) on Windows.
- **Consequences:** Phase 5 adds `llvmlite` and `ziglang` as dependencies. `forgecompile info`
  reports their availability.

## D-003 — uv + pyproject.toml (hatchling), src layout

- **Date:** 2026-10-02
- **Alternatives:** pip + requirements.txt; Poetry; conda.
- **Chosen:** `uv` with a standard PEP 621 `pyproject.toml`, the hatchling build backend,
  PEP 735 dependency groups, a committed `uv.lock` and a `src/` layout.
- **Why:** uv was already installed and is fast. The lock file gives reproducible dependency
  versions. The src layout ensures tests run against the installed package, not against stray
  files in the repository.
- **Trade-offs:** Contributors need uv. Plain `pip install -e .` still works because the
  metadata is standard.

## D-004 — argparse for the CLI

- **Date:** 2026-10-02
- **Alternatives:** click, typer.
- **Chosen:** standard-library `argparse` with subcommands.
- **Why:** zero dependencies. The CLI surface is small (`parse`, `check`, `ir`, `opt`,
  `build`, `run`, `bench`, ...), so argparse is enough.
- **Trade-offs:** slightly more boilerplate.

## D-005 — Develop and test locally; the remote GPU server is optional

- **Date:** 2026-10-02
- **Context:** `server_system_info.txt` describes a remote Ubuntu server (AMD EPYC 7513
  32C/64T, 503 GB RAM, 2× RTX A6000, CUDA 12.4, no sudo). The development machine is a 4-core
  laptop with 16 GB RAM and no GPU.
- **Chosen:** All code, tests and initial (small) experiments are built to run on the laptop.
  Experiments are sized so that they also run there. The server is an optional target for
  larger or quieter timing runs, used at the owner's discretion. The agent does not log into
  it itself.
- **Why:**
  - The server is on a private network.
  - Using credentials found in a file is not appropriate without explicit authorization.
  - The ML/RL models planned here (tree ensembles, small MLP/DQN) do not need a GPU.
- **Security:** `server_system_info.txt` contains plaintext credentials and is in
  `.gitignore`. It must never be committed.
- **Consequences:** Every experiment records its environment (`utils/environment.py`), so
  laptop and server results are never mixed silently.

## D-006 — (Planned) IR interpreter as reference semantics and deterministic cost metric

- **Date:** 2026-10-02 (to be confirmed or revised in Phases 3 and 6)
- **Context:** Wall-clock timing on a laptop is noisy (turbo boost, thermals, background
  processes). An RL reward built only on noisy timings would mostly learn noise, and each
  native measurement costs a compile, link and repeated execution.
- **Plan:** The IR interpreter serves two roles:
  - it is the *oracle* for correctness (differential testing of passes);
  - it reports *dynamic instruction counts* (optionally weighted per opcode). These are
    deterministic and cheap, and form the primary optimization signal for ML/RL.
- **Validation required:** Phase 6 must measure how well interpreter cost correlates with
  native runtime. If the correlation is weak, that is reported as a finding and native timing
  is used for evaluation.
- **Trade-off:** Dynamic IR instruction count ignores cache and memory effects and
  LLVM-backend effects. This is a known limitation that must be discussed alongside the
  results.

## D-007 — Add dependencies only in the phase that needs them

- **Date:** 2026-10-02
- **Chosen:** Phase 0 has zero runtime dependencies. llvmlite and ziglang arrive in Phase 5,
  numpy and scikit-learn in Phase 7, PyTorch (if used at all) in Phase 9.
- **Why:** Keeps installs light, makes each dependency's purpose obvious, and keeps the
  dependency audit (Phase 11) simple.

## D-008 — Documentation layout

- **Date:** 2026-10-02
- **Chosen:** `README.md` at the root. All other docs live in `docs/`, with per-phase reports
  in `docs/phases/PHASE_N.md`. Docs for future phases exist from Phase 0 with an explicit
  "not yet implemented" status, so the structure is stable and nothing pretends to exist
  before it does.
