"""CLI tests for `forgecompile lex` and `forgecompile parse`."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.cli.main import EXIT_COMPILE_ERROR, EXIT_OK, main

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_parse_dumps_ast(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", str(EXAMPLES / "gcd.mini")]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Program")
    assert "FunctionDecl name='gcd' return_type=int" in out


def test_parse_format_emits_reparseable_source(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["parse", "--format", str(EXAMPLES / "matmul.mini")]) == EXIT_OK
    formatted = capsys.readouterr().out
    copy = tmp_path / "copy.mini"
    copy.write_text(formatted, "utf-8")
    assert main(["parse", "--format", str(copy)]) == EXIT_OK
    assert capsys.readouterr().out == formatted


def test_lex_prints_tokens(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    src = tmp_path / "t.mini"
    src.write_text("let x = 4.5;", "utf-8")
    assert main(["lex", str(src)]) == EXIT_OK
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == ["1:1", "LET", "'let'"]
    assert "value=4.5" in out[3]
    assert "EOF" in out[-1]


def test_syntax_error_exit_code_and_rendering(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    src = tmp_path / "bad.mini"
    src.write_text("fn main() {\n    let x = 5\n}\n", "utf-8")
    assert main(["parse", str(src)]) == EXIT_COMPILE_ERROR
    err = capsys.readouterr().err
    assert "error: expected ';' after variable declaration" in err
    assert f"{src}:2:14" in err
    assert "1 error found" in err


def test_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", "does/not/exist.mini"]) == EXIT_COMPILE_ERROR
    assert "no such file" in capsys.readouterr().err
