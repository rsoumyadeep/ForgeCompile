"""Parser for the textual IR format produced by ``forgecompile.ir.printer``.

It exists so that optimization-pass tests can be written directly in IR::

    fn = parse_function('''
    func @f(%x: i64) -> i64 {
    entry:
        %t1: i64 = add %x, 0
        ret %t1
    }''')

and so that ``parse(print(ir))`` can serve as a round-trip check on the printer.

Two passes per function: the first creates every block and every defined
register, so that forward references (branches to later blocks, phis that
use values defined later) resolve; the second builds the instructions.
"""

from __future__ import annotations

import re

from forgecompile.ir.function import BasicBlock, Function, Module
from forgecompile.ir.instructions import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    AllocaInst,
    BinaryInst,
    BoundsCheckInst,
    BranchInst,
    CallInst,
    CmpPred,
    CompareInst,
    Instruction,
    JumpInst,
    LoadInst,
    MemZeroInst,
    Opcode,
    PhiInst,
    PrintInst,
    PtrAddInst,
    ReturnInst,
    StoreInst,
    UnaryInst,
    UnreachableInst,
)
from forgecompile.ir.values import Constant, IRType, Register, Undef, Value

_HEADER = re.compile(r"^func\s+@([\w.]+)\((.*)\)\s*->\s*(\w+)\s*\{$")
_LABEL = re.compile(r"^([\w.]+):$")
_DEF = re.compile(r"^%([\w.]+)\s*:\s*(\w+)\s*=\s*(.*)$")
_LOAD = re.compile(r"^load\s+(\S+?)\[(.+)\]$")
_STORE = re.compile(r"^store\s+(\S+?)\[(.+?)\],\s*(.+)$")
_CALL = re.compile(r"^call\s+@([\w.]+)\((.*)\)$")
_PHI_PAIR = re.compile(r"\[\s*([^,\]]+?)\s*,\s*([\w.]+)\s*\]")
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?(\d+\.\d*([eE][+-]?\d+)?|\d+[eE][+-]?\d+|inf|nan)$")

_OPCODES = {op.value: op for op in Opcode}
_TYPES = {ty.value: ty for ty in IRType}


class IRParseError(Exception):
    def __init__(self, line_number: int, message: str) -> None:
        super().__init__(f"line {line_number}: {message}")
        self.line_number = line_number


def _split_args(text: str) -> list[str]:
    text = text.strip()
    return [part.strip() for part in text.split(",")] if text else []


class _FunctionParser:
    def __init__(self, lines: list[tuple[int, str]], header_line: int, header: str) -> None:
        self.lines = lines
        self.header_line = header_line
        match = _HEADER.match(header)
        if not match:
            raise IRParseError(header_line, f"bad function header: {header!r}")
        name, params_text, ret = match.groups()
        self.registers: dict[str, Register] = {}
        params: list[Register] = []
        for param in _split_args(params_text):
            pname, _, ptype = (s.strip() for s in param.partition(":"))
            if not pname.startswith("%"):
                raise IRParseError(header_line, f"bad parameter {param!r}")
            reg = Register(pname[1:], self._type(ptype, header_line))
            self.registers[reg.name] = reg
            params.append(reg)
        self.fn = Function(name, params, self._type(ret, header_line))
        self.blocks: dict[str, BasicBlock] = {}

    @staticmethod
    def _type(text: str, line: int) -> IRType:
        try:
            return _TYPES[text]
        except KeyError:
            raise IRParseError(line, f"unknown type {text!r}") from None

    # ------------------------------------------------------------------ pass 1

    def predeclare(self) -> None:
        for number, line in self.lines:
            label = _LABEL.match(line)
            if label:
                name = label.group(1)
                if name in self.blocks:
                    raise IRParseError(number, f"duplicate label {name!r}")
                block = BasicBlock(name)
                self.fn._used_labels.add(name)
                self.fn.blocks.append(block)
                self.blocks[name] = block
                continue
            definition = _DEF.match(line)
            if definition:
                rname, rtype, _ = definition.groups()
                ty = self._type(rtype, number)
                existing = self.registers.get(rname)
                if existing is None:
                    self.registers[rname] = Register(rname, ty)
                    self.fn.reserve_name(rname)
                elif existing.type is not ty:
                    raise IRParseError(number, f"register %{rname} redefined with type {ty}")

    # ------------------------------------------------------------------ pass 2

    def build(self) -> Function:
        block: BasicBlock | None = None
        for number, line in self.lines:
            label = _LABEL.match(line)
            if label:
                block = self.blocks[label.group(1)]
                continue
            if block is None:
                raise IRParseError(number, "instruction before the first label")
            # insert() rather than append(): the parser represents the text faithfully,
            # even malformed IR (e.g. two terminators), and leaves checking to the verifier.
            block.insert(len(block.instructions), self._instruction(number, line))
        return self.fn

    def _value(self, text: str, line: int) -> Value:
        text = text.strip()
        if text.startswith("%"):
            reg = self.registers.get(text[1:])
            if reg is None:
                raise IRParseError(line, f"undefined register {text}")
            return reg
        if text in ("true", "false"):
            return Constant(IRType.I1, text == "true")
        if text.startswith("undef."):
            return Undef(self._type(text[len("undef.") :], line))
        if _INT.match(text):
            return Constant(IRType.I64, int(text))
        if _FLOAT.match(text):
            return Constant(IRType.F64, float(text))
        raise IRParseError(line, f"bad operand {text!r}")

    def _block(self, label: str, line: int) -> BasicBlock:
        try:
            return self.blocks[label.strip()]
        except KeyError:
            raise IRParseError(line, f"unknown block {label.strip()!r}") from None

    def _instruction(self, line: int, text: str) -> Instruction:
        dest: Register | None = None
        definition = _DEF.match(text)
        if definition:
            dest = self.registers[definition.group(1)]
            text = definition.group(3).strip()
        mnemonic, _, rest = text.partition(" ")
        opcode = _OPCODES.get(mnemonic)
        if opcode is None:
            raise IRParseError(line, f"unknown opcode {mnemonic!r}")
        v = self._value
        args = _split_args(rest)

        def need_dest() -> Register:
            if dest is None:
                raise IRParseError(line, f"'{mnemonic}' needs a destination register")
            return dest

        if opcode in BINARY_OPCODES:
            return BinaryInst(opcode, need_dest(), v(args[0], line), v(args[1], line))
        if opcode in UNARY_OPCODES:
            return UnaryInst(opcode, need_dest(), v(args[0], line))
        if opcode in (Opcode.ICMP, Opcode.FCMP):
            pred_text, _, operands = rest.partition(" ")
            pair = _split_args(operands)
            pred = CmpPred(pred_text)
            return CompareInst(opcode, pred, need_dest(), v(pair[0], line), v(pair[1], line))
        if opcode is Opcode.ALLOCA:
            return AllocaInst(need_dest(), self._type(args[0], line), int(args[1]))
        if opcode is Opcode.LOAD:
            m = _LOAD.match(text)
            if not m:
                raise IRParseError(line, "expected 'load %p[index]'")
            return LoadInst(need_dest(), v(m.group(1), line), v(m.group(2), line))
        if opcode is Opcode.STORE:
            m = _STORE.match(text)
            if not m:
                raise IRParseError(line, "expected 'store %p[index], value'")
            return StoreInst(v(m.group(1), line), v(m.group(2), line), v(m.group(3), line))
        if opcode is Opcode.PTRADD:
            return PtrAddInst(need_dest(), v(args[0], line), v(args[1], line))
        if opcode is Opcode.MEMZERO:
            return MemZeroInst(v(args[0], line), self._type(args[1], line), int(args[2]))
        if opcode is Opcode.BOUNDSCHECK:
            return BoundsCheckInst(v(args[0], line), int(args[1]))
        if opcode is Opcode.CALL:
            m = _CALL.match(text)
            if not m:
                raise IRParseError(line, "expected 'call @f(args)'")
            call_args = [v(a, line) for a in _split_args(m.group(2))]
            return CallInst(dest, m.group(1), call_args)
        if opcode is Opcode.PRINT:
            return PrintInst(v(args[0], line))
        if opcode is Opcode.PHI:
            pairs = [(v(val, line), self._block(lbl, line)) for val, lbl in _PHI_PAIR.findall(rest)]
            return PhiInst(need_dest(), pairs)
        if opcode is Opcode.JUMP:
            return JumpInst(self._block(rest, line))
        if opcode is Opcode.BRANCH:
            return BranchInst(
                v(args[0], line), self._block(args[1], line), self._block(args[2], line)
            )
        if opcode is Opcode.RET:
            return ReturnInst(v(rest, line) if rest.strip() else None)
        if opcode is Opcode.UNREACHABLE:
            return UnreachableInst()
        raise IRParseError(line, f"unhandled opcode {mnemonic!r}")


def parse_module(text: str) -> Module:
    module = Module()
    lines = [
        (number, line.split("//")[0].strip()) for number, line in enumerate(text.splitlines(), 1)
    ]
    lines = [(n, line) for n, line in lines if line]
    i = 0
    while i < len(lines):
        header_line, header = lines[i]
        j = i + 1
        while j < len(lines) and lines[j][1] != "}":
            j += 1
        if j == len(lines):
            raise IRParseError(header_line, "function body is not closed with '}'")
        parser = _FunctionParser(lines[i + 1 : j], header_line, header)
        parser.predeclare()
        module.add(parser.build())
        i = j + 1
    return module


def parse_function(text: str) -> Function:
    module = parse_module(text)
    if len(module.functions) != 1:
        raise ValueError(f"expected exactly one function, found {len(module.functions)}")
    return next(iter(module.functions.values()))
