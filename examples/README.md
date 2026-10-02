# Examples

Small MiniLang programs that exercise the whole language. They double as end-to-end test
inputs: every file here must parse (Phase 1), type-check (Phase 2), and from Phase 3 on produce
the same output when interpreted, optimized and compiled natively.

| File | Exercises |
|------|-----------|
| `fibonacci.mini` | recursion, while loops, for-range |
| `gcd.mini` | `%`, `/`, recursion, bool printing |
| `primes.mini` | bool arrays, nested loops, `break` / `continue` |
| `bubble_sort.mini` | array literal, arrays passed by reference, early `return` |
| `matmul.mini` | 2-D float arrays, casts (`as`), triple loop nest |
| `newton_sqrt.mini` | float arithmetic, `&&`, scientific literals |
| `collatz.mini` | data-dependent loops, nested `if/else` |

```bash
uv run forgecompile parse examples/gcd.mini            # AST
uv run forgecompile parse --format examples/gcd.mini   # canonical source
```
