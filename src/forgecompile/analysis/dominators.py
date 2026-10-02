"""Dominator tree and dominance frontiers.

**Dominance.** Block A *dominates* block B (A dom B) if every path from the
entry to B passes through A. Every block dominates itself. The *immediate
dominator* idom(B) is the unique closest strict dominator of B. The idom edges
form a tree rooted at the entry: the dominator tree.

**Algorithm.** Cooper, Harvey & Kennedy, "A Simple, Fast Dominance Algorithm"
(2001). It iterates

    idom(b) = intersect over processed predecessors p of b

in reverse postorder until nothing changes. ``intersect`` walks two
candidates up the current tree until they meet, using RPO numbers to decide
which one to move. The worst case is O(n²), but on reducible CFGs (all
MiniLang CFGs are, since the language has no goto) it converges in a few
passes. The paper shows it is faster in practice than Lengauer-Tarjan for
graphs of this size, and it takes about 20 lines.

**Dominance frontier.** DF(A) is the set of blocks B such that A dominates a
predecessor of B but does not strictly dominate B. Informally, it is where
A's dominance "ends", which is exactly where a variable defined in A may
meet a different definition. SSA construction places phi nodes at the
(iterated) dominance frontiers of definition sites (Cytron et al., 1991).
"""

from __future__ import annotations

from forgecompile.analysis.cfg import predecessors, reverse_postorder
from forgecompile.ir.function import BasicBlock, Function


class DominatorTree:
    def __init__(self, fn: Function) -> None:
        self.fn = fn
        self.rpo = reverse_postorder(fn)
        self.preds = predecessors(fn)
        self._rpo_index = {block: i for i, block in enumerate(self.rpo)}
        self.idom: dict[BasicBlock, BasicBlock | None] = self._compute_idoms()
        self.children: dict[BasicBlock, list[BasicBlock]] = {b: [] for b in self.rpo}
        for block in self.rpo:  # RPO order keeps children deterministic
            parent = self.idom[block]
            if parent is not None:
                self.children[parent].append(block)
        self._pre: dict[BasicBlock, int] = {}
        self._post: dict[BasicBlock, int] = {}
        self._number_tree()

    # ------------------------------------------------------------------ construction

    def _compute_idoms(self) -> dict[BasicBlock, BasicBlock | None]:
        entry = self.fn.entry
        idom: dict[BasicBlock, BasicBlock] = {entry: entry}
        index = self._rpo_index

        def intersect(a: BasicBlock, b: BasicBlock) -> BasicBlock:
            while a is not b:
                while index[a] > index[b]:
                    a = idom[a]
                while index[b] > index[a]:
                    b = idom[b]
            return a

        changed = True
        while changed:
            changed = False
            for block in self.rpo[1:]:
                processed = [p for p in self.preds[block] if p in idom]
                new_idom = processed[0]
                for pred in processed[1:]:
                    new_idom = intersect(pred, new_idom)
                if idom.get(block) is not new_idom:
                    idom[block] = new_idom
                    changed = True
        result: dict[BasicBlock, BasicBlock | None] = dict(idom)
        result[entry] = None  # the root has no immediate dominator
        return result

    def _number_tree(self) -> None:
        """Pre/post DFS numbers make ``dominates`` an O(1) interval test."""
        counter = 0
        stack: list[tuple[BasicBlock, bool]] = [(self.fn.entry, False)]
        while stack:
            block, done = stack.pop()
            if done:
                self._post[block] = counter
                counter += 1
                continue
            self._pre[block] = counter
            counter += 1
            stack.append((block, True))
            stack.extend((child, False) for child in reversed(self.children[block]))

    # ------------------------------------------------------------------ queries

    def dominates(self, a: BasicBlock, b: BasicBlock) -> bool:
        """True if every path from the entry to ``b`` goes through ``a`` (reflexive)."""
        return self._pre[a] <= self._pre[b] and self._post[b] <= self._post[a]

    def strictly_dominates(self, a: BasicBlock, b: BasicBlock) -> bool:
        return a is not b and self.dominates(a, b)

    def preorder(self) -> list[BasicBlock]:
        """Dominator-tree preorder: every block comes after its dominators."""
        return sorted(self.rpo, key=self._pre.__getitem__)

    def frontiers(self) -> dict[BasicBlock, set[BasicBlock]]:
        """Dominance frontiers, using the Cooper-Harvey-Kennedy runner algorithm.

        For each join point ``b`` (two or more predecessors), walk up from each
        predecessor until reaching idom(b). Every block passed on the way has
        ``b`` in its frontier.
        """
        df: dict[BasicBlock, set[BasicBlock]] = {block: set() for block in self.rpo}
        for block in self.rpo:
            preds = [p for p in self.preds[block] if p in self._rpo_index]
            if len(preds) < 2:
                continue
            for pred in preds:
                runner: BasicBlock | None = pred
                while runner is not None and runner is not self.idom[block]:
                    df[runner].add(block)
                    runner = self.idom[runner]
        return df
