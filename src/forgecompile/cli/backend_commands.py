"""Backend subcommands: ``llvm`` (print LLVM IR) and ``build`` (native executable)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forgecompile.backend.llvm_emitter import optimize_llvm
from forgecompile.backend.native import EXE_SUFFIX, compile_llvm
from forgecompile.cli.common import EXIT_OK, read_source, run_compile_step
from forgecompile.cli.ir_commands import add_pipeline_options, selected_pipeline
from forgecompile.driver import compile_to_llvm


def add_llvm_opt_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llvm-opt",
        type=int,
        choices=[0, 1, 2, 3],
        default=0,
        help="LLVM's own optimization level when generating native code (default 0: "
        "isolate ForgeCompile's optimizations)",
    )


def _cmd_llvm(args: argparse.Namespace) -> int:
    source = read_source(args.file)
    pipeline = selected_pipeline(args)

    def step() -> int:
        llvm_ir, _ = compile_to_llvm(source.text, source.name, pipeline)
        if args.llvm_opt:
            llvm_ir = optimize_llvm(llvm_ir, args.llvm_opt)
        print(llvm_ir, end="")
        return EXIT_OK

    return run_compile_step(source, step)


def _cmd_build(args: argparse.Namespace) -> int:
    source = read_source(args.file)
    pipeline = selected_pipeline(args)
    output = Path(args.output) if args.output else Path(source.name).with_suffix(EXE_SUFFIX)

    def step() -> int:
        llvm_ir, report = compile_to_llvm(source.text, source.name, pipeline)
        keep = output.with_suffix(".ll") if args.emit_llvm else None
        build = compile_llvm(llvm_ir, output, args.llvm_opt, keep_ll=keep)
        if keep is None:
            build.llvm_file.unlink(missing_ok=True)
        print(
            f"built {output} (ForgeCompile passes: {len(pipeline)}, "
            f"pass time {report.total_seconds * 1000:.1f} ms; native compile "
            f"{build.compile_seconds:.2f} s at LLVM -O{args.llvm_opt})",
            file=sys.stderr,
        )
        return EXIT_OK

    return run_compile_step(source, step)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    llvm = subparsers.add_parser("llvm", help="print the LLVM IR generated for a MiniLang file")
    llvm.add_argument("file")
    add_pipeline_options(llvm)
    llvm.add_argument(
        "--llvm-opt",
        type=int,
        choices=[0, 1, 2, 3],
        default=0,
        help="also run LLVM's optimizer at this level (inspection only)",
    )
    llvm.set_defaults(handler=_cmd_llvm)

    build = subparsers.add_parser("build", help="compile a MiniLang file to a native executable")
    build.add_argument("file")
    build.add_argument("-o", "--output", help="output executable path")
    add_pipeline_options(build)
    add_llvm_opt_option(build)
    build.add_argument(
        "--emit-llvm", action="store_true", help="keep the .ll file next to the output"
    )
    build.set_defaults(handler=_cmd_build)
