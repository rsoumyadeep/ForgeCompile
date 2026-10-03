# ForgeCompile IR

The ForgeCompile IR is a typed, register-based three-address code organised into basic
blocks. It is the level at which all of ForgeCompile's own optimizations and the ML/RL pass
scheduler operate. This document covers the design, the instruction set, the textual format,
the verifier, the interpreter, CFG/dominance, and SSA.

Code: `src/forgecompile/ir/` (data structures, printer, parser, verifier, interpreter, SSA),
`src/forgecompile/lowering.py` (AST → IR), and `src/forgecompile/analysis/` (CFG, dominators).

```bash
uv run forgecompile ir --no-ssa examples/gcd.mini   # IR straight from lowering
uv run forgecompile ir examples/gcd.mini            # SSA form (the canonical form)
uv run forgecompile run --stats examples/gcd.mini   # execute + dynamic instruction counts
```

## 1. Why a separate IR

MiniLang's AST is the wrong shape for optimization:
- control flow is implicit in nesting;
- expressions nest arbitrarily deep;
- a variable name can denote different storage at different points (shadowing).

LLVM IR is the right shape, but optimizing directly in LLVM would hand the project's core work
to LLVM. ForgeCompile therefore has its own IR between the two, which:

- makes **control flow explicit**: basic blocks plus terminators form a CFG;
- makes **every intermediate value named**: three-address code (`%t3 = add %total, %t2`), so
  passes can reason about individual computations;
- has **machine-level types** only (`i64`, `f64`, `i1`, `ptr`): arrays are gone, and so is
  MiniLang-level typing;
- is **small enough** to analyse and transform with readable passes (about 30 opcodes);
- maps almost **one-to-one onto LLVM IR** (Phase 5), so lowering to LLVM is mechanical and
  does not hide optimizations.

## 2. Structure

```
Module ─ functions: name -> Function
Function ─ name, params: [Register], return_type, blocks: [BasicBlock]   (blocks[0] = entry)
BasicBlock ─ label, instructions: [phi..., body..., terminator]
Instruction ─ opcode, dest: Register | None, operands: [Value], + opcode-specific attributes
Value ─ Register (virtual register) | Constant (typed immediate) | Undef
```

- **Registers** are compared by identity, and the name is only for printing. Before SSA a
  register may be assigned many times, one register per source variable. After SSA it is
  assigned exactly once.
- **Predecessors are computed, not stored** (`analysis/cfg.py`). A pass that rewires a branch
  cannot leave stale predecessor lists behind.
- Every instruction records its `block`. The verifier checks this back-pointer.

## 3. Instruction set

| Group | Opcodes | Notes |
|-------|---------|-------|
| Integer | `add sub mul sdiv srem neg` | wrap-around; `sdiv`/`srem` truncate (C) and **trap on zero** |
| Float | `fadd fsub fmul fdiv frem fneg` | IEEE-754; `frem` is C `fmod`; never traps |
| Compare | `icmp <pred>`, `fcmp <pred>` | preds `eq ne lt le gt ge`; ints signed; floats ordered except `ne` (unordered) |
| Boolean | `not` | `&&`/`\|\|` are lowered to control flow, not to instructions |
| Convert | `sitofp fptosi zext copy` | `fptosi` saturates (NaN → 0); `zext` is i1 → i64 |
| Memory | `alloca load store ptradd memzero boundscheck` | see §4 |
| Calls / IO | `call @f(...)`, `print v` | `print` is a built-in effect |
| SSA | `phi [v, block], ...` | only at block start |
| Terminators | `jump`, `br c, t, f`, `ret [v]`, `unreachable` | exactly one, last in the block |

**Effect classification** (`Opcode.may_trap/writes_memory/reads_memory/is_pure`). Phase 4
depends on it:

| Class | Opcodes | Consequence for optimization |
|-------|---------|------------------------------|
| may trap | `sdiv srem boundscheck call` | cannot be deleted when unused unless proven not to trap |
| writes memory | `store memzero call` | orders other memory operations |
| reads memory | `load call` | cannot be CSE'd across a store without alias information |
| pure | arithmetic (except `sdiv/srem`), compares, conversions, `copy`, `ptradd`, `phi` | delete if unused, CSE, hoist freely |

The `sdiv` row is a deliberate subtlety. An unused `x / y` *cannot* be removed by
dead-code elimination, because if `y == 0` the original program traps and the "optimized"
one would not. This follows from MiniLang having no undefined behaviour (DECISIONS D-010).
C compilers may delete such a division, because dividing by zero is UB in C.

## 4. Memory model

- Arrays are **flat, zero-filled buffers** of scalars. `alloca f64, 9` returns a `ptr`.
  Lowering places every `alloca` at the top of the entry block, so a loop that declares an
  array does not grow the stack. It then emits `memzero` *at the declaration site*, because
  a declaration inside a loop must re-zero its array on each iteration.
- `m[i][j]` on `[[T; C]; R]` becomes `boundscheck i, R; boundscheck j, C;
  load m[i*C + j]`. Each dimension is checked separately, as the language requires.
- `load p[k]` and `store p[k], v` index in **elements**. `ptradd p, k` makes a derived
  pointer, used to pass a row `m[i]` by reference.
- Bounds checks are explicit instructions, not part of `load`/`store`. This keeps memory
  access simple and makes bounds-check elimination a visible, measurable optimization
  opportunity.
- There is no alias analysis yet. Two array parameters may alias, so passes treat memory
  conservatively.

## 5. Textual format

```
func @sum(%xs: ptr) -> i64 {
entry:
    %total: i64 = copy 0
    %i: i64 = copy 0
    jump for.cond
for.cond:
    %t1: i1 = icmp lt %i, 4
    br %t1, for.body, for.end
for.body:
    boundscheck %i, 4
    %t2: i64 = load %xs[%i]
    %t3: i64 = add %total, %t2
    %total: i64 = copy %t3
    jump for.latch
for.latch:
    %t4: i64 = add %i, 1
    %i: i64 = copy %t4
    jump for.cond
for.end:
    ret %total
}
```

Every definition is annotated with its type. Constants are typed by their spelling:
- `4` is `i64`;
- `4.0`, `1.0e+20`, `nan` and `inf` are `f64`;
- `true`/`false` are `i1`;
- `undef.i64` is an undefined value of type `i64`.

`ir/parser.py` parses this format back. Tests check that `print → parse → print` is the
identity for every example program, both before and after SSA. Phase 4 pass tests are
written directly in this format.

## 6. Verifier (`ir/verify.py`)

The verifier runs after lowering, after SSA construction and, from Phase 4, after every pass.

- **Structure:** blocks are non-empty, there is exactly one terminator and it is last, phis
  come first, the entry block has no predecessors and no phis, and branch targets belong to
  the function.
- **Phis:** incoming blocks are exactly the predecessors, each listed once.
- **Types:** operand and result types per opcode, call signatures against the callee, and
  `ret` against the function's return type.
- **SSA mode:** single definition per register, every use is defined, and every definition
  dominates its uses. A phi operand counts as a use at the end of its incoming block.

## 7. Interpreter and cost model (`ir/interpreter.py`)

- The interpreter executes any IR, pre- or post-SSA. Phis are executed as a **parallel copy**
  on the incoming edge; `test_phis_are_parallel_copies` checks the swap case.
- It uses an explicit frame stack, so MiniLang recursion depth is not limited by Python's
  recursion limit. 5,000 levels are tested.
- It counts every executed instruction by opcode and computes a weighted **cost**
  (`DEFAULT_COST_MODEL`, rough x86-64 latencies). This is the deterministic optimization
  signal planned in DECISIONS D-006. *Whether the cost correlates with native runtime is an
  open question that Phase 6 will measure.* *(Update, 2026-10-03: EXP-002 measured a pooled Spearman
  correlation of only 0.29 with native time at LLVM -O0, and the weights add nothing over plain
  instruction counts. See RESULTS.md.)*
- It reports compiler bugs as `InterpreterError`, distinct from MiniLang runtime traps:
  - an observable use of `undef`;
  - reading an unassigned register;
  - memory access outside an allocation (for example after a wrongly removed bounds check);
  - reaching `unreachable`.

## 8. Control-flow graph and dominance (`analysis/`)

- `cfg.py`: `predecessors`, `reverse_postorder` (iterative DFS),
  `remove_unreachable_blocks` (fixes phis), `is_critical_edge`, `split_edge`.
- `dominators.py`: dominator tree by Cooper–Harvey–Kennedy, O(1) `dominates` via DFS
  intervals, and dominance frontiers by the CHK "runner" algorithm. The tests check
  dominance against its *definition* (A dom B ⇔ B is unreachable without A) on 40 random
  CFGs, including an irreducible one.

## 9. SSA form

### Why SSA (and why not "just because")

SSA is adopted because it makes **this project's** Phase 4 passes simpler and more reliable:

| Pass | Without SSA | With SSA |
|------|-------------|----------|
| constant propagation | per-variable, per-program-point data-flow sets | one lattice value per register (SCCP) |
| copy propagation | needs reaching-definitions analysis | replace all uses of `%a = copy %b` with `%b` |
| CSE / GVN | must prove no redefinition between the two expressions | registers never change: equal operands imply an equal value |
| DCE | needs liveness | a pure instruction whose register has no uses is dead |

There is a second, practical reason: LLVM IR is SSA, so Phase 5 emits SSA directly.

### Phi nodes

At a join point a variable may have different values depending on the incoming edge.
`%total.2 = phi [%total.1, entry], [%total.3, for.latch]` selects `%total.1` when control
arrives from `entry` and `%total.3` when it arrives from the latch. This is what lets every
register have a single static definition.

### Construction strategy (`ir/ssa.py`)

Cytron et al. (1991), with Briggs's semi-pruning:

1. *Variables* are registers with more than one definition. Lowering creates one register
   per source variable, and every assignment is a `copy` into it. A reassigned parameter is
   a variable whose first definition is the incoming argument.
2. *Global names* are variables used in some block before being defined there. Only these
   can need phis.
3. *Phi placement* happens at the **iterated dominance frontier** of each global variable's
   definition blocks. DF(B) is exactly where B's definition stops dominating, i.e. where it
   can meet another definition.
4. *Renaming* walks the dominator tree with a stack of versions per variable, producing
   `%x.1`, `%x.2`, and so on. A path with no definition supplies `undef`.

The `sum` function above in SSA form:

```
for.cond:
    %total.2: i64 = phi [%total.1, entry], [%total.3, for.latch]
    %i.2: i64 = phi [%i.1, entry], [%i.3, for.latch]
    %t1: i1 = icmp lt %i.2, 4
    br %t1, for.body, for.end
for.body:
    boundscheck %i.2, 4
    %t2: i64 = load %xs[%i.2]
    %t3: i64 = add %total.2, %t2
    %total.3: i64 = copy %t3
    ...
```

### Limitations and deliberate omissions

- **Copies remain.** SSA construction only renames. `%total.3 = copy %t3` is removed by copy
  propagation in Phase 4. Keeping the two separate keeps each transformation simple and
  separately testable.
- **Semi-pruned, not pruned.** Some dead phis remain, for example a loop-local variable's
  phi at the loop header, whose entry input is `undef`. DCE removes them. Fully pruned SSA
  would need liveness first.
- **Only scalar variables are in SSA.** Array memory stays in memory (load/store). There is
  no "memory SSA".
- **No out-of-SSA translation** (DECISIONS D-017). Nothing in the pipeline consumes non-SSA
  IR after construction, and LLVM accepts phis directly. Implementing it anyway would be
  complexity without a consumer. If a register allocator or a non-SSA backend were ever
  added, the standard approach is to split critical edges (`split_edge` already exists) and
  sequentialize the parallel copies.
