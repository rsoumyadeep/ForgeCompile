"""Basic blocks, functions and modules.

A **basic block** is a maximal straight-line sequence of instructions: control
enters only at the top and leaves only at the bottom, through the single
*terminator* (``jump``, ``br``, ``ret`` or ``unreachable``). Phi instructions,
if any, come first. Successors are read off the terminator. Predecessors are
computed by ``forgecompile.analysis.cfg`` rather than stored, so passes that
rewrite branches never leave a stale predecessor list behind.
"""

from __future__ import annotations

from collections.abc import Iterator

from forgecompile.ir.instructions import Instruction, PhiInst, Terminator
from forgecompile.ir.values import IRType, Register


class BasicBlock:
    def __init__(self, label: str) -> None:
        self.label = label
        self.instructions: list[Instruction] = []

    # ------------------------------------------------------------------ inspection

    @property
    def terminator(self) -> Terminator | None:
        if self.instructions and isinstance(self.instructions[-1], Terminator):
            return self.instructions[-1]
        return None

    @property
    def successors(self) -> list[BasicBlock]:
        term = self.terminator
        return term.targets if term is not None else []

    def phis(self) -> list[PhiInst]:
        result = []
        for inst in self.instructions:
            if not isinstance(inst, PhiInst):
                break
            result.append(inst)
        return result

    def body(self) -> list[Instruction]:
        """Instructions that are neither phis nor the terminator."""
        start = len(self.phis())
        end = len(self.instructions) - (1 if self.terminator is not None else 0)
        return self.instructions[start:end]

    # ------------------------------------------------------------------ mutation

    def append(self, inst: Instruction) -> Instruction:
        if self.terminator is not None:
            raise ValueError(f"block {self.label} already has a terminator")
        inst.block = self
        self.instructions.append(inst)
        return inst

    def insert(self, index: int, inst: Instruction) -> Instruction:
        inst.block = self
        self.instructions.insert(index, inst)
        return inst

    def insert_before_terminator(self, inst: Instruction) -> Instruction:
        index = len(self.instructions) - (1 if self.terminator is not None else 0)
        return self.insert(index, inst)

    def remove(self, inst: Instruction) -> None:
        self.instructions.remove(inst)
        inst.block = None

    def __repr__(self) -> str:
        return f"<BasicBlock {self.label}>"


class Function:
    def __init__(self, name: str, params: list[Register], return_type: IRType) -> None:
        self.name = name
        self.params = params
        self.return_type = return_type
        self.blocks: list[BasicBlock] = []
        self._used_names: set[str] = {p.name for p in params}
        self._used_labels: set[str] = set()
        self._temp_counter = 0

    @property
    def entry(self) -> BasicBlock:
        return self.blocks[0]

    def instructions(self) -> Iterator[Instruction]:
        for block in self.blocks:
            yield from block.instructions

    def _unique(self, hint: str, used: set[str]) -> str:
        name = hint
        counter = 1
        while name in used:
            name = f"{hint}.{counter}"
            counter += 1
        used.add(name)
        return name

    def new_register(self, hint: str, type: IRType) -> Register:
        """Create a register with a function-unique name derived from ``hint``."""
        return Register(self._unique(hint, self._used_names), type)

    def new_temp(self, type: IRType) -> Register:
        """Create a compiler temporary named ``%t1``, ``%t2``, ..."""
        while True:
            self._temp_counter += 1
            name = f"t{self._temp_counter}"
            if name not in self._used_names:
                self._used_names.add(name)
                return Register(name, type)

    def reserve_name(self, name: str) -> None:
        """Mark a name as used (for registers created outside ``new_register``)."""
        self._used_names.add(name)

    def new_block(self, hint: str) -> BasicBlock:
        block = BasicBlock(self._unique(hint, self._used_labels))
        self.blocks.append(block)
        return block

    def remove_block(self, block: BasicBlock) -> None:
        self.blocks.remove(block)

    def block_by_label(self, label: str) -> BasicBlock:
        for block in self.blocks:
            if block.label == label:
                return block
        raise KeyError(label)

    def __repr__(self) -> str:
        return f"<Function @{self.name}>"


class Module:
    def __init__(self) -> None:
        self.functions: dict[str, Function] = {}

    def add(self, function: Function) -> Function:
        if function.name in self.functions:
            raise ValueError(f"duplicate function @{function.name}")
        self.functions[function.name] = function
        return function
