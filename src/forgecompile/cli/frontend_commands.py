"""Frontend subcommands: ``lex``, ``parse`` and ``check``."""

from __future__ import annotations

import argparse

from forgecompile.ast.dump import dump
from forgecompile.ast.formatter import format_program
from forgecompile.cli.common import EXIT_OK, read_source, run_compile_step
from forgecompile.diagnostics import CompileError
from forgecompile.driver import check_source
from forgecompile.frontend import parse_source
from forgecompile.frontend.lexer import tokenize


def _cmd_lex(args: argparse.Namespace) -> int:
    source = read_source(args.file)

    def step() -> int:
        tokens, errors = tokenize(source)
        for token in tokens:
            value = f"  value={token.value!r}" if token.value is not None else ""
            print(f"{token.span!s:>8}  {token.kind.name:<10} {token.text!r}{value}")
        if errors:
            raise CompileError(errors)
        return EXIT_OK

    return run_compile_step(source, step)


def _cmd_parse(args: argparse.Namespace) -> int:
    source = read_source(args.file)

    def step() -> int:
        program = parse_source(source.text, source.name)
        print(format_program(program) if args.format else dump(program), end="")
        if not args.format:
            print()
        return EXIT_OK

    return run_compile_step(source, step)


def _cmd_check(args: argparse.Namespace) -> int:
    source = read_source(args.file)

    def step() -> int:
        checked = check_source(source.text, source.name)
        if args.dump:
            print(dump(checked.ast, show_types=True))
        else:
            count = len(checked.info.functions)
            print(f"{source.name}: ok ({count} function{'s' if count != 1 else ''})")
        return EXIT_OK

    return run_compile_step(source, step)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    lex = subparsers.add_parser("lex", help="print the token stream of a MiniLang file")
    lex.add_argument("file")
    lex.set_defaults(handler=_cmd_lex)

    parse = subparsers.add_parser("parse", help="parse a MiniLang file and print its AST")
    parse.add_argument("file")
    parse.add_argument(
        "--format", action="store_true", help="print canonical MiniLang source instead of the AST"
    )
    parse.set_defaults(handler=_cmd_parse)

    check = subparsers.add_parser("check", help="parse and type-check a MiniLang file")
    check.add_argument("file")
    check.add_argument("--dump", action="store_true", help="print the AST annotated with types")
    check.set_defaults(handler=_cmd_check)
