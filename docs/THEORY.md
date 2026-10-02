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
| 6. Intermediate representations | 3 | ⏳ |
| 7. Control-flow graphs and basic blocks | 3 | ⏳ |
| 8. Dominance and SSA | 3 | ⏳ |
| 9. Data-flow analysis (lattices, fixpoints) | 4 | ⏳ |
| 10. Why each optimization is valid | 4 | ⏳ |
| 11. LLVM IR | 5 | ⏳ |
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
