# ML-Guided Optimization

Code: `src/forgecompile/ml/` (`features.py`, `dataset.py`, `data_pipeline.py`, `models.py`,
`policies.py`, `evaluate.py`). Experiments: EXP-004 (pass prediction) and EXP-005 (end-to-end
scheduling). Measured numbers are only in [RESULTS.md](RESULTS.md) and
[EXPERIMENTS.md](EXPERIMENTS.md).

## 1. Why pass ordering is hard

There are 11 passes. Sequences of length 12 give 11¹² ≈ 3·10¹² possibilities per program, and
the right choice differs between programs:

- **Enabling:** `copyprop` must precede `bce` and `strength` (EXP-001).
- **Disabling and harm:** `licm` can increase work 1.87× on a program whose loops never run
  (EXP-001).
- **Redundancy:** `constfold` and `sccp` overlap. Applying the second after the first often
  achieves nothing, but costs compile time.
- **Code size vs speed:** `inline` lowers cost but grew the examples' code by 52% (EXP-001).

A fixed pipeline (O2) is a one-size-fits-all guess. The question is whether a policy that
*looks at the program* does better, and whether that is worth its overhead.

## 2. The learning problem

**Formulation.**
- Input: the current IR state, as a feature vector φ(M) of 61 static counts.
- Output: the next pass to apply, or **stop**.
- This is posed as multi-class classification over 12 labels, and used greedily: predict,
  apply, re-extract features, repeat (at most 12 steps).

**Labels from real compiler experiments** (`ml/dataset.py`). For each recorded state, *every*
pass is applied to a copy of the module and the resulting program is executed on the IR
interpreter:

    label(M) = argmin_pass C(pass(M))     if C(pass(M)) < C(M)
               stop                        otherwise

No label is synthetic or guessed. C is the interpreter's weighted cost. EXP-002 found that it
tracks native time only weakly (Spearman 0.29), so all labels are statements about this proxy. Ties (several passes reaching the same cost) are broken by name.
This is why *regret*, not accuracy, is the primary metric (§5).

**Which states are labelled.** An ε-greedy walk (ε = 0.3) from the unoptimized IR follows the
oracle-best pass 70% of the time, and a random pass 30% of the time. This covers states a good
policy visits, plus states reached after mistakes. Every state stores the complete one-step
outcome table, so regret can be computed for any predicted pass.

## 3. Features (`ml/features.py`)

| Group | Count | Examples | Why |
|-------|-------|----------|-----|
| size | 4 | blocks, instructions, phis | scale |
| opcodes | 32 | fraction of each opcode | workload mix (memory vs float vs branch) |
| cfg | 5 | edges, conditional branches, critical edges, cyclomatic complexity, dominator-tree depth | control structure |
| loops | 4 | number of loops, nesting depth, fraction of instructions in loops, induction variables | where loop passes can pay off |
| memory | 5 | loads, stores, allocas, bounds checks, fraction of checks on IVs | memory passes, bce |
| calls | 3 | calls, inlinable call sites, recursive functions | inlining |
| opportunities | 8 | copies, trivial phis, constant-operand instructions, unused removable instructions, duplicate expressions, loop-invariant instructions, IV·constant multiplies, constant branches | cheap detectors of each pass's precondition |

The "opportunities" group is hand-engineered: each feature is essentially a cheap test for
whether a specific pass has work to do. Including it is a design decision, and it raises an
interview-worthy question: *is the model learning anything beyond these detectors?* The
feature-group ablation (Phase 10) answers that by retraining without each group.

## 4. Dataset generation and leakage prevention (`ml/data_pipeline.py`)

| Split | Programs | Use |
|-------|----------|-----|
| train | generated, seeds 100000–100399 (`LOOP_HEAVY` profile) | fit models |
| val | seeds 100400–100499 | model selection only |
| test | seeds 100500–100599 | reported once, for the selected model |
| ood | the 10 benchmark kernels (small instances) + 7 examples | generalization to hand-written code; never used for training or selection |

- **Split by program, not by state.** States from one program are strongly correlated.
  Splitting by state would put near-duplicate states in both train and test, and inflate
  accuracy.
- **Disjoint seed ranges** from the generator seeds used by the correctness tests.
- **The OOD split is a different distribution** (hand-written kernels). It is the honest
  generalization test.
- **Determinism:** each program has its own trajectory RNG seed, so the dataset does not depend
  on the number of worker processes.
- **Caching:** datasets are cached under `experiments/data/` (git-ignored) keyed by config +
  git commit, so labels from an older compiler are never reused.

**Generator profile.** EXP-001 showed the default generator to be constant-heavy with few
loops. The `LOOP_HEAVY` profile (deeper loop nests, fewer straight-line constants) is used for
training data. The defaults remain byte-identical, so earlier experiments stay reproducible.
The training profile emits **no deliberate traps** (D-036): at the testing rate, about 10% of
programs trapped, which truncates their cost. The dataset validator (EXP-007) found this.

## 5. Models and metrics (`ml/models.py`)

Candidates: majority class (floor), decision tree, random forest, histogram gradient boosting,
and a small MLP (2 × 64) on log-scaled, standardized features. **Selection is by validation
mean regret**, and the selected model is refit on train + val, then scored once on test and
once on OOD.

| Metric | Definition | Why |
|--------|------------|-----|
| **mean regret** | best one-step gain − gain of the predicted pass (stop = 0) | Equal-gain passes are interchangeable. Regret charges only for real losses. |
| near-optimal rate | regret ≤ 10% of the best gain | "good enough" decisions |
| accuracy / top-2 | exact label match | reported, but misleading under ties |

## 6. Baselines and end-to-end evaluation (`ml/policies.py`, `ml/evaluate.py`)

| Policy | Description |
|--------|-------------|
| O1, O2 | fixed presets |
| random-k12 (3 seeds) | 12 uniformly random passes |
| frequency | static order: passes by how often each was the best label in train |
| model | the classifier, applied greedily, never retrying a pass in an unchanged state |
| oracle-greedy | applies every pass at every step and takes the best: an upper bound for any greedy policy |

Metrics: the geometric mean of final cost / unoptimized cost, passes used, and decision time
per program. Every final program's output is checked against the unoptimized program, and any
mismatch aborts the evaluation (`WrongCodeError`).

## 7. Results

See EXPERIMENTS.md (EXP-004, EXP-005) and RESULTS.md. Limitations and interpretation are
written there, against measured numbers.
