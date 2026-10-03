"""IR-level subcommands: ``ir``, ``opt``, ``passes`` and ``run`` (interpreters or native)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forgecompile.backend.native import build_and_run
from forgecompile.cli.common import (
    EXIT_OK,
    CliError,
    read_source,
    run_compile_step,
    write_program_output,
)
from forgecompile.driver import build_ir, check_source, compile_to_llvm
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


def selected_pipeline(args: argparse.Namespace) -> list[str]:
    """The pass list selected by --passes / -O (default: no optimization)."""
    if args.passes is not None and args.opt_level is not None:
        raise CliError("use either --passes or -O, not both")
    level = args.opt_level if args.opt_level is not None else "0"
    spec = args.passes if args.passes is not None else f"O{level}"
    try:
        return parse_pipeline(spec)
    except ValueError as exc:
        raise CliError(str(exc)) from None


DEFAULT_DQN_CHECKPOINT = (
    Path(__file__).resolve().parents[3]
    / "experiments"
    / "EXP-006-rl-scheduling"
    / "checkpoints"
    / "dqn_seed0.npz"
)


def scheduled_pipeline(args: argparse.Namespace, source_text: str, name: str) -> list[str]:
    """The pass list: from --passes/-O, or decided per program by --schedule (a policy).

    The policy looks at this program's IR and picks passes one at a time; the
    resulting list is then applied like any other pipeline, and printed to stderr.
    """
    if args.schedule is None:
        return selected_pipeline(args)
    if args.passes is not None or args.opt_level is not None:
        raise CliError("use either --schedule or --passes/-O, not both")
    from forgecompile.ml.dataset import CostEvaluator
    from forgecompile.ml.policies import OraclePolicy, Policy, schedule

    policy: Policy
    if args.schedule == "oracle":
        policy = OraclePolicy(CostEvaluator("cost"))
    else:
        from forgecompile.ml.features import FEATURE_NAMES
        from forgecompile.rl.dqn import DQNAgent, DQNPolicy
        from forgecompile.rl.env import ENV_ACTIONS

        checkpoint = Path(args.checkpoint) if args.checkpoint else DEFAULT_DQN_CHECKPOINT
        if not checkpoint.exists():
            raise CliError(f"no DQN checkpoint at {checkpoint} (train one with EXP-006)")
        n = len(ENV_ACTIONS)
        policy = DQNPolicy(DQNAgent.load(checkpoint, len(FEATURE_NAMES) + 1 + n, n))
    result = schedule(policy, build_ir(source_text, name), max_steps=args.max_passes)
    print(
        f"schedule ({args.schedule}): {','.join(result.actions) or '(none)'} "
        f"[decided in {1000 * result.decision_seconds:.1f} ms]",
        file=sys.stderr,
    )
    return result.actions


def _optimized(source_text: str, name: str, pipeline: list[str]) -> tuple[Module, PipelineReport]:
    module = build_ir(source_text, name)
    return module, optimize(module, pipeline)


def add_pipeline_options(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument(
        "--schedule",
        choices=["oracle", "dqn"],
        help="choose passes per program: 'oracle' (greedy, applies and measures every pass) "
        "or 'dqn' (the trained RL policy); the chosen list is printed to stderr",
    )
    parser.add_argument("--checkpoint", help="DQN checkpoint (.npz) for --schedule dqn")
    parser.add_argument(
        "--max-passes", type=int, default=12, help="pass budget for --schedule (default 12)"
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

    def step() -> int:
        pipeline = scheduled_pipeline(args, source.text, source.name)
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
    optimizing = args.passes is not None or args.opt_level is not None or args.schedule
    if args.engine not in ("ir", "native") and optimizing:
        raise CliError("--passes/-O/--schedule requires the 'ir' or 'native' engine")

    def step() -> int:
        pipeline = scheduled_pipeline(args, source.text, source.name)
        stats: IRExecutionResult | None = None
        if args.engine == "ast":
            result: ExecutionResult | IRExecutionResult = run_program(
                check_source(source.text, source.name).ast
            )
        elif args.engine == "ir-nossa":
            stats = run_module(build_ir(source.text, source.name, ssa=False))
            result = stats
        elif args.engine == "native":
            llvm_ir, _ = compile_to_llvm(source.text, source.name, pipeline)
            _, native = build_and_run(llvm_ir, args.llvm_opt)
            write_program_output(native.stdout)
            sys.stderr.write(native.stderr)
            return native.exit_code
        else:
            module, _ = _optimized(source.text, source.name, pipeline)
            stats = run_module(module)
            result = stats
        write_program_output(result.stdout)
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
    add_pipeline_options(opt)
    opt.add_argument("--stats", action="store_true", help="print per-pass statistics to stderr")
    opt.set_defaults(handler=_cmd_opt)

    passes = subparsers.add_parser("passes", help="list optimization passes and presets")
    passes.set_defaults(handler=_cmd_passes)

    run = subparsers.add_parser("run", help="execute a MiniLang program with an interpreter")
    run.add_argument("file")
    run.add_argument(
        "--engine",
        choices=["ir", "ir-nossa", "ast", "native"],
        default="ir",
        help="ir: SSA IR interpreter (default); ir-nossa: pre-SSA IR; ast: reference AST "
        "interpreter; native: compile with LLVM and run the executable",
    )
    run.add_argument(
        "--llvm-opt",
        type=int,
        choices=[0, 1, 2, 3],
        default=0,
        help="LLVM optimization level for --engine native (default 0)",
    )
    add_pipeline_options(run)
    run.add_argument("--stats", action="store_true", help="print dynamic instruction counts")
    run.set_defaults(handler=_cmd_run)
