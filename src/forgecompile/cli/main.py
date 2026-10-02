"""Entry point for the ``forgecompile`` command.

Subcommands are added phase by phase; each one is a small function that
receives the parsed ``argparse.Namespace`` and returns a process exit code.
Currently available:

    forgecompile --version
    forgecompile info [--json]     environment + backend toolchain report
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from forgecompile import __version__
from forgecompile.utils.environment import collect_environment
from forgecompile.utils.logging import configure_logging

EXIT_OK = 0
EXIT_USAGE = 2


def _cmd_info(args: argparse.Namespace) -> int:
    env = collect_environment()
    if args.json:
        print(json.dumps(env, indent=2, default=str))
        return EXIT_OK

    python = env["python"]
    plat = env["platform"]
    tools = env["tools"]
    assert isinstance(python, dict) and isinstance(plat, dict) and isinstance(tools, list)
    print(f"ForgeCompile {__version__}")
    print(f"Python      {python['version']} ({python['executable']})")
    print(f"Platform    {plat['system']} {plat['release']} {plat['machine']}")
    print(f"CPUs        {env['cpu_count']}")
    print("Toolchain:")
    for tool in tools:
        mark = "ok " if tool["available"] else "-- "
        version = tool["version"] or ""
        detail = f"  [{tool['detail']}]" if tool["detail"] else ""
        print(f"  {mark}{tool['name']:<10}{version}{detail}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forgecompile",
        description="ForgeCompile: an ML-guided optimizing compiler for MiniLang.",
    )
    parser.add_argument("--version", action="version", version=f"forgecompile {__version__}")
    parser.add_argument(
        "--log-level",
        default=None,
        help="logging level (DEBUG, INFO, WARNING, ...); default from FORGECOMPILE_LOG_LEVEL",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    info = subparsers.add_parser("info", help="show environment and backend toolchain status")
    info.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    info.set_defaults(handler=_cmd_info)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(level=args.log_level)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    exit_code: int = handler(args)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
