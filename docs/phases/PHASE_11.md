# Phase 11 Report — Hardening and Final Audit

**PHASE:** 11 — system hardening, reproducibility and the final audit
**STATUS:** ✅ Complete (2026-10-03).

## Hardening done
- **Correctness at scale:**
  - full suite (772 tests), plus the slow differential-fuzz tests;
  - `scripts/fuzz_passes.py --programs 300 --sequences 3`: 0 failures;
  - the pass differential tests now also require optimized IR to round-trip through text
    (F-016).
- **Profiling** (DEVELOPMENT.md):
  - dataset generation is dominated by the interpreter (58%) and the text-based module clone
    (20%);
  - `Enum.__hash__` cost 11%. A C-level identity hash made generation about 10% faster with
    byte-identical datasets.
- **Resource safety on a shared server:**
  - per-process thread caps (F-017);
  - load averages recorded in run metadata;
  - "dirty" redefined so curated result files do not taint later runs (D-040).
- **CLI cleanup:**
  - `opt` and `run` accept `--schedule {oracle,dqn}`;
  - the DQN path uses the no-retry wrapper, a fix prompted by the fresh-clone check;
  - conflicting options are rejected with clear errors.
- **Dependency audit:** runtime dependencies are exactly llvmlite 0.50.0, numpy 2.4.6,
  scikit-learn 1.9.1 and ziglang 0.16.0, all imported and used. The dev group is pytest, ruff
  and mypy. There is no PyTorch (D-039), and the GPUs were never used.
- **Reproducibility checks:**
  - EXP-010's base condition reproduced EXP-006's DQN seeds bit-exactly;
  - EXP-006 reproduced EXP-005's oracle/O2/model rows exactly;
  - EXP-003's two native runs agree to a median of 0.53%;
  - EXP-007 showed datasets are identical across worker counts.

## Fresh-clone reproduction (server, `git clone` from GitHub at `d3b544f`)
`uv sync --locked`, then:
- `forgecompile --version`;
- 772 tests passed;
- `scripts/e2e_sanity.py` passed;
- `forgecompile run --schedule dqn examples/gcd.mini` printed the correct output with the
  committed checkpoint;
- an EXP-004 sanity experiment completed.

An earlier fresh clone (`87df891`) had also passed. The final source change after the clone
(`f529a6d`, CLI no-retry) is covered by the CLI tests and CI.

## Final audit checklist (from the project brief)

| Item | Status | Evidence |
|---|---|---|
| Fresh installation works | ✅ | fresh clone above; CI on Linux and Windows |
| Compiler accepts valid MiniLang programs | ✅ | `tests/frontend`, examples, 1,000 random expressions, generated programs |
| Invalid programs produce useful errors | ✅ | `tests/frontend/test_syntax_errors.py`, `tests/semantic` (one test per diagnostic, mutation-tested, F-005) |
| AST works | ✅ | parse → format → parse round trips |
| Semantic analysis works | ✅ | 116 semantic tests |
| IR works | ✅ | printer/parser round trip, verifier, two interpreters |
| CFG works | ✅ | `tests/analysis` |
| SSA works | ✅ | Cytron construction, dominance verifier, 1,000 programs agree across engines |
| Optimization passes work | ✅ | 11 passes with before/after tests |
| Optimizations preserve correctness | ✅ | differential tests, 0 fuzz failures, outputs checked in every ML/RL evaluation |
| LLVM backend works / native binaries execute | ✅ | `tests/backend`, the native correctness gate in every benchmark run |
| Benchmarks run | ✅ | EXP-002, EXP-003, EXP-008 |
| ML pipeline runs | ✅ | EXP-004, EXP-005, EXP-007, EXP-009 |
| RL environment runs | ✅ | Phase 8, about 450k training steps, 0 invalid transformations |
| RL training runs / evaluation runs | ✅ | EXP-006, EXP-010, EXP-012 |
| Baselines exist | ✅ | random, O1, O2, frequency, majority, greedy oracle, beam search |
| Ablations are complete | ✅ | EXP-009 (features, data, distribution), EXP-010 (reward, γ, action space) |
| Experiments are reproducible | ✅ | metadata with commit/environment/seed/load; bit-exact re-runs; noise band |
| Results are documented | ✅ | RESULTS.md (summary answers all ten research questions) |
| Failures are documented | ✅ | FAILURES.md F-001…F-017; aborted and failed runs preserved |
| Decisions are documented | ✅ | DECISIONS.md D-001…D-040 |
| Theory is documented | ✅ | THEORY.md §1–17 |
| Study guide exists | ✅ | HOW_TO_STUDY.md §0–18 |
| Interview questions exist | ✅ | INTERVIEW_QUESTIONS.md (62 questions) |
| HOW_TO_RUN works from a clean environment | ✅ | fresh clone above |
| No fabricated results | ✅ | every number traces to a curated run with metadata. Pre-registered hypotheses are kept, including rejected ones. Corrections stay visible (F-014, kernel counts). |
| Git history is clean | ✅ | phase-scoped commits; no credentials (`server_system_info.txt` is gitignored and was never committed); no large artefacts (checkpoints 0.2 MB each) |
| README accurately represents the project | ✅ | README "Results in brief" matches RESULTS.md |

## Known limitations (project level)
See RESULTS.md ("Why the answers are mostly negative"), ROADMAP ("Future work") and each phase
report. In short:
- the interpreter-cost proxy;
- one shared machine;
- LLVM -O0 as the measurement point;
- synthetic training workloads with coverage gaps;
- small models;
- 11 unparameterized passes with about 1% headroom.

## Commit
See `git log` (2026-10-03, `46a5643` … final).
