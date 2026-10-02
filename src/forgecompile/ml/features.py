"""Static IR features: a fixed-length numeric description of a module.

The ML/RL schedulers see the program only through this vector. Features are
grouped so that ablations can remove a whole group ("without loop features")
and measure what it contributed (Phase 10). All features are cheap static
counts; nothing here executes the program.

=================  ===============================================================
group              features
=================  ===============================================================
size               functions, blocks, instructions, phis
opcodes            fraction of instructions per opcode (normalized histogram)
cfg                edges, conditional branches, critical edges, cyclomatic
                   complexity, max dominator-tree depth
loops              loops, max nesting depth, fraction of instructions inside loops,
                   basic induction variables
memory             loads, stores, allocas, bounds checks, fraction of bounds
                   checks on a plain induction variable
calls              call sites, inlinable call sites, recursive functions
opportunities      copies, trivial phis, constant-operand instructions, unused
                   removable instructions, duplicate pure expressions, loop-
                   invariant speculatable instructions, IV * constant multiplies,
                   constant branches
=================  ===============================================================

The "opportunities" group is the most pass-specific: each counter is
essentially a cheap detector for a pass's precondition. Including it is a
deliberate design choice. It is the kind of feature a compiler engineer would
hand-craft, and the ablation in Phase 10 measures how much the models depend
on it.
"""

from __future__ import annotations

from collections import Counter

from forgecompile.analysis.cfg import predecessors
from forgecompile.analysis.dominators import DominatorTree
from forgecompile.analysis.loops import basic_induction_variables, find_loops, preheader
from forgecompile.ir.function import Function, Module
from forgecompile.ir.instructions import BoundsCheckInst, BranchInst, CallInst, Opcode, PhiInst
from forgecompile.ir.values import Constant, Register
from forgecompile.optimization.passes.cse import expression_key
from forgecompile.optimization.passes.inline import INLINE_THRESHOLD, recursive_functions
from forgecompile.optimization.utils import (
    compute_uses,
    instruction_count,
    is_removable_if_unused,
    is_speculatable,
    trivial_phi_value,
)

OPCODE_FEATURES = [f"op_{op.value}" for op in Opcode]

FEATURE_GROUPS: dict[str, list[str]] = {
    "size": ["n_functions", "n_blocks", "n_instructions", "n_phis"],
    "opcodes": OPCODE_FEATURES,
    "cfg": ["n_edges", "n_cond_branches", "n_critical_edges", "cyclomatic", "max_domtree_depth"],
    "loops": ["n_loops", "max_loop_depth", "frac_insts_in_loops", "n_basic_ivs"],
    "memory": ["n_loads", "n_stores", "n_allocas", "n_boundschecks", "frac_boundschecks_on_iv"],
    "calls": ["n_calls", "n_inlinable_calls", "n_recursive_functions"],
    "opportunities": [
        "n_copies",
        "n_trivial_phis",
        "n_constant_operand_insts",
        "n_unused_removable",
        "n_duplicate_expressions",
        "n_loop_invariant",
        "n_iv_multiplies",
        "n_constant_branches",
    ],
}
FEATURE_NAMES: list[str] = [name for group in FEATURE_GROUPS.values() for name in group]


def _domtree_depth(tree: DominatorTree) -> int:
    depth = {tree.fn.entry: 0}
    for block in tree.preorder():
        parent = tree.idom[block]
        if parent is not None:
            depth[block] = depth[parent] + 1
    return max(depth.values(), default=0)


def _function_features(
    fn: Function, module: Module, recursive: set[str], counts: Counter[str]
) -> None:
    preds = predecessors(fn)
    tree = DominatorTree(fn)
    loops = find_loops(fn, tree)
    uses = compute_uses(fn)
    n_insts = instruction_count(fn)

    counts["n_functions"] += 1
    counts["n_blocks"] += len(fn.blocks)
    counts["n_instructions"] += n_insts
    edges = sum(len(b.successors) for b in fn.blocks)
    counts["n_edges"] += edges
    counts["cyclomatic"] += edges - len(fn.blocks) + 2
    counts["max_domtree_depth"] = max(counts["max_domtree_depth"], _domtree_depth(tree))
    for block in fn.blocks:
        if len(block.successors) > 1:
            counts["n_cond_branches"] += 1
            for succ in block.successors:
                if len(preds[succ]) > 1:
                    counts["n_critical_edges"] += 1

    # Loops and induction variables.
    counts["n_loops"] += len(loops)
    counts["max_loop_depth"] = max(
        counts["max_loop_depth"], max((lp.depth for lp in loops), default=0)
    )
    in_loop_blocks = set().union(*(lp.blocks for lp in loops)) if loops else set()
    counts["insts_in_loops"] += sum(len(b.instructions) for b in in_loop_blocks)
    iv_registers: set[Register] = set()
    for loop in loops:
        pre = preheader(loop, preds)
        if pre is None:
            continue
        for iv in basic_induction_variables(loop, pre):
            assert iv.phi.dest is not None
            iv_registers.add(iv.phi.dest)
    counts["n_basic_ivs"] += len(iv_registers)

    # Registers defined inside each loop, and each block's innermost loop (loops are
    # sorted innermost first, so the first loop containing a block is its innermost).
    loop_defs_of = [
        {i.dest for b in loop.blocks for i in b.instructions if i.dest is not None}
        for loop in loops
    ]
    innermost: dict[object, set[Register]] = {}
    for loop, defs in zip(loops, loop_defs_of, strict=True):
        for block in loop.blocks:
            innermost.setdefault(block, defs)

    # Instruction-level counts.
    seen_keys: set[tuple[object, ...]] = set()
    for block in fn.blocks:
        loop_defs: set[Register] = innermost.get(block, set())
        for inst in block.instructions:
            op = inst.opcode
            counts[f"op_{op.value}"] += 1
            if isinstance(inst, PhiInst):
                counts["n_phis"] += 1
                if trivial_phi_value(inst) is not None:
                    counts["n_trivial_phis"] += 1
            if op is Opcode.COPY:
                counts["n_copies"] += 1
            elif op is Opcode.LOAD:
                counts["n_loads"] += 1
            elif op is Opcode.STORE:
                counts["n_stores"] += 1
            elif op is Opcode.ALLOCA:
                counts["n_allocas"] += 1
            if isinstance(inst, BoundsCheckInst):
                counts["n_boundschecks"] += 1
                if inst.index in iv_registers:
                    counts["boundschecks_on_iv"] += 1
            if isinstance(inst, CallInst):
                counts["n_calls"] += 1
                callee = module.functions.get(inst.callee)
                if (
                    callee is not None
                    and callee.name not in recursive
                    and instruction_count(callee) <= INLINE_THRESHOLD
                ):
                    counts["n_inlinable_calls"] += 1
            if isinstance(inst, BranchInst) and isinstance(inst.cond, Constant):
                counts["n_constant_branches"] += 1
            foldable_kind = op not in (Opcode.PHI, Opcode.STORE, Opcode.CALL, Opcode.PRINT)
            if (
                inst.operands
                and foldable_kind
                and all(isinstance(v, Constant) for v in inst.operands)
            ):
                counts["n_constant_operand_insts"] += 1
            if inst.dest is not None and not uses.get(inst.dest) and is_removable_if_unused(inst):
                counts["n_unused_removable"] += 1
            key = expression_key(inst)
            if key is not None:
                if key in seen_keys:
                    counts["n_duplicate_expressions"] += 1
                seen_keys.add(key)
            if (
                loop_defs
                and is_speculatable(inst)
                and not any(isinstance(v, Register) and v in loop_defs for v in inst.operands)
            ):
                counts["n_loop_invariant"] += 1
            if (
                op is Opcode.MUL
                and any(v in iv_registers for v in inst.operands)
                and any(isinstance(v, Constant) for v in inst.operands)
            ):
                counts["n_iv_multiplies"] += 1


def extract_features(module: Module) -> dict[str, float]:
    """Feature dictionary with exactly the keys in :data:`FEATURE_NAMES`."""
    counts: Counter[str] = Counter()
    recursive = recursive_functions(module)
    counts["n_recursive_functions"] = len(recursive)
    for fn in module.functions.values():
        _function_features(fn, module, recursive, counts)
    total = max(counts["n_instructions"], 1)
    features: dict[str, float] = {name: float(counts.get(name, 0)) for name in FEATURE_NAMES}
    for name in OPCODE_FEATURES:
        features[name] = counts.get(name, 0) / total
    features["frac_insts_in_loops"] = counts["insts_in_loops"] / total
    features["frac_boundschecks_on_iv"] = counts["boundschecks_on_iv"] / max(
        counts["n_boundschecks"], 1
    )
    return features


def feature_vector(module: Module) -> list[float]:
    features = extract_features(module)
    return [features[name] for name in FEATURE_NAMES]
