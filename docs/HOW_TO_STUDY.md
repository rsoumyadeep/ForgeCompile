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
| 6 | IR | 3 | ⏳ |
| 7 | CFG | 3 | ⏳ |
| 8 | SSA | 3 | ⏳ |
| 9 | Data-flow analysis | 4 | ⏳ |
| 10 | Classical optimizations | 4 | ⏳ |
| 11 | LLVM | 5 | ⏳ |
| 12 | Benchmarking | 6 | ⏳ |
| 13 | ML for compiler optimization | 7 | ⏳ |
| 14 | RL formulation | 8 | ⏳ |
| 15 | RL implementation | 9 | ⏳ |
| 16 | Experimental methodology | 10 | ⏳ |
| 17 | Failure analysis | all | ⏳ (read [FAILURES.md](FAILURES.md)) |
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
