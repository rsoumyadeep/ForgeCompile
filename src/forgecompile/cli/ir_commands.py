"""IR-level subcommands: ``ir`` (print IR) and ``run`` (execute a program)."""

from __future__ import annotations

import argparse
import sys

from forgecompile.cli.common import EXIT_OK, read_source, run_compile_step
from forgecompile.driver import build_ir, check_source
from forgecompile.ir.interpreter import IRExecutionResult, run_module
from forgecompile.ir.printer import format_module
from forgecompile.runtime.ast_interpreter import ExecutionResult, run_program


def _cmd_ir(args: argparse.Namespace) -> int:
    source = read_source(args.file)

    def step() -> int:
        module = build_ir(source.text, source.name, ssa=not args.no_ssa)
        print(format_module(module), end="")
        return EXIT_OK

    return run_compile_step(source, step)


def _cmd_run(args: argparse.Namespace) -> int:
    source = read_source(args.file)

    def step() -> int:
        stats: IRExecutionResult | None = None
        if args.engine == "ast":
            result: ExecutionResult | IRExecutionResult = run_program(
                check_source(source.text, source.name).ast
            )
        else:
            stats = run_module(build_ir(source.text, source.name, ssa=args.engine == "ir"))
            result = stats
        sys.stdout.write(result.stdout)
        if result.trap is not None:
            print(f"runtime error: {result.trap}", file=sys.stderr)
        if args.stats and stats is not None:
            print(f"--- {stats.steps} IR instructions, cost {stats.cost:.0f}", file=sys.stderr)
            for opcode, count in stats.opcode_counts.most_common():
                print(f"    {opcode:<12} {count}", file=sys.stderr)
        return result.exit_code

    return run_compile_step(source, step)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ir = subparsers.add_parser("ir", help="print the ForgeCompile IR of a MiniLang file")
    ir.add_argument("file")
    ir.add_argument("--no-ssa", action="store_true", help="print IR before SSA construction")
    ir.set_defaults(handler=_cmd_ir)

    run = subparsers.add_parser("run", help="execute a MiniLang program with an interpreter")
    run.add_argument("file")
    run.add_argument(
        "--engine",
        choices=["ir", "ir-nossa", "ast"],
        default="ir",
        help="ir: SSA IR (default); ir-nossa: pre-SSA IR; ast: reference AST interpreter",
    )
    run.add_argument("--stats", action="store_true", help="print dynamic instruction counts")
    run.set_defaults(handler=_cmd_run)
