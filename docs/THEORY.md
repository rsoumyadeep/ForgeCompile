# Compiler and ML Theory, Connected to the Code

Each section explains a concept from first principles and then points to the code that
implements it. Sections are written when the corresponding code exists, so that no section is
textbook material without a code link.

| Section | Phase | Status |
|---------|-------|--------|
| 1. What a compiler is, and why it is split into phases | 0 | ✅ below |
| 2. Lexing | 1 | ✅ |
| 3. Grammars and parsing (recursive descent, Pratt) | 1 | ✅ |
| 4. The AST | 1 | ✅ |
| 5. Semantic analysis: symbol tables, scopes, types | 2 | ✅ |
| 6. Intermediate representations | 3 | ✅ |
| 7. Control-flow graphs and basic blocks | 3 | ✅ |
| 8. Dominance and SSA | 3 | ✅ |
| 9. Data-flow analysis (lattices, fixpoints) | 4 | ✅ |
| 10. Why each optimization is valid | 4 | ✅ |
| 11. LLVM IR | 5 | ✅ |
| 12. Measuring performance | 6 | ✅ |
| 13. Why pass ordering is hard (the phase-ordering problem) | 7 | ✅ |
| 14. Pass selection as supervised learning | 7 | ✅ |
| 15. Pass scheduling as an MDP | 8 | ✅ |
| 16. From Q-learning to Double DQN | 9 | ✅ |
| 17. Experimental methodology for learned compiler heuristics | 10 | ✅ |

---

## 1. What a compiler is, and why it is split into phases

A compiler translates a program from a source language into a target language and preserves
its **observable behaviour**: the outputs it prints and the value it returns. Everything else
(which registers are used, the instruction order, whether a computation happens at all) may
change. That freedom is what makes optimization possible. The rule that "only observable
behaviour must be preserved" comes up again in every optimization pass and in the RL reward
design (an agent must not be rewarded for deleting observable behaviour).

Compilers are split into phases because each phase works best with a different representation:

| Phase | Input → Output | Representation suits... |
|-------|----------------|-------------------------|
| Lexing | characters → tokens | discarding whitespace/comments, recognising literals |
| Parsing | tokens → AST | nesting structure, operator precedence |
| Semantic analysis | AST → typed AST | names, scopes, types (tree-shaped questions) |
| Lowering | typed AST → IR | explicit control flow and temporaries |
| Optimization | IR → IR | analysis over a CFG; SSA makes def-use explicit |
| Code generation | IR → LLVM IR → machine code | instruction selection, register allocation |

With *N* source languages and *M* targets, a shared IR needs *N + M* translators instead of
*N × M*. This is the argument for LLVM, and for ForgeCompile having its own IR between MiniLang
and LLVM IR. The ForgeCompile IR is where the project's own optimizations and the ML/RL
scheduler operate.

**In the code:** the pipeline is described in [ARCHITECTURE.md](ARCHITECTURE.md). Each stage
will live in its own sub-package of `src/forgecompile/` with one input type and one output
type.

---

## 2. Lexing

**What a token is.** A token is the smallest unit of meaning in the grammar: a keyword
(`while`), an identifier (`count`), a literal (`3.5`), or an operator (`<=`). The lexer (also
called a scanner or tokenizer) turns a character stream into a token stream. Each token
records its kind, its exact text and its source span.

**Why lexing is a separate phase.**

1. *Simpler grammar.* Without a lexer, the parser's grammar would have to spell out
   whitespace, comments, digit sequences and keyword boundaries at every point. With one, the
   grammar talks about `IDENT` and `INT` and never about characters.
2. *Different machinery.* Tokens form a **regular language**: each kind can be described by
   a regular expression and recognised by a finite automaton, with no memory needed. Program
   structure (nested parentheses and blocks) is **context-free** and needs a stack. Each
   phase uses the weakest tool that works.
3. *Speed.* The lexer touches every character exactly once, in O(n). The parser then works on
   far fewer items.

**Maximal munch.** When several tokens could match at a position, take the longest. `<=`
must be one token, not `<` followed by `=`. `lexer.py` implements this by trying the symbol
table longest-first (`tokens.SYMBOLS` is sorted by length).

**A lookahead subtlety in MiniLang.** `0..10` must lex as `INT DOTDOT INT`. A naive number
scanner reads `0.` as the start of a float. `Lexer._number` only consumes a `.` when a digit
follows it, which needs one character of lookahead.

**Errors.** A character that cannot start any token is reported and skipped, and lexing
continues. For a lone `&` the lexer guesses that `&&` was meant and emits that token, so the
parser does not produce a cascade of follow-on errors (see FAILURES F-002).

**In the code:** `src/forgecompile/frontend/lexer.py` (`Lexer.tokenize`),
`src/forgecompile/frontend/tokens.py`. Tests: `tests/frontend/test_lexer.py`. Try
`forgecompile lex examples/gcd.mini`.

## 3. Grammars and parsing

**Context-free grammars.** A grammar is a set of rules such as
`while_stmt → "while" expr block`. A program is syntactically valid if it can be derived from
the start symbol. The parser's job is to find that derivation and build a tree from it. The
grammar for MiniLang is in LANGUAGE.md §2.

**Recursive descent.** Each grammar rule becomes a function. `_while()` consumes `while`,
calls `_expression()`, then calls `_block()`. The parser chooses a rule by looking at the next
token. MiniLang's statements all begin with a distinct keyword, or else are expressions, so
one token of lookahead is enough; the grammar is LL(1) for statements. Recursive descent is
what production compilers such as GCC, Clang, Go and rustc use, because it is fast and easy to
debug, and it gives full control over error messages.

**The problem with expressions.** Precedence can be encoded in the grammar with one rule per
level (`additive → multiplicative (("+"|"-") multiplicative)*`, ...). With nine levels that
means nine nearly identical functions, and a nine-deep call chain just to parse the literal
`1`.

**Pratt parsing (precedence climbing).** One function handles every binary operator using a
table of binding powers:

```
parse_expression(min_prec):
    left = parse_unary()
    while next token is a binary operator op with precedence(op) >= min_prec:
        consume op
        right = parse_expression(precedence(op) + 1)    # +1 => left-associative
        left = Binary(op, left, right)
    return left
```

Here is why `+ 1` gives left-associativity. In `a - b - c`, the recursive call parsing the
right operand of the first `-` runs with `min_prec = ADDITIVE + 1`. It sees the second `-`
(precedence `ADDITIVE`, which is less than `min_prec`) and stops. So the second `-` attaches
to the outer `(a - b)`, giving `(a - b) - c`. A right-associative operator would recurse with
`precedence(op)` instead.

The same loop handles precedence. In `1 + 2 * 3`, the right operand of `+` is parsed with
`min_prec = ADDITIVE + 1`. `*` has precedence `MULTIPLICATIVE` (≥ min_prec), so it is absorbed
into the right operand: `1 + (2 * 3)`.

**Non-associative operators.** MiniLang rejects `a < b < c`. `Parser._expression` remembers
whether it has already combined an operator of a non-associative level in the current loop. A
second operator of the same level raises "comparison operators cannot be chained".
Parenthesized sub-expressions are parsed by a fresh call, so `(a < b) == c` is allowed.

**Error recovery (panic mode).** When a statement fails to parse, the parser records the
error and skips ahead to a synchronization point: after a `;`, before a `}`, or before a
statement keyword. Then it continues. Recovery must respect nesting. An early version did
not, and the `}` of a skipped `if` body was mistaken for the end of the function (FAILURES
F-002).

**In the code:** `src/forgecompile/frontend/parser.py` (`Parser._expression` is the Pratt
loop; `Parser._synchronize` handles recovery). Precedence table:
`src/forgecompile/ast/operators.py`. Tests: `tests/frontend/test_precedence.py` and
`tests/frontend/test_syntax_errors.py`.

## 4. The abstract syntax tree

**Concrete vs abstract syntax.** A *parse tree* (concrete syntax tree) contains every token,
including parentheses, semicolons and keywords. An *abstract* syntax tree keeps only what
affects meaning. `(1 + 2) * 3` becomes `Binary(*, Binary(+, 1, 2), 3)`. The parentheses are
gone, because the nesting already records the grouping. Comments and formatting are gone too.
`tests/frontend/test_parser.py::test_nested_parentheses_are_transparent` checks this.

**Why compilers use an AST rather than source text.**

- Later phases ask structural questions ("what is the condition of this `if`?") that are
  trivial on a tree and painful on text.
- *Desugaring* happens at tree construction. MiniLang turns `else if` into a nested `if`
  inside an `else` block, so every later phase handles only one form of `if`.
- Each node carries a source **span**, so a type error found in Phase 2 still points at the
  right characters.

**Equality ignores spans.** The node dataclasses mark `span` (and the later `ty` annotation)
as `compare=False`. Two trees parsed from differently formatted sources therefore compare
equal, which makes the round-trip property testable.

**The round-trip property.** `format_program` (`src/forgecompile/ast/formatter.py`) prints an
AST back to source with the *minimum* parentheses. The test suite checks
`parse(format(tree)) == tree` for the example programs and for 1,000 randomly generated
expression trees (`tests/frontend/test_roundtrip.py`). This property found a real bug on its
first run (FAILURES F-003). The formatter dropped the parentheses in `(a != b) != c`. That
change is harmless for left-associative operators, but wrong for non-associative ones.

**In the code:** `src/forgecompile/ast/nodes.py`, `dump.py` (tree and S-expression views),
`formatter.py`. Try `forgecompile parse examples/fibonacci.mini`.

## 5. Semantic analysis: symbol tables, scopes and types

**What the parser cannot check.** A context-free grammar cannot express "a variable must be
declared before use" or "both operands of `+` must have the same type". Those rules depend on
*context*: information declared somewhere else in the program. Semantic analysis is the phase
that walks the AST carrying that context.

**Symbol tables and scopes.** A *symbol* records one declaration: name, type, kind and
location. A *scope* maps names to symbols. Scopes nest, and each scope points to its parent,
so lookup walks outward from the innermost scope and the first match wins. That is exactly
**shadowing**:

```
let x = 1;            // scope A: x#0 : int
{ let x = 2.5;        // scope B (parent A): x#1 : float  -- shadows x#0
  print(x); }         // lookup finds x#1 in B
print(x);             // B is gone; lookup finds x#0 in A
```

Name resolution stores the *symbol object* on each `Name` node, not just the string. The two
`x`s are different variables with different types and different `uid`s. IR lowering keys
storage on the symbol, so shadowed variables never collide.

**Type checking as a recursive function.** Each expression's type is computed from its
children's types (a *synthesized attribute*, in attribute-grammar terms). It reads like a set
of inference rules. For example, the rule for `+`:

```
Γ ⊢ e1 : int    Γ ⊢ e2 : int          Γ ⊢ e1 : float    Γ ⊢ e2 : float
───────────────────────────────       ───────────────────────────────────
     Γ ⊢ e1 + e2 : int                       Γ ⊢ e1 + e2 : float
```

Here Γ (the typing environment) is the scope chain. If no rule applies, as with
`1 + 2.0`, the program is ill-typed. `TypeChecker._infer_binary` is a direct transcription of
these rules.

**Two passes for functions.** Pass 1 records every function signature, and pass 2 checks the
bodies. A call can therefore refer to a function defined later in the file. This is how
mutual recursion works without C-style prototypes.

**Error recovery with an error type.** When an expression is ill-typed, the checker reports
it once and gives the expression the special type `<error>`. Every rule silently accepts
`<error>`, so in `(1 + true) * 2` the outer `*` does not complain about its broken left
operand. Without this, one mistake would produce a chain of errors up the tree.
`test_use_of_undefined_variable_does_not_cascade` checks this.

**Flow-sensitive checks on the AST.** "Missing return" asks whether control can reach the end
of a non-void function. `semantic/control_flow.py` answers this with *completes-normally*
rules, similar to Java's (JLS §14.22):
- a `return` never completes;
- an `if` with an `else` completes iff either branch does;
- `while true` completes only if it contains a `break` aimed at it.

The analysis is deliberately **conservative** (sound but incomplete). Deciding the question
exactly would require deciding whether arbitrary loop conditions terminate, which is
undecidable in general (it reduces to the halting problem). A sound compiler therefore
rejects some programs that would in fact always return.

**In the code:** `src/forgecompile/semantic/symbols.py` (`Scope`, `VariableSymbol`),
`checker.py` (`TypeChecker`), `control_flow.py`. Tests: `tests/semantic/` (116 tests). Try
`forgecompile check --dump examples/newton_sqrt.mini` to see every expression's type.

## 6. Intermediate representations

**What an IR is for.** An IR is the representation a compiler *optimizes*. Source syntax is
designed for humans and machine code for hardware; the IR is designed so that questions like
"is this value constant?", "is this computation repeated?" and "can this code run?" are easy
to ask and to answer.

**Three-address code.** Each instruction does one operation on at most two inputs and names
its result: `%t3 = add %total, %t2`. Compound expressions are flattened. Every intermediate
value gets a name, so a pass can talk about "the result of this multiply" and replace or move
it.

**Lowering** (`lowering.py`) is the translation from AST to IR. Ours is deliberately *naive*:
- each variable becomes a register assigned by `copy`;
- `&&` becomes branches;
- `m[i][j]` becomes explicit bounds checks plus a flat offset `i*C + j`;
- a literal index still produces `mul 0, 4`.

Naive lowering is easy to verify, and every inefficiency it leaves becomes measurable work
for the optimizer. That is the separation of concerns compilers rely on: correctness first,
improvement second.

**Two oracles.** The IR interpreter defines what IR *means*. The AST interpreter
(`runtime/ast_interpreter.py`) defines what MiniLang *means*, transcribing LANGUAGE.md §7 with
none of the IR machinery: nested lists rather than flat buffers, exceptions rather than
blocks. Lowering is correct when the two agree. They are compared on every example and on
1,000 generated programs.

**In the code:** `ir/instructions.py`, `ir/function.py`, `ir/printer.py`, `lowering.py`; see
[IR.md](IR.md). Try `forgecompile ir --no-ssa examples/gcd.mini`.

## 7. Control-flow graphs and basic blocks

**Basic block.** A basic block is a maximal sequence of instructions with one entry (the top)
and one exit (the terminator at the bottom). If its first instruction runs, all of them run,
in order. This is why many analyses work per block and only reason about *edges* between
blocks.

**CFG.** Nodes are blocks; there is an edge A → B when A's terminator can jump to B. Loops
appear as *back edges* (latch → header).

**Reverse postorder (RPO).** Do a DFS from the entry and list the blocks in reverse order of
finishing. Every block then comes before its successors, except across back edges. Forward
data-flow analyses converge in very few passes when they visit blocks in RPO
(`analysis/cfg.py::reverse_postorder`).

**Critical edges.** An edge from a block with several successors to a block with several
predecessors is *critical*. Code cannot be placed on it without splitting it with a new
block (`split_edge`). This matters for code motion and for out-of-SSA translation.

## 8. Dominance and SSA

**Dominance.** A *dominates* B if every path from the entry to B passes through A. The
nearest strict dominator is the *immediate dominator*, and the idom edges form the
**dominator tree**.

The Cooper–Harvey–Kennedy algorithm (`analysis/dominators.py`) computes it by iterating

```
idom(b) = intersect_{p ∈ preds(b), p processed} p      (in RPO, until stable)
```

where `intersect` walks two nodes up the current tree until they meet.

**Dominance frontier.** B ∈ DF(A) iff A dominates a predecessor of B but does not strictly
dominate B. It is the boundary where A's influence ends, which is exactly where a definition
made in A can meet a competing definition from another path.

**SSA.** Each register is assigned exactly once. To make that possible at join points, a
**phi** chooses a value according to the incoming edge: `%x.3 = phi [%x.1, then],
[%x.2, else]`.

**Why phis go at dominance frontiers (Cytron et al.).** A definition of x in block D reaches,
unchallenged, every block D dominates. The first blocks it does *not* dominate, but still
reaches, are DF(D). There a different definition may also arrive, so a phi is needed. A phi
is itself a definition, so the process repeats on the frontier of the frontier: the
**iterated** DF.

**Renaming.** Walk the dominator tree with a stack of versions per variable. Each definition
pushes a fresh name. Each use takes the top of the stack. When leaving a block, pop what it
pushed. Walking the *dominator* tree is what guarantees that the top of the stack is the
definition that dominates the use.

**The dominance property** is the invariant of SSA: every definition dominates all its uses,
where a phi input counts as a use at the end of its incoming block. `ir/verify.py` checks it
after every transformation.

**In the code:** `ir/ssa.py::construct_ssa`, `ir/verify.py::_check_ssa`. Tests:
`tests/ir/test_ssa.py`, `tests/analysis/test_dominators.py`. Try
`forgecompile ir examples/gcd.mini`.

## 9. Data-flow analysis: lattices and fixed points

**The general shape.** A data-flow analysis computes, for each program point, a fact taken
from a **lattice** (a partially ordered set of facts with a *meet*, the "least upper bound"
of information). Each instruction has a **transfer function** f mapping input facts to
output facts. At join points the facts from all predecessors are combined with meet. The
analysis iterates

```
OUT[b] = f_b( ⊓_{p ∈ preds(b)} OUT[p] )
```

until nothing changes.

**Why it terminates.** Two conditions:
1. The transfer functions are **monotone**: more input information never gives less output
   information.
2. The lattice has **finite height**: each value can only move down a bounded number of
   times.

Together these guarantee that iteration reaches a fixed point. Starting from the
*optimistic* top element gives the **maximal** fixed point, i.e. the most precise sound
answer.

**SCCP as the worked example** (`optimization/passes/sccp.py`).
- Lattice per register: `TOP > {…, -1, 0, 1, …} > BOTTOM`, with height 3, so each register
  changes at most twice.
- Meet: `TOP ⊓ x = x`; `c ⊓ c = c`; `c1 ⊓ c2 = BOTTOM` for `c1 ≠ c2`.
- Transfer: fold the operation if all inputs are constants; BOTTOM if any input is BOTTOM.
- The **conditional** part: phis meet only values arriving over *executable* edges, and a
  branch on a constant marks only one edge executable. Optimism here is what proves the
  loop-carried constant in OPTIMIZATIONS.md.
- **Sparseness**: SSA means each register has one definition, so the facts are attached to
  registers rather than to (variable × program point) pairs. When a value changes, only its
  users are revisited, via def-use edges.

**Other analyses in the code, framed the same way.**

| Analysis | Lattice / fact | Direction | Where |
|----------|----------------|-----------|-------|
| Dominators | sets of blocks, meet = intersection | forward | `analysis/dominators.py` (CHK solves it on the dominator tree) |
| Liveness, as used by DCE | live / dead per instruction | backward (along def-use) | `passes/dce.py` (mark phase) |
| Reachability | reachable or not | forward | `analysis/cfg.py` |
| Completes-normally (missing return) | bool per statement | AST, structural | `semantic/control_flow.py` |

## 10. Why each optimization is valid

Each pass's correctness rests on a small number of arguments, which recur throughout:

1. **Value equality plus dominance makes substitution valid.** In SSA, replacing every use of
   `%r` with a value v is correct if v always equals `%r` and v's definition dominates
   every use. This argument justifies copyprop, trivial-phi removal, CSE, constant
   propagation and strength reduction. When the dominance half was forgotten in one case
   (an `undef` phi input), the verifier caught it (FAILURES F-009).
2. **Observable behaviour is the contract.** Only `(stdout, exit status)` must be
   preserved. Since MiniLang defines traps as observable, any instruction that *may trap*
   is treated like an output statement: never deleted as unused, never hoisted
   speculatively. C compilers may delete `x / y` when unused, because division by zero is
   undefined behaviour in C.
3. **Speculation needs safety.** Moving code to a point where it executes on more paths (LICM)
   is only valid for instructions with no effect, no trap and no dependence on memory.
   *Validity* is separate from *profitability*: LICM is always correct, but can be slower
   (EXP-001, 1.87× worst case).
4. **Floating-point identities must hold for every IEEE value.** `x + 0.0 ≠ x` when x = −0.0;
   `x * 0.0 ≠ 0.0` when x is NaN or inf; `x - x ≠ 0.0` when x is inf. The `simplify` pass only
   uses identities that are exact over all doubles, including NaN and signed zero.
5. **Loop facts need an induction argument.** Strength reduction maintains the invariant
   `%s == %i·k` (holding modulo 2⁶⁴). Bounds-check elimination proves `0 ≤ %i < N` from the
   loop guard plus a no-overflow condition on the step.

**In the code:** each pass's docstring states its correctness argument;
[OPTIMIZATIONS.md](OPTIMIZATIONS.md) collects them with examples.

## 11. LLVM IR

**What LLVM is.** LLVM is a compiler infrastructure built around one IR. Frontends (Clang, rustc,
Swift, and here ForgeCompile) translate to LLVM IR. Shared middle-end passes optimize it, and
backends turn it into machine code for many targets. This is the *N + M* argument from §1 at
industrial scale.

**LLVM IR in one paragraph.** It is typed, three-address and in SSA form, with basic blocks,
`phi` nodes and explicit terminators, very much like ForgeCompile's IR, which is why our
translation is nearly 1:1 (`backend/llvm_emitter.py`). The differences that matter here:
- values are instructions (no `copy`);
- memory is reached through `getelementptr` address arithmetic;
- arithmetic carries flags (`nsw`, `nuw`, `exact`) that *promise* the absence of overflow;
- some operations have **undefined behaviour or poison** results.

**Undefined behaviour and poison.** LLVM IR inherits C's attitude: `sdiv INT_MIN, -1` is UB;
`add nsw` that overflows is poison; `fptosi` of an out-of-range double is poison. The optimizer
may assume these never happen and transform code accordingly. MiniLang defines all of them
(LANGUAGE.md §7), so the backend must never emit a construct whose UB case a MiniLang program
could reach. That is why it:
- omits `nsw`;
- calls `@llvm.fptosi.sat` (saturating, defined for every input);
- guards division with a helper that traps on zero and special-cases −1.

`tests/backend/test_native.py::test_semantic_corner_cases` runs those exact cases at LLVM `-O3`,
where an exploitable UB would most likely change the output.

**Ordered vs unordered float comparisons.** LLVM's `fcmp` has 16 predicates. `oeq` ("ordered
and equal") is false if either side is NaN; `une` ("unordered or not equal") is true if either
side is NaN. IEEE `!=` is `une`, so mapping MiniLang `!=` to `one` would make `nan != nan`
false. This is a classic backend bug that is avoided here by construction.

**Why use LLVM at all** (DECISIONS D-002)? Writing instruction selection, register allocation
and an object-file writer for x86-64 is a separate project. The project's subject is
optimization and *where* to apply it, and LLVM lets every ForgeCompile decision run as real
machine code. It also gives an honest comparison point: what an industrial optimizer achieves
on the same input (`--llvm-opt 2`).

**In the code:** `backend/llvm_emitter.py` (translation table in its docstring),
`backend/runtime/fc_runtime.c`, `backend/native.py`; see [LLVM_BACKEND.md](LLVM_BACKEND.md).
Try `forgecompile llvm examples/gcd.mini` and then `--llvm-opt 2`.

## 12. Measuring performance

**Why measurement is hard.** A wall-clock time is the program's work *plus* everything else:
- process creation;
- the OS scheduler;
- CPU frequency changes (turbo, thermal throttling);
- caches;
- other processes;
- on Windows, a possible antivirus scan of a newly built executable.

A single number therefore means little. The questions are always "compared with what?" and
"how noisy?".

**Protocol used here** (`benchmarking/runner.py`):
1. **Correctness before speed.** Each configuration's output must match the reference before
   it is timed. A fast wrong program is not a result.
2. **Warm-up.** One untimed run per executable. This matters a lot here: the first run of a
   fresh executable took 50–90 ms, against about 5 ms warm (F-014).
3. **Interleaving.** Each repetition round runs all configurations of a benchmark in a new
   random (seeded) order. Slow drifts (heating, background jobs) then hit every configuration
   equally, instead of systematically penalizing the last one.
4. **Robust statistics.**
   - The **median** is robust to occasional outliers. The **minimum** is a lower bound on
     intrinsic run time, since noise only adds.
   - The **coefficient of variation** (CV = σ/μ) is reported for every measurement.
   - Speedups are ratios of medians, aggregated with the **geometric mean**. That is the only
     mean that makes "2× faster on A and 2× slower on B" average to 1×.
5. **Reproducibility.** A whole suite is run twice with different seeds. The spread of the
   medians between runs is the empirical *noise band*, and effects smaller than that are not
   claimed (EXP-003).
6. **Startup baseline.** An empty program is timed with the same protocol, so the fixed cost
   is visible.

**Deterministic proxies.** Counting executed IR instructions (with or without per-opcode weights)
is exact and repeatable, but it is only a *model* of time. Whether that model predicts native
speedups is an empirical question, and EXP-002 measures it with rank correlation (Spearman) and
linear correlation (Pearson). That matters because ML/RL rewards built on a bad proxy would
optimize the wrong thing.

**Two sizes of the same benchmark.** The Python interpreter is about 1,000× slower than native
code. Each benchmark therefore has a small instance (interpreter) and a large one (native) that
differ only in repetition count, so the *relative* effect of an optimization is comparable
across the two.

**Code size.** The `.text` bytes of the LLVM object file for the module, which excludes libc
and the runtime. Executable size would be dominated by the C library.

**In the code:** `src/forgecompile/benchmarking/` (`suite.py`, `measure.py`, `runner.py`,
`report.py`, `stats.py`), `benchmarks/`, `experiments/EXP-002-cost-model/`,
`experiments/EXP-003-fc-vs-llvm/`.

## 13. Why pass ordering is hard (the phase-ordering problem)

**The problem.** An optimizing compiler is a sequence of transformations. Each pass assumes
something about its input, and each pass changes what the next one sees. The order therefore
matters, and no single order is best for every program. This is the *phase-ordering problem*,
studied since the 1970s and still open.

**The four interactions.** Each one is visible in ForgeCompile:
- **Enabling:** pass A creates opportunities for pass B. `copyprop` turns `%i.4 = copy %t13`
  chains into direct uses, and only then can `bce` recognize `%i` as an induction variable
  (EXP-001: `bce` alone does nothing; `copyprop,bce` removes checks).
- **Disabling:** pass A destroys opportunities for pass B. In other compilers, inlining a call
  before constant propagation can hide a constant argument behind a parameter phi.
- **Redundancy:** `constfold` and `sccp` overlap. Running the second after the first usually
  does nothing, but it still costs compile time.
- **Harm:** a valid pass can make the program slower. LICM hoisted code out of a loop that
  never ran (EXP-001, 1.87× worse), and inlining grows code.

**Why not just search?** With |A| = 11 passes and sequences of length T = 12 there are
11¹² ≈ 3·10¹² candidate schedules per program, and evaluating one means compiling and
measuring. Exhaustive search is out. Greedy search ("apply whatever helps most right now") is
myopic: it cannot take a pass with zero immediate gain that enables a large later one.
`OraclePolicy` (`ml/policies.py`) implements exactly this greedy search, using the real cost
of every candidate. It is expensive, and it is an upper bound only for *one-step* policies.

**Why learn?** A learned policy replaces the expensive evaluation of every candidate with a
cheap prediction from program features. An interviewer will ask whether the prediction is good
enough to matter, and whether its overhead is smaller than its benefit. Phases 7–10 measure
both instead of assuming them.

**Why not just use O2?** A fixed pipeline is a hand-tuned guess for "typical" code. A
program-specific schedule can skip useless passes (compile time) and choose orders that suit
the program (run time). The honest null hypothesis is that O2 is already good enough. Every
learned policy here is compared against it.

**In the code:** `optimization/pass_manager.py` (`PRESETS`, `optimize`), `ml/policies.py`,
[ML_GUIDED_OPTIMIZATION.md](ML_GUIDED_OPTIMIZATION.md) §1.

## 14. Pass selection as supervised learning

**Formulation.** The learner sees a state, the current IR summarized by a feature vector
φ(M) ∈ ℝ⁶¹. It outputs a label y ∈ {11 passes, stop}. This is multi-class classification. The
classifier is applied greedily: predict, apply, re-extract features, repeat.

**Where labels come from.** At every recorded state, every pass is applied to a copy, the
result is executed, and the label is the cheapest outcome (or *stop* if nothing improves).
This is supervised learning from an *oracle*: a teacher that is too expensive to run at
compile time but affordable offline. The model learns to imitate the one-step oracle (in RL
language, *imitation learning* of the greedy policy). Its ceiling is the greedy oracle, which
is exactly the limitation that motivates RL (§15).

**Features.** These are cheap static counts (`ml/features.py`): size, opcode mix, CFG shape,
loops, memory, calls, and "opportunity detectors" such as the number of copies or of duplicate
pure expressions. The detectors encode compiler knowledge directly, which raises a legitimate
question: is the model learning anything beyond them? A feature-group ablation (EXP-009)
answers it.

**Why regret instead of accuracy.** Several passes often tie: on many states `constfold` and
`sccp` remove the same instructions. Predicting the "wrong" one of two equally good passes
costs nothing, yet accuracy counts it as an error. Regret measures what the decision actually
loses:

    regret(s) = max_a gain(a, s) − gain(â, s) ≥ 0,   gain(stop, s) = 0

Its mean over held-out states is the primary metric.

**Model classes.**
- **Decision tree:** recursive axis-aligned splits that minimize impurity (Gini). It is
  interpretable but has high variance.
- **Random forest:** averages many trees, each trained on a bootstrap sample with random
  feature subsets. This lowers variance and needs little tuning, which makes it a strong
  default for heterogeneous count features.
- **Gradient boosting:** trees are fitted one after another, each to the gradient of the loss
  with respect to the current ensemble's prediction. It is often the most accurate model on
  tabular data.
- **MLP:** a small neural network. It needs scaled inputs (`log1p`, then standardize), because
  counts span orders of magnitude.

Selection is by **validation** regret. The chosen model is refitted on train + val and scored
once on test.

**Leakage.** States from the same program are near-duplicates. Splitting by state would put
almost the same example in train and test and inflate every metric. The split is therefore by
*program*, with disjoint generator seeds (`ml/data_pipeline.py`), and EXP-007 verifies it.

**In the code:** `ml/dataset.py`, `ml/features.py`, `ml/models.py`, `ml/data_pipeline.py`;
experiment EXP-004.

## 15. Pass scheduling as an MDP

**Markov decision process.** An MDP is a tuple (S, A, P, R, γ):
- states S and actions A;
- a transition distribution P(s′ | s, a);
- a reward R(s, a, s′);
- a discount γ ∈ [0, 1].

A policy π(a | s) induces trajectories. Its *return* is G = Σₜ γᵗ rₜ, and the goal is the
policy with the highest expected return. "Markov" means the next state depends only on the
current state and action, not on the history.

**ForgeCompile's MDP** (full table in [RL_FORMULATION.md](RL_FORMULATION.md)):
- the state is (M, t), the IR module and the step;
- the actions are the 11 passes plus stop;
- transitions are deterministic (applying a pass is a function);
- the reward is the relative cost reduction minus a per-pass penalty λ;
- γ = 1, with a finite horizon T = 12.

**Why rewards telescope.** With rₜ = (C(Mₜ) − C(Mₜ₊₁))/C(M₀) − λ, an episode that applies K
passes returns (C(M₀) − C(M_K))/C(M₀) − λK, because the intermediate states cancel. This is
deliberate reward shaping:
- the objective is "final program quality minus compile cost", so no intermediate step can be
  exploited;
- cycling between states earns nothing;
- normalizing by C(M₀) makes programs of different sizes comparable.

**Why RL rather than the supervised model?** The supervised model imitates the greedy oracle,
which maximizes the *immediate* gain. RL maximizes the *sum* of gains, so it can in principle
learn "apply copyprop now (gain ≈ 0) because bce next gains a lot". Whether such delayed
effects are common enough in this compiler to matter is an empirical question, answered by
EXP-006.

**Partial observability.** The agent sees φ(M), not M. Two different programs can have the
same features, so strictly this is a POMDP. The step counter and the previous action are added
to the observation to recover the information that matters most: the remaining budget, and
whether the last pass did anything.

**In the code:** `rl/env.py` (the MDP as a Gym-style environment). The telescoping property is
tested in `tests/rl/test_rl.py::test_rewards_telescope_to_total_improvement`.

## 16. From Q-learning to Double DQN

**Action values.** Q^π(s, a) is the expected return from taking a in s and following π
afterwards. The optimal Q* satisfies the **Bellman optimality equation**:

    Q*(s, a) = E[ r + γ · max_a′ Q*(s′, a′) ]

Once Q* is known, acting greedily (argmax_a Q*(s, a)) is optimal.

**Q-learning** learns Q* from experience with temporal-difference (TD) updates: Q(s, a) moves
toward the *TD target* y = r + γ max_a′ Q(s′, a′). It is *off-policy*: it learns about the
greedy policy while behaving ε-greedily (a random action with probability ε), which is how it
explores.

**DQN** (Mnih et al., 2015) replaces the table with a neural network Q(s, a; θ) and adds two
stabilizers:
1. **Experience replay.** Transitions are stored in a buffer and minibatches are sampled
   uniformly. This breaks the correlation between consecutive samples and reuses each
   transition many times. That matters here, because an environment step is a compile plus an
   interpreter run.
2. **Target network.** The TD target uses a frozen copy θ⁻, refreshed every N steps. Without
   it the target moves with every update and training can diverge.

**Double DQN** (van Hasselt et al., 2016). The max in the target overestimates, because the
maximum of noisy estimates is biased upward. Double DQN selects the next action with the
online network and evaluates it with the target network:

    y = r + γ · Q(s′, argmax_a′ Q(s′, a′; θ); θ⁻)

**Huber loss** is quadratic for small TD errors and linear for large ones, so rare large errors
do not produce huge gradients.

**Why DQN here and not policy gradients?** The action space is small and discrete (12).
Observations are fixed-length vectors. Environment steps are expensive, which favours reusing
samples. On-policy methods (REINFORCE, PPO) discard their experience after each update.

**Implemented from scratch** in NumPy (`rl/dqn.py`), with no deep-learning framework. The MLP's
backward pass is about 20 lines and is checked against numerical gradients
(`test_mlp_backward_matches_numerical_gradient`). This keeps every line defensible in an
interview and keeps dependencies small (D-007).

**In the code:** `rl/dqn.py` (`MLP`, `Adam`, `DQNAgent.learn`, `train`), `rl/training.py`;
experiment EXP-006, ablations EXP-010.

## 17. Experimental methodology for learned compiler heuristics

**Baselines decide whether a result means anything.** Each one answers a different "is it
just…?" question:
- a random schedule: is any schedule fine?
- the fixed O2 pipeline: is hand-tuning already enough?
- a frequency-ordered list: is it just the label prior?
- the majority class: is it just the most common label?
- the greedy oracle: how much is left to gain?

**Held-out evaluation, three ways.**
1. **Validation** programs choose models, checkpoints and hyperparameters.
2. **Test** programs come from the same generator, are never seen during development, and are
   scored once.
3. **OOD** programs are hand-written kernels, from a different distribution.

Tuning on test, even by looking at it and rerunning, is not allowed. The hypotheses for
EXP-004 onward were written in EXPERIMENTS.md before the full runs.

**Proxy vs target.** Training uses the interpreter cost because it is exact and cheap, but what
matters is native time. EXP-002 measures how well the two correlate, and EXP-008 re-measures
the final schedules natively. *Prediction accuracy is not compiler performance*: a classifier
can be accurate on easy states and wrong on the few that matter. That is why end-to-end
schedule quality is reported separately from regret.

**Seeds and variance.** RL results vary from seed to seed. Several seeds are trained, and every
seed's result is reported, not just the best one.

**Overhead.** A learned scheduler costs feature extraction and inference at compile time. It is
worth it only if (run-time benefit × executions) exceeds (compile-time cost × compilations).
Decision milliseconds are recorded for every policy.

**Negative results are results.** If O2 matches the learned policy, the honest conclusion is
that this action space and workload leave little for learning to find, and it is reported that
way.

**In the code:** `ml/evaluate.py` (end-to-end evaluation with output checks), every
`experiments/EXP-*/run.py`, [EXPERIMENTS.md](EXPERIMENTS.md).
