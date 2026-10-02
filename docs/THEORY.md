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
| 12. Measuring performance | 6 | ⏳ |
| 13. Why pass ordering is hard (the phase-ordering problem) | 7 | ⏳ |
| 14. Pass scheduling as an MDP | 8 | ⏳ |

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
