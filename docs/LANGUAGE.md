# MiniLang Language Specification

MiniLang is a small, statically typed, imperative language. It is designed to be:

- **big enough** to write realistic benchmark kernels (loops, arrays, functions, floating
  point), so that optimizations have real work to do;
- **small enough** that every construct can be lowered, optimized and code-generated
  correctly;
- **fully defined**: no behaviour is undefined. Integer overflow, division by zero,
  out-of-range casts and out-of-bounds indexing all have specified results. This matters
  because ForgeCompile checks optimizations by comparing program outputs (unoptimized vs
  optimized vs native). Undefined behaviour would make those comparisons meaningless.

File extension: `.mini`.

**Status:** syntax (§1–§3) is implemented in Phase 1 (`src/forgecompile/frontend/`).
Static semantics (§4–§6) are enforced from Phase 2. Dynamic semantics (§7) are implemented
by the interpreter (Phase 3) and the LLVM backend (Phase 5).

```rust
// A complete MiniLang program.
fn gcd(a: int, b: int) -> int {
    while b != 0 {
        let t = b;
        b = a % b;
        a = t;
    }
    return a;
}

fn main() -> int {
    let data: [int; 4] = [12, 18, 27, 36];
    for i in 1..4 {
        print(gcd(data[0], data[i]));
    }
    return 0;
}
```

---

## 1. Lexical structure

Implemented by `src/forgecompile/frontend/lexer.py`.

| Element | Rule |
|---------|------|
| Whitespace | space, tab, `\r`, `\n`; separates tokens; otherwise ignored |
| Line comment | `//` to end of line |
| Block comment | `/* ... */`, not nested; unterminated is an error |
| Identifier | `[A-Za-z_][A-Za-z0-9_]*` (ASCII only), not a keyword |
| Integer literal | `[0-9]+`, must be ≤ 2⁶³−1 |
| Float literal | `[0-9]+ '.' [0-9]+ ([eE][+-]?[0-9]+)?` or `[0-9]+ [eE][+-]?[0-9]+` |
| Bool literal | `true`, `false` |

**Keywords:** `fn let if else while for in return break continue true false as int float bool`

**Operators and punctuation:**
`+ - * / % = == != < <= > >= && || ! -> .. ( ) { } [ ] , ; :`

Tokenization uses *maximal munch*: the longest token that matches wins (`<=` is one token).
A `.` belongs to a number only when a digit follows it, so `0..10` is `0`, `..`, `10`.
Literals have no sign. `-5` is unary minus applied to `5`. A consequence is that the most
negative int, −2⁶³, cannot be written as a literal (`-9223372036854775808` overflows when
lexed). Write `-9223372036854775807 - 1` instead.

## 2. Grammar

EBNF. `{ x }` means zero or more, `[ x ]` means optional. Implemented by
`src/forgecompile/frontend/parser.py`.

```ebnf
program     = { function } EOF ;
function    = "fn" IDENT "(" [ param { "," param } [ "," ] ] ")" [ "->" type ] block ;
param       = IDENT ":" type ;
type        = "int" | "float" | "bool" | "[" type ";" INT_LITERAL "]" ;

block       = "{" { statement } "}" ;
statement   = "let" IDENT [ ":" type ] [ "=" expr ] ";"
            | "if" expr block [ "else" ( if_stmt | block ) ]
            | "while" expr block
            | "for" IDENT "in" expr ".." expr block
            | "return" [ expr ] ";"
            | "break" ";"
            | "continue" ";"
            | block
            | expr "=" expr ";"           (* assignment; target must be a name or index *)
            | expr ";" ;

expr        = expr BINOP expr
            | UNOP expr
            | expr "as" type
            | expr "[" expr "]"
            | IDENT "(" [ expr { "," expr } [ "," ] ] ")"
            | "[" [ expr { "," expr } [ "," ] ] "]"
            | "(" expr ")"
            | INT_LITERAL | FLOAT_LITERAL | "true" | "false" | IDENT ;
```

Conditions in `if` and `while` do not need parentheses. Bodies always need braces, which
rules out the "dangling else" ambiguity. A `let` needs a type annotation, an initializer, or
both.

## 3. Operator precedence

From loosest to tightest. The single source of truth is
`src/forgecompile/ast/operators.py`.

| Level | Operators | Associativity |
|-------|-----------|---------------|
| 1 | `\|\|` | left |
| 2 | `&&` | left |
| 3 | `==` `!=` | **non-associative** |
| 4 | `<` `<=` `>` `>=` | **non-associative** |
| 5 | `+` `-` | left |
| 6 | `*` `/` `%` | left |
| 7 | `as` | left (`x as float as int`) |
| 8 | unary `-` `!` | prefix |
| 9 | call `f(..)`, index `a[i]` | postfix |

Comparisons are non-associative: `a < b < c` is a syntax error ("comparison operators
cannot be chained"), because its C meaning, `(a < b) < c`, is almost never what was intended.
Examples: `-a[i]` is `-(a[i])`. `-x as float` is `(-x) as float`. `a * b as float` is
`a * (b as float)`.

## 4. Types *(enforced from Phase 2)*

| Type | Values | Size |
|------|--------|------|
| `int` | signed integers −2⁶³ … 2⁶³−1 | 64-bit |
| `float` | IEEE-754 binary64 | 64-bit |
| `bool` | `true`, `false` | — |
| `[T; N]` | N elements of type T (T may be an array: `[[float; 3]; 3]`); N ≥ 1, a literal | N × size(T) |

Functions without `-> T` return nothing (internally type `void`). `void` is not a value type:
no variable, parameter or array element can have it.

**No implicit conversions.** `1 + 2.0` is a type error; write `1 as float + 2.0`. This keeps
the type checker simple and makes every conversion visible in the IR.

**Arrays are not first-class values.** Arrays can be declared, indexed, element-assigned and
passed to functions, which receive them **by reference** (the callee can modify the caller's
array, as `examples/bubble_sort.mini` does). Arrays cannot be assigned as a whole, returned,
compared or printed. Parameter array types must match exactly, size included.

## 5. Typing rules *(enforced from Phase 2)*

| Construct | Rule |
|-----------|------|
| `+ - * /` | both operands `int`, or both `float`; result has the same type |
| `%` | both `int` or both `float` |
| `< <= > >=` | both `int` or both `float`; result `bool` |
| `== !=` | both operands of the same scalar type; result `bool` |
| `&& \|\| !` | `bool` operands; result `bool` |
| unary `-` | `int` or `float` |
| `e as T` | `e` and `T` both scalar (any of int/float/bool to any of int/float/bool) |
| `a[i]` | `a` is an array, `i` is `int`; result is the element type |
| `[e1, ..., en]` | all elements of the same type `T`; type `[T; n]`; only allowed as a `let` initializer |
| `f(args)` | `f` is declared; argument count and types match exactly |
| `print(e)` | built-in; one scalar argument; returns nothing |
| `if c` / `while c` | `c` is `bool` |
| `for i in a..b` | `a`, `b` are `int`; `i` is a fresh `int`, read-only within the body |
| `let x: T = e` | `e` has type `T`; without `: T` the type of `e` is used |
| `x = e` | `x` is a mutable scalar variable or an array element, with type equal to type(e) |
| `return e` | type(e) equals the function's return type; `return;` only in void functions |
| expression statement | must be a call (`1 + 2;` is an error: the result would be discarded) |

## 6. Names and scopes *(enforced from Phase 2)*

- Functions live in one global namespace and may be called before their definition, which
  allows mutual recursion. There is no overloading. `print` is reserved.
- Variables are **block-scoped**. A declaration is visible from its `let` to the end of the
  enclosing block.
- Redeclaring a name in the *same* scope is an error. Shadowing a name from an *enclosing*
  scope is allowed.
- Parameters share a scope with the function body's top level, so `let n = ...;` in a function
  with parameter `n` is a redeclaration error.
- A `for` loop variable is scoped to the loop body and cannot be assigned. The loop is
  therefore always a simple counted loop, which later loop analyses can rely on.
- A non-void function must not be able to reach the end of its body without returning
  ("missing return" is checked over all control-flow paths).
- `break` and `continue` are only valid inside a loop.
- `main` must exist, take no parameters, and return `int` or nothing.

## 7. Dynamic semantics *(interpreter Phase 3, native code Phase 5)*

**Evaluation order:** left to right. Binary operands, call arguments and array indices are
evaluated left to right. `&&` and `||` short-circuit.

**Integers:** `+ - *` and unary `-` wrap around modulo 2⁶⁴ (two's complement). They never
trap. `/` truncates toward zero and `%` takes the sign of the dividend (C semantics, matching
LLVM `sdiv`/`srem`). Python's `//` floors instead, and the interpreter must not use it.
Division or remainder by zero is a **runtime error**. `INT_MIN / -1` evaluates to `INT_MIN`
and `INT_MIN % -1` to `0` (wrap-around, no trap).

**Floats:** IEEE-754 binary64 with round-to-nearest-even. Division by zero gives ±inf or NaN.
It is not an error. `%` is C `fmod`.

**Casts:**

| From → to | Result |
|-----------|--------|
| int → float | nearest representable double |
| float → int | truncate toward zero; **saturates** at INT_MIN/INT_MAX; NaN → 0 (Rust semantics; LLVM `llvm.fptosi.sat`) |
| bool → int / float | `true` → 1 / 1.0, `false` → 0 / 0.0 |
| int / float → bool | `x != 0` / `x != 0.0` (NaN → `true`) |

**Arrays:** zero-initialized when declared without an initializer (scalars too: `let x: int;`
is 0). Indexing out of range is a **runtime error**: arrays are bounds-checked.

**Runtime errors** print `runtime error: <message>` to stderr and terminate the program with
exit status **101**.

**`print`:** writes its argument and a newline to stdout. `int` is printed in decimal. `bool`
is printed as `true` or `false`. `float` is printed with exactly six digits after the decimal
point (C `printf("%.6f")`), and `inf`, `-inf` and `nan` are spelled that way.

**Program result:** execution starts at `main`. The process exit status is main's return
value modulo 256 (0 for a void `main`). The *observable behaviour* of a program is
`(stdout, exit status)`. Optimizations must preserve exactly that.

## 8. Not in MiniLang (deliberately)

- **Strings, structs, pointers, heap allocation, global variables.** Not needed to express
  the benchmark kernels. Each would complicate alias analysis.
- **Compound assignment (`+=`) and `++`.** Purely syntactic sugar.
- **Implicit conversions and overloading.** These complicate type checking without adding
  anything to the optimization story.
- **Bitwise operators.** May be added if a benchmark needs them.
