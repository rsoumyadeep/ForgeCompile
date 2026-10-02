"""cse: common subexpression elimination by dominator-scoped value numbering.

**Motivation.** The same pure computation often appears more than once. Index
arithmetic is the typical case: ``a[i][k] * b[k][j]`` and its neighbours
recompute ``i * 3`` many times. Computing it once and reusing the register
saves work.

**Transformation.** Walk the dominator tree in preorder, keeping a scoped hash
table from *expression keys* to registers::

    key = (opcode, predicate, operands)     # operands sorted for commutative ops

If an instruction's key is already in the table, an identical computation
*dominates* it. Its uses are replaced by the earlier register and it is
deleted. Otherwise its key is recorded. Table entries are popped when the walk
leaves a dominator subtree, so a value computed in one branch of an ``if`` is
never reused in the other branch, where it was not computed.

**Correctness.**
- Only *pure* instructions are numbered: no side effects and no memory reads,
  so the same operands always give the same result.
- In SSA, operands cannot be redefined between the two computations.
- The earlier instruction dominates the later one, so the reused register is
  defined on every path.
- Loads are excluded because a store in between could change memory. That
  would need alias analysis, which ForgeCompile does not have yet.

**Complexity.** O(n) expected (hash table operations along one tree walk).

**Limitation.** This is not full GVN. It does not discover that ``phi [a, x], [a, y]``
equals ``a`` (copyprop does that), and it does not number loads.
"""

from __future__ import annotations

from forgecompile.analysis.dominators import DominatorTree
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import COMMUTATIVE, CompareInst, Instruction, Opcode
from forgecompile.ir.values import Constant, Register, Value
from forgecompile.optimization.pass_manager import FunctionPass, PassResult, register_pass
from forgecompile.optimization.utils import Substitution, delete_instruction


def _operand_key(value: Value) -> tuple[int, object]:
    # Registers by identity, constants by value. The leading tag makes keys orderable.
    if isinstance(value, Register):
        return (0, id(value))
    if isinstance(value, Constant):
        return (1, hash(value))
    return (2, repr(value))


def expression_key(inst: Instruction) -> tuple[object, ...] | None:
    if not inst.opcode.is_pure or inst.opcode in (Opcode.PHI, Opcode.COPY):
        return None
    operands: list[Value] = list(inst.operands)
    if inst.opcode in COMMUTATIVE:
        operands.sort(key=_operand_key)
    pred = inst.pred if isinstance(inst, CompareInst) else None
    return (inst.opcode, pred, *operands)


@register_pass
class CommonSubexpressionElimination(FunctionPass):
    name = "cse"
    description = "reuse identical pure computations that dominate each other"

    def run_on_function(self, fn: Function, module: Module) -> PassResult:
        result = PassResult()
        domtree = DominatorTree(fn)
        subst = Substitution()
        table: dict[tuple[object, ...], Register] = {}
        # Iterative preorder walk with explicit scope undo lists.
        stack: list[tuple[BasicBlock, list[tuple[object, ...]] | None]] = [(fn.entry, None)]
        while stack:
            block, added = stack.pop()
            if added is not None:
                for stale in added:
                    del table[stale]
                continue
            added_here: list[tuple[object, ...]] = []
            for inst in list(block.instructions):
                for i, op in enumerate(inst.operands):
                    inst.operands[i] = subst.resolve(op)
                key = expression_key(inst)
                if key is None or inst.dest is None:
                    continue
                existing = table.get(key)
                if existing is not None:
                    subst.add(inst.dest, existing)
                    delete_instruction(inst)
                    result.stats["eliminated"] += 1
                else:
                    table[key] = inst.dest
                    added_here.append(key)
            stack.append((block, added_here))
            stack.extend((child, None) for child in reversed(domtree.children[block]))
        subst.apply(fn)
        result.changed = bool(result.stats)
        return result
