# Compiler and ML Theory, Connected to the Code

Each section explains a concept from first principles and then points to the code that
implements it. Sections are written when the corresponding code exists, so that no section is
textbook material without a code link.

| Section | Phase | Status |
|---------|-------|--------|
| 1. What a compiler is, and why it is split into phases | 0 | ✅ below |
| 2. Lexing | 1 | ⏳ |
| 3. Grammars and parsing (recursive descent, Pratt) | 1 | ⏳ |
| 4. The AST | 1 | ⏳ |
| 5. Semantic analysis: symbol tables, scopes, types | 2 | ⏳ |
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
