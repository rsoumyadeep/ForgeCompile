"""SSA construction (Cytron et al. 1991, with Briggs' semi-pruning).

**Why SSA.** In Static Single Assignment form every register has exactly one
definition. A use therefore names exactly one definition, so def-use chains
are implicit and many analyses become simple and sparse: constant
propagation, copy propagation, CSE/GVN and DCE all work per value instead of
per (variable, program point). LLVM IR is SSA too, so the backend can emit
our SSA directly (see docs/IR.md for the full argument).

**Input.** Pre-SSA IR from lowering, where each source variable is a register
assigned by several ``copy`` instructions.

**Algorithm.**

1. *Variables* are registers with more than one definition. A parameter that
   is reassigned counts as a variable, with the incoming argument as its first
   definition.
2. *Semi-pruning (Briggs).* Only variables that are live across a block
   boundary ("global names": used in some block before being defined there)
   need phis. This skips most of the dead phis that minimal SSA would insert.
3. *Phi insertion.* For each global variable v, place ``phi`` nodes at the
   iterated dominance frontier of v's definition blocks. A phi is itself a new
   definition, hence the worklist.
4. *Renaming.* Walk the dominator tree keeping a stack of current versions
   per variable. At each definition, push a fresh register (``%x.1``, ``%x.2``,
   ...). Rewrite each use to the top of its stack. Fill in successor phi
   inputs for this edge. Pop on the way out. A variable with no reaching
   definition on some path gets ``undef``, e.g. a loop-local variable at the
   loop header. Valid programs never observe it, and the IR interpreter checks
   that.

**Complexity.** Dominators plus frontiers are near-linear in practice. Phi
insertion is O(defs * |DF|). Renaming is linear in program size.

We deliberately do **not** implement out-of-SSA translation. Its usual consumer
is a register allocator or a non-SSA backend, and LLVM consumes phis directly
(DECISIONS D-017).
"""

from __future__ import annotations

from collections import defaultdict

from forgecompile.analysis.dominators import DominatorTree
from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import PhiInst
from forgecompile.ir.values import Register, Undef, Value


def _definition_sites(fn: Function) -> dict[Register, list[BasicBlock]]:
    sites: dict[Register, list[BasicBlock]] = defaultdict(list)
    for param in fn.params:
        sites[param].append(fn.entry)
    for block in fn.blocks:
        for inst in block.instructions:
            if inst.dest is not None:
                sites[inst.dest].append(block)
    return sites


def _global_names(fn: Function, variables: set[Register]) -> set[Register]:
    """Variables used in some block before any definition in that block (Briggs)."""
    result: set[Register] = set()
    for block in fn.blocks:
        defined_here: set[Register] = set()
        for inst in block.instructions:
            for reg in inst.registers_used():
                if reg in variables and reg not in defined_here:
                    result.add(reg)
            if inst.dest is not None:
                defined_here.add(inst.dest)
    return result


def construct_ssa(fn: Function) -> int:
    """Convert ``fn`` to SSA form in place. Returns the number of phis inserted."""
    sites = _definition_sites(fn)
    variables = {reg for reg, blocks in sites.items() if len(blocks) > 1}
    if not variables:
        return 0
    domtree = DominatorTree(fn)
    frontiers = domtree.frontiers()
    preds = domtree.preds

    # ---- phi insertion at iterated dominance frontiers
    phi_variable: dict[PhiInst, Register] = {}
    inserted = 0
    for var in sorted(_global_names(fn, variables), key=lambda r: r.name):  # deterministic
        has_phi: set[BasicBlock] = set()
        worklist = list(dict.fromkeys(sites[var]))
        queued = set(worklist)
        while worklist:
            block = worklist.pop()
            for frontier in sorted(frontiers.get(block, ()), key=lambda b: b.label):
                if frontier in has_phi:
                    continue
                phi = PhiInst(var, [(Undef(var.type), p) for p in preds[frontier]])
                frontier.insert(0, phi)
                phi_variable[phi] = var
                has_phi.add(frontier)
                inserted += 1
                if frontier not in queued:
                    queued.add(frontier)
                    worklist.append(frontier)

    # ---- renaming along the dominator tree (iterative DFS)
    stacks: dict[Register, list[Value]] = {var: [] for var in variables}
    for param in fn.params:
        if param in variables:
            stacks[param].append(param)  # version 0 = the incoming argument

    def current(var: Register) -> Value:
        stack = stacks[var]
        return stack[-1] if stack else Undef(var.type)

    def rename_block(block: BasicBlock) -> list[Register]:
        pushed: list[Register] = []
        for inst in block.instructions:
            if not isinstance(inst, PhiInst) or inst not in phi_variable:
                for i, operand in enumerate(inst.operands):
                    if isinstance(operand, Register) and operand in variables:
                        inst.operands[i] = current(operand)
            dest = inst.dest
            var = phi_variable.get(inst) if isinstance(inst, PhiInst) else dest
            if var is not None and var in variables:
                version = fn.new_register(var.name, var.type)
                inst.dest = version
                stacks[var].append(version)
                pushed.append(var)
        for succ in block.successors:
            for phi in succ.phis():
                var = phi_variable.get(phi)
                if var is not None:
                    for i, pred in enumerate(phi.blocks):
                        if pred is block:
                            phi.operands[i] = current(var)
        return pushed

    work: list[tuple[BasicBlock, list[Register] | None]] = [(fn.entry, None)]
    while work:
        block, pushed = work.pop()
        if pushed is not None:  # leaving the subtree: pop this block's versions
            for var in pushed:
                stacks[var].pop()
            continue
        pushed_here = rename_block(block)
        work.append((block, pushed_here))
        work.extend((child, None) for child in reversed(domtree.children[block]))
    return inserted


def construct_ssa_module(module: Module) -> int:
    return sum(construct_ssa(fn) for fn in module.functions.values())
