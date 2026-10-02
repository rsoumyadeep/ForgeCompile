"""IR-level subcommands: ``ir``, ``opt``, ``passes`` and ``run``."""

from __future__ import annotations

import argparse
import sys

from forgecompile.cli.common import EXIT_OK, CliError, read_source, run_compile_step
from forgecompile.driver import build_ir, check_source
from forgecompile.ir.function import Module
from forgecompile.ir.interpreter import IRExecutionResult, run_module
from forgecompile.ir.printer import format_module
from forgecompile.optimization.pass_manager import (
    PRESETS,
    PipelineReport,
    available_passes,
    optimize,
    parse_pipeline,
)
from forgecompile.runtime.ast_interpreter import ExecutionResult, run_program


def _pipeline(args: argparse.Namespace) -> list[str]:
    """The pass list selected by --passes / -O (default: no optimization)."""
    if args.passes is not None and args.opt_level is not None:
        raise CliError("use either --passes or -O, not both")
    level = args.opt_level if args.opt_level is not None else "0"
    spec = args.passes if args.passes is not None else f"O{level}"
    try:
        return parse_pipeline(spec)
    except ValueError as exc:
        raise CliError(str(exc)) from None


def _optimized(source_text: str, name: str, pipeline: list[str]) -> tuple[Module, PipelineReport]:
    module = build_ir(source_text, name)
    return module, optimize(module, pipeline)


def _add_pipeline_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--passes",
        metavar="PIPELINE",
        help="comma-separated passes (e.g. constfold,dce,cse), a preset, or a pipeline file",
    )
    parser.add_argument(
        "-O",
        dest="opt_level",
        choices=sorted(p.removeprefix("O") for p in PRESETS),
        help="optimization preset, written like GCC: -O0 (none), -O1, -O2",
    )


def _cmd_ir(args: argparse.Namespace) -> int:
    source = read_source(args.file)

    def step() -> int:
        module = build_ir(source.text, source.name, ssa=not args.no_ssa)
        print(format_module(module), end="")
        return EXIT_OK

    return run_compile_step(source, step)


def _cmd_opt(args: argparse.Namespace) -> int:
    source = read_source(args.file)
    pipeline = _pipeline(args)

    def step() -> int:
        module, report = _optimized(source.text, source.name, pipeline)
        print(format_module(module), end="")
        if args.stats:
            print(report.summary(), file=sys.stderr)
        return EXIT_OK

    return run_compile_step(source, step)


def _cmd_passes(args: argparse.Namespace) -> int:
    print("Passes:")
    for name, cls in available_passes().items():
        print(f"  {name:<12} {cls.description}")
    print("\nPresets:")
    for preset, names in PRESETS.items():
        print(f"  {preset:<4} {', '.join(names) if names else '(no optimization)'}")
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    source = read_source(args.file)
    pipeline = _pipeline(args)
    if args.engine != "ir" and pipeline:
        raise CliError("--passes/-O requires the default 'ir' engine")

    def step() -> int:
        stats: IRExecutionResult | None = None
        if args.engine == "ast":
            result: ExecutionResult | IRExecutionResult = run_program(
                check_source(source.text, source.name).ast
            )
        elif args.engine == "ir-nossa":
            stats = run_module(build_ir(source.text, source.name, ssa=False))
            result = stats
        else:
            module, _ = _optimized(source.text, source.name, pipeline)
            stats = run_module(module)
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

    opt = subparsers.add_parser("opt", help="optimize a MiniLang file and print the IR")
    opt.add_argument("file")
    _add_pipeline_options(opt)
    opt.add_argument("--stats", action="store_true", help="print per-pass statistics to stderr")
    opt.set_defaults(handler=_cmd_opt)

    passes = subparsers.add_parser("passes", help="list optimization passes and presets")
    passes.set_defaults(handler=_cmd_passes)

    run = subparsers.add_parser("run", help="execute a MiniLang program with an interpreter")
    run.add_argument("file")
    run.add_argument(
        "--engine",
        choices=["ir", "ir-nossa", "ast"],
        default="ir",
        help="ir: SSA IR (default); ir-nossa: pre-SSA IR; ast: reference AST interpreter",
    )
    _add_pipeline_options(run)
    run.add_argument("--stats", action="store_true", help="print dynamic instruction counts")
    run.set_defaults(handler=_cmd_run)
