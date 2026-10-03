# CV Description

Written from measured results only. Every number below is in [RESULTS.md](RESULTS.md) with its
experiment ID, commit and raw data. If you change a claim here, change it there first.

## One line

**ForgeCompile** — an optimizing compiler for a typed language, written from scratch in Python
(SSA IR, 11 optimization passes, LLVM backend), used to test whether ML and RL can schedule
compiler passes better than a hand-written pipeline. Answer, measured: not in this setting, and
why.

## Bullet points (pick 3–4)

- Built a compiler from scratch for a statically typed language:
  - Pratt/recursive-descent parser with error recovery and a type checker;
  - SSA IR (Cytron construction, dominators, verifier) with two reference interpreters;
  - 11 classical passes (SCCP, GVN-style CSE, LICM, strength reduction, bounds-check
    elimination, inlining, …);
  - an LLVM backend producing native executables.
- Verified correctness differentially across 5 engines (AST interpreter, pre-SSA and SSA IR
  interpreters, optimized IR, native code), with 770+ tests and random-program fuzzing. Two
  optimizer bugs were found by experiments rather than tests, and both are documented with
  regression tests.
- Formulated pass scheduling as supervised learning and as an MDP:
  - 61 static IR features;
  - oracle labels from about 3,000 compiled-and-executed states;
  - a Double-DQN agent implemented from scratch in NumPy;
  - evaluated end to end on held-out and hand-written programs, with every output checked.
- Showed rigorously that learned schedulers do not beat the hand-written `-O2` pipeline here:
  - gradient boosting beat the majority baseline 4.4× on regret (in distribution), but lost
    to `-O2` end to end (cost ratio 0.580 vs 0.558);
  - DQN lost to both;
  - a beam search over all 12-pass schedules found only about 1% headroom above `-O2`;
  - the root causes (tiny action gaps, workload-coverage gaps) are documented.
- Ran experiments reproducibly on a shared 64-thread server:
  - pre-registered hypotheses;
  - per-run metadata (commit, environment, load);
  - correctness-gated native benchmarking;
  - documented negative results and fixed a thread-oversubscription incident caused by my own
    jobs.

## What not to claim

- Not "ML improves compiler performance". It did not here (EXP-005/006/011).
- Not native speedups beyond what EXP-002/003/008 report.
- Not "state-of-the-art RL": it is a small, from-scratch Double DQN, and that is the point.
