# Interview Questions

Questions range from beginner to advanced. Each answer is short enough to say aloud, and points
to the code or document where the full argument lives. Numbers are quoted only from
[RESULTS.md](RESULTS.md). If a number is not there, the honest answer is "not measured".

Legend: 🟢 beginner · 🟡 intermediate · 🔴 advanced · 🛠 specific to this repository

---

## 1. The project in one minute

**🟢 What did you build?**
A compiler for a small typed language (MiniLang) written from scratch in Python. It has a
lexer, a Pratt/recursive-descent parser, a type checker, an SSA IR with a verifier and two
reference interpreters, 11 optimization passes, and an LLVM backend that produces native
executables. On top of that sits a study of *which passes to run in which order*: a
supervised pass selector and a Double-DQN agent, compared against fixed pipelines, random
schedules and a greedy oracle, with correctness checked on every output.

**🟢 Why build a compiler from scratch instead of using LLVM's passes?**
The subject is optimization decisions. Owning the IR and the passes means:
- every transformation can be explained and tested;
- the action space for ML/RL is under my control;
- correctness can be checked differentially.

LLVM is still used for what it is best at: code generation (D-002, LLVM_BACKEND.md §1).

**🟡 What is the most interesting thing you found?**
That the learned schedulers *could not* beat `-O2`, and why. A beam search over 12-pass
schedules found only about 1.1% average headroom above O2 on generated programs and 0% on the
hand-written kernels (EXP-011).

Further examples:
- the regret-vs-schedule paradox: the model beat the majority baseline 4.4× on one-step regret,
  yet lost to O2 end to end (EXP-004/005);
- two bugs found by experiments rather than tests (F-010 SCCP, F-016 unparseable register
  names).

## 2. Frontend

**🟢 Why separate lexing from parsing?**
Tokens are a regular language and grammar structure is context-free. Splitting them keeps
each simple and fast, and lets the parser work on a clean token stream with locations
(THEORY §2).

**🟡 What is a Pratt parser and why use it for expressions?**
Each token has binding powers. The parser loop keeps consuming operators while their
left-binding power exceeds the current minimum. Precedence and associativity become a table
(`ast/operators.py`) instead of one grammar rule per precedence level (THEORY §3).

**🟡 How does your parser report several errors in one run?**
Panic-mode recovery: after an error it skips to a synchronizing token (`;`, `}`, a statement
keyword), tracking brace depth (F-002), and continues.

**🛠 How do you test the parser beyond hand-written cases?**
- A parse → format → parse round trip on every example.
- 1,000 random expression trees.
- Precedence tables tested against expected bracketings.

## 3. Semantic analysis

**🟢 What is a symbol table?**
A mapping from names to declarations, organized as a stack of scopes. A lookup walks outward
from the innermost scope.

**🟡 How do you avoid cascades of type errors?**
An `ERROR` type is compatible with everything and suppresses further diagnostics about the
same expression (D-014).

**🛠 How did you test the type checker's tests?**
Mutation testing: four bugs were injected into the checker, and the suite caught all four
(F-005).

## 4. IR, CFG, SSA

**🟢 Why do compilers use an IR?**
To decouple N frontends from M backends, and to give optimizations a uniform, explicit,
analyzable form: three-address code, explicit control flow, explicit memory (THEORY §6).

**🟢 What is a basic block?**
A maximal straight-line sequence of instructions with one entry (the first instruction) and
one exit (the terminator).

**🟢 What is SSA?**
Static single assignment: every virtual register has exactly one definition. Def-use chains
become trivial, and many analyses become sparse.

**🟡 Why are phi nodes required?**
Where control-flow paths merge, a variable can have different reaching definitions. A phi
selects the value according to the predecessor the control came from, which keeps the
single-definition property.

**🟡 What is dominance?**
Block A dominates block B if every path from the entry to B passes through A. SSA requires that
every definition dominates its uses. Phis are placed at the *dominance frontier* of each
definition.

**🔴 How did you construct SSA?**
Cytron et al.:
1. Compute dominators (Cooper–Harvey–Kennedy iterative algorithm).
2. Compute dominance frontiers.
3. Place phis at the iterated dominance frontier of each promoted variable's definitions.
4. Rename with a dominator-tree walk and per-variable stacks.

See `ir/ssa.py` and IR.md §9.

**🛠 Why didn't you implement out-of-SSA?**
The LLVM backend consumes SSA directly, since LLVM has phis, so destruction was never needed
(D-017).

**🛠 How do you know your IR transformations are correct?**
1. The verifier runs after every pass (structure + SSA dominance).
2. Differential testing compares the AST interpreter, the pre-SSA and SSA IR interpreters,
   optimized IR and native executables on examples and generated programs.
3. Since F-016, optimized IR must also round-trip through its text format.

## 5. Optimizations

**🟢 What is dead code elimination?**
Removing instructions whose results are never used and that have no side effects. In
MiniLang a possible trap counts as a side effect, so a division that might trap is never
deleted (THEORY §10).

**🟡 What is SCCP and why is it better than constant folding?**
Sparse conditional constant propagation tracks a lattice value (⊤, constant, ⊥) per SSA value
*and* which CFG edges are executable. It finds constants that only hold because a branch is
never taken, which plain folding cannot.

**🟡 Why can LICM make code slower?**
Hoisting moves code to the preheader, so it runs even if the loop body never executes. Without
loop rotation (guarding the hoisted code), a zero-trip loop pays for work it never needed.
EXP-001 measured a 1.87× slowdown on one program.

**🟡 Why is optimization ordering difficult?**
Passes enable, disable, duplicate and sometimes harm each other. The best order depends on the
program, and the space of orders is huge (11¹² schedules of length 12). THEORY §13.

**🟡 Why can't we simply apply every optimization, repeatedly?**
- Compile time: each pass costs time, often for no gain.
- Some passes trade one resource for another (inlining: speed vs code size).
- Some are harmful in context (LICM above).
- Iterating to a fixed point can still land in a worse local optimum than a good order.

**🛠 Name a phase-ordering dependency you measured.**
`bce` and `strength` do nothing unless `copyprop` runs first, because they pattern-match
induction variables through copies (D-023, EXP-001).

## 6. LLVM backend

**🟢 Why use LLVM?**
Register allocation, instruction selection and object emission are a separate project. LLVM
provides industrial code generation, so every ForgeCompile decision runs as real machine code
(D-002).

**🟡 What is undefined behaviour in LLVM IR, and how did you avoid it?**
LLVM, like C, leaves `sdiv INT_MIN, -1`, overflow with `nsw`, and out-of-range `fptosi`
undefined, and the optimizer may assume they never happen. MiniLang defines all of them. The
emitter therefore:
- omits `nsw`;
- calls a checked division helper;
- uses `llvm.fptosi.sat`;
- tests the corner cases at `-O3` (THEORY §11).

**🟡 Why do you measure at LLVM -O0?**
To isolate ForgeCompile's effect. At -O2, LLVM redoes most classical optimizations, and its
gains would be wrongly attributed to my passes (D-028). LLVM -O2 is reported separately as a
reference (EXP-003).

**🔴 What is the difference between compile-time and run-time optimization?**
Compile-time (static) optimization transforms code before execution using only facts provable
from the program text, which is everything here. Run-time (dynamic) optimization, as in JITs,
uses observed behaviour (profiles, types) and can specialize and deoptimize. ForgeCompile's
learned policies are still *static*: they choose from static features.

## 7. Benchmarking

**🟡 How do you make benchmark numbers trustworthy?**
- A correctness gate before timing.
- A warm-up run.
- Configurations interleaved in a seeded random order.
- Medians and minima, with the CV reported.
- Geometric means of ratios.
- A two-run noise band; nothing smaller than the band is claimed.

See THEORY §12.

**🛠 What measurement mistake did you make?**
I first called 50–90 ms "process startup". It was the first run of a freshly built
executable; warm startup is about 5 ms (F-014). The correction is kept visible.

**🛠 Is the interpreter cost a good proxy for native time?**
Only weakly: pooled Spearman 0.29 across 120 (kernel, pipeline) points (EXP-002). It works
better on the memory, vector, stencil and helper-call kernels (Spearman 0.49–0.65). It fails on latency-bound arithmetic
(`arith_hash`: O2 cuts 6% of the cost but runs 9% slower) and on `loop_nest` (predicted −64%,
measured ≈ 0%). At LLVM -O0 every value lives in a stack slot, so removing cheap register work
saves little. I kept the proxy because it is exact and cheap, and I re-measured the final
schedules natively (EXP-008).

## 8. ML for pass selection

**🟢 What is the learning problem?**
Given the IR's 61 static features, predict the next pass, or stop. It is multi-class
classification, applied greedily.

**🟡 Where do labels come from?**
At each state, every pass is applied to a copy, the result is executed on the IR interpreter,
and the label is the cheapest result. Nothing is synthetic, and EXP-007 replays labels from
scratch to prove they are reproducible.

**🟡 Why regret instead of accuracy?**
Passes often tie (constfold vs sccp). Accuracy punishes harmless choices, while regret counts
only real losses.

**🟡 How do you avoid benchmark leakage?**
- Split by program, never by state; states of one program are near-duplicates.
- Disjoint generator seed ranges, checked by name and by source text.
- A separate hand-written OOD set that is never used for training or selection.
- Model selection on validation only, and test scored once.

**🟡 What constitutes a good baseline?**
One that answers "is it just…?":
- random: is any schedule fine?
- O2: is hand-tuning enough?
- frequency order: is it just the label prior?
- majority class: is it just the most common label?
- greedy oracle: how much is left to gain?

**🔴 Your features include hand-made "opportunity detectors". Isn't the model just reading them?**
Largely yes, but not *only* them. In EXP-009:
- the 8 detectors alone recover 96% of the regret reduction over the majority baseline;
- removing them hurts validation regret most (0.0163 vs 0.0148);
- removing any one other group barely matters, because the groups are redundant: generic
  counts carry similar information.

**🔴 Prediction accuracy vs compiler performance?**
They are different things. A model can be accurate on easy states and wrong on the few that
matter, and greedy application compounds errors. Schedule quality is therefore evaluated end to
end (EXP-005), and natively (EXP-008).

## 9. RL formulation

**🟢 How did you formulate compiler optimization as an RL problem?**
- The state is the current IR (observed as 61 features + remaining-step fraction + previous
  action = 74 numbers).
- An action is one of the 11 passes, or stop.
- Transitions apply the pass, deterministically.
- The reward is the relative cost reduction minus a per-pass penalty.
- γ = 1, horizon 12.

See RL_FORMULATION.md.

**🟡 What exactly is the reward, and why that one?**
rₜ = (C(Mₜ) − C(Mₜ₊₁))/C(M₀) − λ. It telescopes to the total relative improvement minus λ times
the number of passes:
- cycling cannot farm reward;
- padding with no-op passes is penalized;
- programs of different sizes are comparable.

**🟡 Why RL instead of supervised learning?**
The supervised model imitates a *one-step greedy* oracle. RL optimizes the *sum* of rewards, so
it can learn enabling sequences (e.g. copyprop before bce) that greedy search skips.

Here it did not pay off:
- beam search shows lookahead is worth only about 1% (EXP-011);
- the DQN finished below both the supervised model and O2 (EXP-006/012).

**🟡 Why is the step counter in the observation?**
With a hard horizon the optimal action depends on the remaining budget. Observing it makes the
problem Markov in time, and t = T becomes a genuine terminal state.

**🔴 Is it really an MDP?**
Strictly a POMDP: features are a lossy summary of the IR. The previous action and the step
counter recover the most decision-relevant missing information.

**🔴 Could the agent exploit the reward?**
- Not by cycling (telescoping).
- Not by padding (λ).
- Not by breaking semantics: outputs are re-checked, and invalid transformations are penalized
  and counted. There were 0 invalid transformations.
- It *can* exploit errors in the cost model itself. That is why EXP-002 validates the proxy and
  EXP-008 re-measures natively.

## 10. RL implementation

**🟡 Why DQN?**
Small discrete action space, fixed-length observations, and expensive environment steps.
Off-policy learning with replay reuses every transition, whereas policy-gradient methods
discard experience after each update.

**🟡 Explain replay buffers and target networks.**
- Replay buffer: transitions are sampled uniformly from a buffer, which breaks temporal
  correlation and reuses data.
- Target network: a periodically copied network computes TD targets, so the regression target
  does not shift with every update.

**🔴 What does Double DQN fix?**
The max in the TD target overestimates values under noise. Double DQN selects the argmax with
the online network and evaluates it with the target network.

**🛠 Why NumPy and not PyTorch?**
- The network is tiny (74 → 128 → 128 → 12), and its backward pass is checked against
  numerical gradients.
- The bottleneck is the environment (compilation and interpretation), not the network.
- A GPU would sit idle (D-039).

**🛠 How do you select the checkpoint?**
Every 100 episodes the greedy policy runs on 40 validation programs, and the checkpoint with
the best geomean cost ratio is kept. Test programs are never used. Every seed is reported.

**🟡 What happens when the learned policy makes a bad decision?**
- *Correctness:* nothing breaks. Every action is a semantics-preserving pass, and the
  evaluation checks every output (`WrongCodeError`).
- *Quality:* a bad pass may waste compile time or make the program slower (e.g. LICM).
- The policy can recover in later steps, and the "worst ratio" column in the results shows the
  damage when it does not.

**🟡 Why did your RL agent fail?**
Three measured reasons:
1. **It repeated no-op passes** (EXP-006). A repeat's true value is only λ = 0.002 below the
   best action, which is smaller than the Q-network's error. Adding the supervised policy's
   "never retry in an unchanged state" rule closed 31–63% of the gap to O2 (EXP-012).
2. **More training did not help.** With 4× the episodes, the best validation checkpoints came
   from episodes 100–1,800 of 12,000 (EXP-012).
3. **There was almost nothing to learn.** Beam search finds only about 1% headroom above O2
   (EXP-011).

A two-step chain-MDP test shows that the TD update itself works.

**🔴 If neither ML nor RL beat O2, what is the value of the project?**
- A complete, correctness-checked compiler.
- A clean experimental harness.
- A *quantified* negative result with root causes:
  - headroom (EXP-011);
  - error compounding (EXP-005);
  - action gaps (EXP-006/012);
  - workload coverage (EXP-004).
- It tells you exactly what would have to change for learned scheduling to pay off
  (ROADMAP "Future work"). Reporting that honestly is the point.

## 11. Evaluation and limitations

**🟡 How do you evaluate generalization?**
- Unseen generated programs (test split).
- Hand-written kernels from a different distribution (OOD).
- A train-on-one-profile, test-on-another ablation (EXP-009).

**🟡 Does the optimization quality justify the inference overhead?**
Compare the mean decision milliseconds with the run-time savings × executions (EXP-005/008).
For a program run once, almost nothing justifies tens of milliseconds of scheduling. For a hot
kernel run millions of times, anything measurable does.

**🔴 What are the limitations?**
- The interpreter cost is a proxy for time (EXP-002).
- Features are static; there is no profile information.
- The action space is 11 passes without parameters.
- Training programs are synthetic.
- LLVM -O0 code generation makes native effects small and latency-dominated.
- The RL agent observes features, not the IR (POMDP).
- Results are on one machine, a shared server.

**🔴 What would you do next?**
- A learned cost model, or native-time rewards on a subset.
- Graph neural networks over the IR instead of hand-made counts.
- Parameterized passes (unroll factors, inlining thresholds).
- Evaluation at LLVM -O2 to see whether ForgeCompile decisions survive LLVM.
- MCTS or beam search with the DQN as a heuristic, to test whether lookahead pays off.

## 12. Repository-specific deep dives 🛠

- **Walk me through `PassSchedulingEnv.step`.**
  1. Apply the pass to a copy (verified).
  2. Re-check the output against the reference, memoized by IR hash.
  3. Compute the reward from memoized costs.
  4. Update the step counter and the previous action.
  5. Truncate at T.
- **Why does `ModelPolicy` remember tried passes per state?** A no-op pass leaves features
  unchanged, so the model would predict it forever. Remembering tried actions per IR hash
  forces progress.
- **Why are costs memoized by a hash of the printed IR?** States recur constantly (many passes
  are no-ops), and the interpreter run is the expensive part.
- **Why is the dataset cache keyed by the tree hash of `src/forgecompile`?** Labels depend only
  on the compiler's code and the configuration. Documentation commits should not force a
  rebuild, but compiler changes must (D-037).
- **What did EXP-007 check, and what did it find?**
  - It checked determinism across worker counts, split disjointness, and exact replay of
    labels.
  - The first attempt found that 10% of training programs trapped (D-036).
- **Tell me about a bug an experiment found.**
  - F-010: SCCP kept dead divisions.
  - F-016: a negative strength-reduction factor produced the register name `%i.x-2`, which the
    IR parser rejects. It surfaced only when the ML pipeline cloned modules through the text
    format at scale.
