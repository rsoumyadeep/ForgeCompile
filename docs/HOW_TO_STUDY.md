# How to Study ForgeCompile

A study guide for understanding and defending the project. Topics are filled in as the
corresponding phase is built. For each topic the guide gives: what you need to know, where it
lives in the code, key equations, an example, likely interview questions and common
misconceptions.

| # | Topic | Phase | Status |
|---|-------|-------|--------|
| 0 | Project infrastructure and reproducibility | 0 | ✅ below |
| 1 | Compiler overview | 0 | ✅ see [THEORY §1](THEORY.md#1-what-a-compiler-is-and-why-it-is-split-into-phases) |
| 2 | Lexing | 1 | ✅ below |
| 3 | Parsing | 1 | ✅ below |
| 4 | AST | 1 | ✅ below |
| 5 | Semantic analysis | 2 | ✅ below |
| 6 | IR | 3 | ✅ below |
| 7 | CFG | 3 | ✅ below |
| 8 | SSA | 3 | ✅ below |
| 9 | Data-flow analysis | 4 | ✅ below |
| 10 | Classical optimizations | 4 | ✅ below |
| 11 | LLVM | 5 | ✅ below |
| 12 | Benchmarking | 6 | ✅ below |
| 13 | ML for compiler optimization | 7 | ✅ below |
| 14 | RL formulation | 8 | ✅ below |
| 15 | RL implementation | 9 | ✅ below |
| 16 | Experimental methodology | 10 | ✅ below |
| 17 | Failure analysis | all | ✅ below + [FAILURES.md](FAILURES.md) |
| 18 | Interview questions | 11 | ⏳ |

Suggested order: read [ARCHITECTURE.md](ARCHITECTURE.md), then this guide topic by topic, with
the code open alongside. After each topic, run its tests and change something on purpose to
see which tests fail.

---

## 0. Project infrastructure and reproducibility

**What you need to know**
- Why a `src/` layout: tests import the *installed* package, which catches packaging mistakes
  that a flat layout hides.
- Why a lock file (`uv.lock`): `pyproject.toml` states *ranges*, while the lock pins the
  *exact* versions, so a fresh clone gets the same dependency set.
- Why every experiment stores environment metadata: a timing is meaningless without the
  machine, OS, Python version and git commit that produced it.
- Why seeds are recorded: RL and ML results vary with the seed. Results are reported across
  several seeds, never from one lucky run.

**Where in the code**
- `src/forgecompile/utils/environment.py`: `collect_environment()`, `detect_tools()`.
- `src/forgecompile/utils/experiment.py`: `ExperimentRun.create()` / `finalize()`.
- `src/forgecompile/utils/logging.py`: JSON-lines logging.
- `src/forgecompile/cli/main.py`: CLI entry point (`forgecompile info`).

**Likely interview questions**
- *How would someone else reproduce your results?* Clone, run `uv sync`, then run the script
  in `HOW_TO_RUN.md`. Each result links to a run directory with its config, seed, environment
  and commit.
- *Why not just print results to the console?* Console output is lost and unstructured. JSON
  lines can be parsed later, for example to rebuild reward curves.
- *What does the `dirty` flag in metadata mean?* The run used uncommitted code, so its commit
  hash does not fully describe the code. Final results must come from clean runs.

**Common misconceptions**
- "Setting a seed makes everything deterministic." It only covers RNGs that you seed. Wall-clock
  timings, thread scheduling and some GPU kernels stay nondeterministic, which is one reason
  for the interpreter-based cost metric (DECISIONS D-006).

---

## 2. Lexing

**What you need to know.** What a token is. Why lexing is separate from parsing: tokens form
a regular language, while program structure is context-free. Maximal munch. How lexical
errors are reported and recovered from. See [THEORY §2](THEORY.md#2-lexing).

**Where in the code.** `frontend/lexer.py` (`Lexer._number`, `_symbol`, `_skip_trivia`),
`frontend/tokens.py` (`KEYWORDS`, `SYMBOLS` sorted longest-first).

**Example.** `forgecompile lex examples/gcd.mini`. `a<=b` becomes `IDENT LE IDENT`. `0..10`
becomes `INT DOTDOT INT`.

**Likely interview questions**
- *Why not lex with one big regex?* That works for simple languages. A hand-written scanner
  gives precise spans, custom errors ("did you mean '&&'?"), and fine control of cases like
  `0..10`.
- *How are keywords distinguished from identifiers?* Scan an identifier-shaped word, then
  look it up in `KEYWORDS`. This is simpler than a separate rule per keyword, and it
  naturally handles `iffy` (an identifier, not `if`).
- *What is the complexity?* O(n). Each character is examined a constant number of times.

**Common misconceptions.** "The lexer knows about nesting." It does not: brackets are just
tokens, and matching them is the parser's job.

## 3. Parsing

**What you need to know.**
- Context-free grammars and EBNF (LANGUAGE.md §2).
- Recursive descent: one function per rule, chosen by lookahead.
- Pratt parsing: binding powers. Recursing with `prec + 1` gives left-associativity.
- How MiniLang rejects chained comparisons.
- Panic-mode recovery and why it must track braces.

See [THEORY §3](THEORY.md#3-grammars-and-parsing).

**Where in the code.** `frontend/parser.py`: `Parser._expression` (Pratt loop), `_unary`,
`_postfix`, `_primary`, `_synchronize`; `ast/operators.py` (precedence table).

**Key rule.** For a binary operator with precedence p, parse the right operand with
`min_prec = p + 1` (left-associative) or `p` (right-associative).

**Example.** Trace `1 + 2 * 3 - 4` by hand through `_expression`, then compare with
`sexpr`: `(- (+ 1 (* 2 3)) 4)`.

**Likely interview questions**
- *What is left recursion and why is it a problem for recursive descent?* A rule like
  `E → E + T` makes `parse_E` call itself first without consuming input, so it recurses
  forever. Pratt parsing replaces it with a loop.
- *Is your grammar LL(1)?* Statements: yes, each one is chosen by its first token.
  Assignment vs expression statements are disambiguated by parsing an expression first and
  then checking for `=`. This also lets the parser report "invalid assignment target" for
  `1 + 2 = x`.
- *How does the parser report several errors in one run?* Panic-mode recovery (see the F-002
  story in FAILURES.md).
- *Why hand-write instead of using ANTLR?* See DECISIONS D-009.

**Common misconceptions.** "Precedence and associativity are the same thing." Precedence
decides between *different* operators (`*` vs `+`). Associativity decides between *equal*
ones (`a - b - c`).

## 4. AST

**What you need to know.** Concrete vs abstract syntax. Desugaring (`else if`). Spans on
nodes. Why node equality ignores spans. The round-trip property. See
[THEORY §4](THEORY.md#4-the-abstract-syntax-tree).

**Where in the code.** `ast/nodes.py`, `ast/dump.py`, `ast/formatter.py`;
`tests/frontend/test_roundtrip.py`.

**Likely interview questions**
- *How do you test a parser beyond examples?* Round-trip property tests over randomly
  generated trees. They found F-003.
- *Where do type annotations go?* In the `ty` field on `Expr` nodes, filled in by Phase 2.
  It is excluded from equality.

**Common misconceptions.** "An AST must keep parentheses to remember grouping." It does not:
the grouping is the tree shape.

## 5. Semantic analysis

**What you need to know.**
- Why some rules cannot be in the grammar (context-sensitivity).
- Symbols and scopes, and lookup that walks outward (shadowing).
- Why names are resolved to symbol *objects*.
- Type rules as inference rules.
- Two-pass checking for forward references.
- The error type for cascade suppression.
- Conservative return-path analysis, and why it must be conservative.

See [THEORY §5](THEORY.md#5-semantic-analysis-symbol-tables-scopes-and-types).

**Where in the code.** `semantic/checker.py` (`TypeChecker.check_program`,
`_collect_signatures`, `_check_let`, `_infer_binary`, `_infer_call`), `semantic/symbols.py`,
`semantic/control_flow.py`, `driver.py` (`check_source`).

**Key rule (typing judgement).** `Γ ⊢ e : T` means "in environment Γ, expression e has type
T". Each `_infer_*` method implements the rules for one expression form.

**Example.** `forgecompile check --dump examples/matmul.mini`. Note the `: float` and `: int`
annotations, and that `(i == j) as float` is `bool → float`.

**Likely interview questions**
- *How do you handle shadowing?* A chain of scope dicts. Each declaration gets a unique
  `VariableSymbol`. Uses are resolved to the symbol object, not the name.
- *How do you support calling a function before its definition?* Two passes: signatures
  first, then bodies.
- *Why does `let x = x + 1;` work?* The new symbol is declared *after* its initializer is
  checked, so the initializer's `x` is the outer one.
- *How do you avoid 20 errors from one typo?* The `<error>` type, which every rule accepts.
- *Is your missing-return check exact?* No. It is conservative, because exactness is
  undecidable. It recognises `while true` as infinite but not `while 1 < 2`.
- *Why no implicit int→float conversion?* It keeps the type rules trivial, and makes every
  conversion an explicit instruction in the IR, which matters for optimization and cost
  modelling (DECISIONS D-010, LANGUAGE.md §4).

**Common misconceptions.**
- "Type checking needs a separate pass per rule." One recursive walk computes types and
  enforces every rule.
- "Symbol tables are global dictionaries." Variables are scoped. Only functions are global
  here.

## 6. IR

**What you need to know.**
- Why compilers have an IR (N+M rather than N×M translators; optimization-friendly shape).
- Three-address code.
- Register-based IR, where SSA is a renaming, vs LLVM's "instruction is the value" model
  (DECISIONS D-016).
- The memory model: flat buffers, explicit `boundscheck`.
- Effect classes: why `sdiv` is not pure.
- What the verifier checks.
- The two oracles: AST interpreter vs IR interpreter.

See [IR.md](IR.md) and [THEORY §6](THEORY.md#6-intermediate-representations).

**Where in the code.** `ir/instructions.py` (`Opcode` effect properties), `ir/function.py`,
`lowering.py` (`FunctionLowering.address`, `short_circuit`, `for_stmt`), `ir/verify.py`,
`ir/interpreter.py`.

**Example.** `forgecompile ir --no-ssa examples/matmul.mini`. Find the flattened
`i*3 + k` offset computations and the per-dimension bounds checks.

**Likely interview questions**
- *Why not optimize the AST directly?* Control flow is implicit, intermediate values are
  unnamed, and names are ambiguous because of shadowing.
- *Why is integer division not "pure" in your IR?* It can trap, and trapping is observable.
  Removing an unused `x / 0` would change program behaviour.
- *How do you know lowering is correct?* Differential testing against an independent AST
  interpreter, on examples with hand-verified outputs and on 1,000 generated programs.
- *Why are arrays flattened?* It gives one load per access with computed offsets, which maps
  directly onto LLVM `getelementptr`.

**Common misconceptions.** "Three-address code means at most three registers." It means each
instruction has at most two operands and one result. Calls and phis are the usual exceptions.

## 7. CFG

**What you need to know.** Basic blocks; CFG edges from terminators; back edges and loops;
reverse postorder and why analyses use it; critical edges; unreachable-block removal.
See [THEORY §7](THEORY.md#7-control-flow-graphs-and-basic-blocks).

**Where in the code.** `analysis/cfg.py`.

**Likely interview questions**
- *Why are predecessors computed instead of stored?* So that no transformation can leave them
  stale. The O(n) recomputation is cheap at this scale.
- *What is a critical edge, and why does it matter?* An edge from a multi-successor block to a
  multi-predecessor block. Code cannot be placed "on" it without inserting a block.

## 8. SSA

**What you need to know.**
- The definition of SSA, and phi semantics as parallel copies on edges.
- Dominance, the dominator tree and dominance frontiers.
- Why phis belong at the *iterated* DF.
- Renaming via the dominator tree.
- Minimal, semi-pruned and pruned SSA.
- Where `undef` comes from.
- Why there is no out-of-SSA pass here.

See [THEORY §8](THEORY.md#8-dominance-and-ssa) and [IR.md §9](IR.md#9-ssa-form).

**Where in the code.** `analysis/dominators.py` (`_compute_idoms`, `frontiers`),
`ir/ssa.py` (`construct_ssa`), `ir/verify.py` (`_check_ssa`).

**Key equations.**
- `idom(b) = ⋂ over processed preds` (CHK).
- `DF(a) = { b | ∃ p ∈ preds(b): a dom p  ∧  ¬(a sdom b) }`.
- Phi sites for x = `DF⁺(defsites(x))`.

**Example.** Compare `forgecompile ir --no-ssa` with `forgecompile ir` on
`examples/gcd.mini`. Note `%b.1 = phi [%b, entry], [%b.2, while.body]`.

**Likely interview questions**
- *Why are phis needed?* At a join, the value depends on which edge was taken, and SSA
  forbids assigning the same register on both paths.
- *What does a phi compile to?* Copies on the incoming edges. Here, LLVM handles that:
  register allocation removes most of them.
- *Why place phis at dominance frontiers?* That is exactly where a definition stops
  dominating and can meet another one.
- *What is the dominance property, and how do you check it?* Every definition dominates every
  use. The verifier checks it after each transformation.
- *Did your SSA construction ever produce `undef`?* Yes. A variable defined inside a loop gets
  a dead header phi with an `undef` input from the entry edge. DCE removes it, and the
  interpreter proves the value is never observed (`test_ssa.py`).
- *Why no out-of-SSA?* No consumer needs it, because LLVM takes SSA directly (D-017).

**Common misconceptions.**
- "Phis execute in order." They execute simultaneously on the edge;
  `test_phis_are_parallel_copies` shows the swap case.
- "Every variable needs a phi at every join." Only variables with several definitions that
  are live across blocks. A single-assignment `let` never needs one.

## 9. Data-flow analysis

**What you need to know.** Lattices, meet, transfer functions, monotonicity, finite height, and
why fixed-point iteration terminates. Optimistic vs pessimistic initialization. SCCP's
lattice and its two worklists. Why SSA makes analyses *sparse*. See
[THEORY §9](THEORY.md#9-data-flow-analysis-lattices-and-fixed-points).

**Where in the code.** `optimization/passes/sccp.py` (`_meet`, `_SCCPSolver.solve`,
`evaluate`), and `passes/dce.py` (mark phase as a backward liveness).

**Key equation.** `OUT[b] = f_b(⊓ over preds of OUT[p])`, iterated to a fixed point.

**Example.** The `sccp` example in OPTIMIZATIONS.md: `x` is proven constant only by
assuming the `if` body is dead, which in turn is proven using `x`.

**Likely interview questions**
- *Why does SCCP terminate?* Lattice height 3, so each register lowers at most twice, and
  each edge becomes executable at most once.
- *Why is SCCP stronger than constant folding plus DCE run to a fixed point?* Pessimistic
  iteration never assumes a branch is dead. Optimistic iteration assumes code is dead until
  shown otherwise, which catches mutually dependent facts.
- *What went wrong in your SCCP the first time?* Deletion safety was judged before
  substitution, so dead divisions survived. An experiment exposed it (F-010).

**Common misconceptions.** "A more powerful analysis always gives better code." Run 1 of
EXP-001 showed SCCP losing to constfold, because the *rewrite* phase was incomplete. The
analysis alone is not the optimization.

## 10. Classical optimizations

**What you need to know.** For each of the 11 passes:
- what it does, and the one-line correctness argument;
- what it must *not* do: trap deletion, IEEE identities, speculating loads;
- the pass-manager design: one interface, verification after each pass, statistics;
- the measured effects and phase-ordering dependencies (EXP-001).

See [OPTIMIZATIONS.md](OPTIMIZATIONS.md) and [THEORY §10](THEORY.md#10-why-each-optimization-is-valid).

**Where in the code.** `optimization/pass_manager.py`, `optimization/utils.py`,
`optimization/passes/*.py`, `analysis/loops.py`. Tests: `tests/optimization/`.

**Example.** `forgecompile opt --stats -O 2 examples/matmul.mini`. Read the per-pass report,
then compare `forgecompile run --stats` with and without `-O 2`.

**Likely interview questions**
- *Why can't you just apply every optimization?* Passes interact: some enable others
  (copyprop → bce), some are harmful in context (LICM on zero-trip loops: 1.87× worse), and
  inlining trades code size for speed.
- *How do you know your optimizations are correct?*
  - The verifier runs after every pass.
  - IR-level unit tests include negative cases.
  - Differential testing covers single passes, presets and random orderings (thousands of
    programs).
  - The guards were mutation-tested.
- *Why is DCE not allowed to remove an unused division?* It could trap, and traps are
  observable in MiniLang.
- *Why isn't `x + 0.0 → x` valid?* `-0.0 + 0.0 = +0.0`.
- *What does LICM require of an instruction?* Speculatability: no side effects, no trap, no
  memory read. Plus a preheader to put it in.
- *Your strength reduction: is it worth it?* It saves about 0.5% of interpreter cost on the
  examples. Natively it is probably close to nothing, because `imul` is cheap and LLVM does
  its own loop strength reduction. That honest answer is what EXP-001 supports.

**Common misconceptions.**
- "Optimizations always make code faster." EXP-001 has counterexamples.
- "SSA makes every substitution valid." The replacement must also dominate the uses (F-009).

## 11. LLVM

**What you need to know.**
- The ForgeCompile → LLVM translation table (LLVM_BACKEND.md §2).
- Why no `nsw`, why `fptosi.sat`, why checked division, and why `fcmp une` for `!=`.
- The exact split between ForgeCompile's work and LLVM's (LLVM_BACKEND.md §1).
- Why experiments use LLVM `-O0`.
- How the C runtime defines observable behaviour (formatting, traps, Windows binary stdout).

See [THEORY §11](THEORY.md#11-llvm-ir).

**Where in the code.** `backend/llvm_emitter.py` (`_FunctionEmitter.instruction`,
`PRELUDE`, `_c_main`), `backend/native.py`, `backend/runtime/fc_runtime.c`.

**Example.** `forgecompile llvm -O 2 examples/gcd.mini` vs `forgecompile llvm -O 2 --llvm-opt 2
examples/gcd.mini`. Spot the checked `__fc_srem` call becoming a `switch` after LLVM inlines
it.

**Likely interview questions**
- *What does LLVM do in your pipeline?* At the default setting: parse, verify, select
  instructions, allocate registers, emit machine code. No IR optimization unless asked for.
  All studied optimizations happen before LLVM.
- *How do you make sure LLVM doesn't "optimize away" MiniLang semantics?* Never emit
  constructs with reachable UB/poison: no `nsw`, saturating casts, checked division. The
  corner-case test runs at `-O3`.
- *How did you verify the backend?* llvmlite verification, plus native vs interpreter
  differential tests: examples, a corner-case program, runtime errors, and generated programs
  with random pass sequences and LLVM levels.
- *Why is `nan != nan` true, and how is that encoded?* IEEE says unordered compares are
  not-equal, so the encoding is `fcmp une`.
- *Why a C runtime instead of LLVM IR for printing?* It is clearer, and its formatting was
  checked against Python on 4,022 values. Performance-relevant checks (division, bounds) stay
  in LLVM IR so LLVM can inline and optimize them.

**Common misconceptions.**
- "`-O0` means LLVM does nothing." It still selects instructions and allocates registers.
  It does not run IR optimization passes.
- "Native timing of small programs measures code quality." It mostly measures process
  startup: about 5 ms warm, but 50–90 ms on the first run of a new executable (F-014).

## 12. Benchmarking

**What you need to know.**
- Why timings are noisy, and the protocol that tames them: correctness gate, warm-up,
  interleaving, median/min/CV, two-run noise band.
- Why the geometric mean is used for speedups.
- Deterministic proxies (interpreter cost) vs ground truth (native time).
- The two-size design.
- What `.text` bytes measure.

See [THEORY §12](THEORY.md#12-measuring-performance) and
[benchmarks/README.md](../benchmarks/README.md).

**Where in the code.** `benchmarking/runner.py` (`run_suite`, `_time_large_instance`,
`_check_small_instance`), `benchmarking/measure.py`, `benchmarking/report.py`,
`benchmarking/stats.py`.

**Key equations.**
- Speedup = median(baseline) / median(config).
- Aggregate = geometric mean (∏ sᵢ)^(1/n).
- CV = σ/μ.
- Spearman ρ = Pearson correlation of ranks.

**Likely interview questions**
- *How do you make benchmark results trustworthy?* Check correctness first, warm up,
  interleave configurations, use robust statistics, report noise, and repeat whole runs to get
  a noise band. Never claim effects inside that band.
- *Why the geometric mean?* Speedups are ratios. An arithmetic mean of ratios is biased, and the
  result depends on which configuration is chosen as the baseline.
- *Is your interpreter cost model valid?* That is exactly what EXP-002 measures. Quote the
  measured correlation, not an assumption.
- *Why time at LLVM -O0?* To isolate ForgeCompile's effects (D-028). LLVM -O2 numbers are
  reported separately as a baseline.
- *What surprised you?* The first-run penalty of new executables (F-014), and LLVM -O2 turning
  `loop_nest` into a closed-form formula.

**Common misconceptions.**
- "More repetitions remove all noise." They reduce random noise but not systematic bias. That
  is what interleaving is for.
- "The minimum is always the right statistic." It estimates intrinsic cost but hides real
  variability, which is why both the minimum and the median are reported.

## 13. ML for compiler optimization

**What you need to know.**
- The phase-ordering problem and its four interactions: enabling, disabling, redundancy, harm.
- How a pass-selection classifier is set up: state → features → next pass or stop.
- How labels are produced by running the compiler (an offline oracle), and why that makes the
  model imitate the *greedy* oracle.
- Why regret, not accuracy, is the primary metric.
- How leakage is prevented: split by program, disjoint seeds, OOD set.

See [THEORY §13–14](THEORY.md#13-why-pass-ordering-is-hard-the-phase-ordering-problem) and
[ML_GUIDED_OPTIMIZATION.md](ML_GUIDED_OPTIMIZATION.md).

**Where in the code.**
- `ml/features.py`: `FEATURE_GROUPS`, 61 features; `extract_features`.
- `ml/dataset.py`: `trajectory`, `StateRecord.label`, `CostEvaluator`.
- `ml/data_pipeline.py`: `program_splits`, `build_dataset`, cache key (D-037).
- `ml/models.py`: `make_models`, `score`, `select_model`.
- `ml/policies.py`: `ModelPolicy` (never retries a pass in an unchanged state), `OraclePolicy`.
- `scripts/validate_dataset.py`: the checks run before any training (EXP-007).

**Key equations.**
- label(s) = argmin_a C(a(s)) if it improves C(s), else stop.
- gain(a, s) = (C(s) − C(a(s))) / C(s).
- regret(s) = max(0, max_a gain(a, s)) − gain(â, s).
- End-to-end metric: geomean over programs of C(final)/C(initial).

**Example.** On the `LOOPY` test program (`tests/ml/test_ml.py`), the oracle's first label is a
folding pass. After `copyprop` the opportunity detector `n_copies` drops to 0, and `bce`
becomes the best next pass. The features reflect the state change that the model must learn.

**Likely interview questions**
- *Where do your labels come from?* From compiling and executing every one-step alternative.
  Nothing is hand-labelled or synthetic, and EXP-007 replays the labels from scratch to prove
  they are reproducible.
- *How do you know you are not leaking?* The split is by program with disjoint generator seeds.
  Names and source text are checked to be disjoint, and a separate hand-written OOD set exists.
- *Why not accuracy?* Ties: `constfold` and `sccp` often give identical gains, so accuracy
  punishes harmless choices. Regret measures what a decision actually costs.
- *Is the model just reading your hand-made opportunity features?* Answer with the EXP-009
  feature ablation numbers.
- *Does better prediction mean faster code?* Not necessarily. That is why EXP-005 evaluates
  end to end and EXP-008 measures native time.

**Common misconceptions.**
- "ML replaces the optimizer." The passes and their correctness arguments are unchanged. The
  model only chooses *which* pass to run *when*.
- "A learned policy can produce wrong code." It can only choose among semantics-preserving
  passes. Wrong code would be a pass bug, and the evaluation checks every output anyway
  (`WrongCodeError`).

## 14. RL formulation

**What you need to know.**
- The MDP tuple and each component in ForgeCompile: state (M, t), 12 actions, deterministic
  transitions, reward, γ = 1, horizon 12.
- The observation vector: 61 features + remaining-step fraction + one-hot of the previous
  action = 74 numbers.
- Why the reward telescopes, and why that makes it hard to exploit.
- Why the step penalty λ exists (compile-time proxy; prevents padding).
- Why this is strictly a POMDP.

See [RL_FORMULATION.md](RL_FORMULATION.md) and [THEORY §15](THEORY.md#15-pass-scheduling-as-an-mdp).

**Where in the code.** `rl/env.py` (`PassSchedulingEnv.reset/step`, `RewardConfig`);
`tests/rl/test_rl.py` (telescoping, stop/horizon, invalid-transformation penalty, restricted
action space).

**Key equations.**
- rₜ = w_c (C(Mₜ) − C(Mₜ₊₁))/C(M₀) + w_s (S(Mₜ) − S(Mₜ₊₁))/S(M₀) − λ.
- Σₜ rₜ = w_c (C(M₀) − C(M_K))/C(M₀) + w_s (S(M₀) − S(M_K))/S(M₀) − λK.

**Likely interview questions**
- *What is the state, action and reward?* Quote the table and the telescoping identity.
- *Could the agent hack the reward?* Not by cycling (telescoping), not by padding (λ), and not
  by deleting behaviour (outputs are checked and invalid transformations are penalized). It
  *can* exploit errors in the cost model itself, which is why EXP-002 and EXP-008 exist.
- *Why γ = 1?* The objective is final program quality over a bounded horizon. Discounting
  would bias the agent toward greedy behaviour, and EXP-010 ablates it.
- *Why put the step counter in the observation?* With a hard horizon, the optimal action
  depends on the remaining budget. Without it the problem is not Markov in time.

**Common misconceptions.**
- "RL is needed because the problem is sequential." Sequential problems can still be solved
  greedily. RL only helps if delayed effects matter, and that is measured, not assumed.
- "Truncation at T should bootstrap." Here T − t is observed, so t = T is a genuine terminal
  state.

## 15. RL implementation

**What you need to know.**
- Q-learning and the Bellman optimality equation; the TD target.
- DQN's two stabilizers (replay buffer, target network); why Double DQN; Huber loss.
- ε-greedy exploration with linear decay; warm-up with random actions, which also fits the
  fixed observation normalizer.
- Checkpoint selection on validation programs; several seeds, all reported.

See [THEORY §16](THEORY.md#16-from-q-learning-to-double-dqn).

**Where in the code.**
- `rl/dqn.py`: `MLP.forward/backward`, `Adam`, `Normalizer`, `DQNAgent.learn`, `train`,
  `DQNPolicy`.
- `rl/training.py`: `run_training_job`, one seed or condition per process.
- Tests: numerical gradient check, Adam on a linear target, DQN on a toy bandit,
  save/load round trip.

**Key equations.**
- y = r + γ (1 − done) Q(s′, argmax_a′ Q(s′, a′; θ); θ⁻).
- Huber: L(δ) = ½δ² if |δ| ≤ 1, otherwise |δ| − ½.
- ε(step) decays linearly from 1.0 to 0.05 over 6,000 steps after warm-up.

**Likely interview questions**
- *Why a replay buffer?* It breaks sample correlation and reuses expensive transitions.
- *Why a target network?* It gives a stable regression target.
- *Why Double DQN?* The max operator overestimates under noise.
- *Why NumPy and no PyTorch?* The network is tiny (74 → 128 → 128 → 12), the backward pass is
  checked against numerical gradients, and it removes a heavy dependency (D-039). GPUs would
  not help: the bottleneck is the environment (compiling and interpreting), not the network.
- *How did you pick the checkpoint?* Best validation geomean. Test programs are never used.

**Common misconceptions.**
- "Training reward going up means a better compiler." Training programs are not test
  programs, and ε-greedy returns understate the greedy policy. Only the held-out evaluation
  counts.

## 16. Experimental methodology

**What you need to know.**
- Each baseline and the question it answers (random, O2, frequency, majority, greedy oracle).
- Validation vs test vs OOD, and pre-registered hypotheses.
- Proxy (interpreter cost) vs target (native time); the cost of a decision vs its benefit.
- Seeds, noise bands, geometric means.
- Ablations: one factor changed at a time (EXP-009, EXP-010).

See [THEORY §17](THEORY.md#17-experimental-methodology-for-learned-compiler-heuristics) and
[EXPERIMENTS.md](EXPERIMENTS.md).

**Where in the code.** `ml/evaluate.py` (output-checked end-to-end evaluation), every
`experiments/EXP-*/run.py`, `utils/experiment.py` (run metadata: commit, environment, seed,
status).

**Likely interview questions**
- *What would convince you the learned policy is better?* A lower held-out geomean than O2
  and the other baselines, consistent across seeds and outside the noise band, *and* on native
  time, with a decision overhead smaller than the benefit.
- *What if RL loses to the supervised model?* Report it, then explain it, e.g. greedy is
  near-optimal in this action space.
- *How do you know the result generalizes?* Test on unseen generated programs and on the
  hand-written OOD set, and measure the distribution-shift ablation (EXP-009).

## 17. Failure analysis

Read [FAILURES.md](FAILURES.md) in order. For each entry, be ready to say what failed, how it
was noticed, the root cause, the fix, and the lesson. Three that come up often in interviews:
- **F-010** (SCCP missed optimizations): found by an experiment, not by a test. Experiments
  are also tests.
- **F-014** (misattributed "startup" time): a measurement artefact turned out to be the
  first-run cost of a fresh executable. Always ask "compared with what?".
- **F-015** (laptop run killed under memory pressure): it produced the resource policy
  (D-034) and failed/aborted run markers (D-035).
