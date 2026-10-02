"""CLI tests for `forgecompile check`."""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecompile.cli.main import EXIT_COMPILE_ERROR, EXIT_OK, main

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_check_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(EXAMPLES / "gcd.mini")]) == EXIT_OK
    assert capsys.readouterr().out.strip().endswith("ok (4 functions)")


def test_check_dump_shows_types(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--dump", str(EXAMPLES / "newton_sqrt.mini")]) == EXIT_OK
    out = capsys.readouterr().out
    assert "FloatLiteral value=2.0 : float" in out
    assert "Cast target=int : int" in out


def test_check_reports_semantic_errors(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    src = tmp_path / "bad.mini"
    src.write_text("fn main() {\n    let x: int = 1.5;\n    print(y);\n}\n", "utf-8")
    assert main(["check", str(src)]) == EXIT_COMPILE_ERROR
    err = capsys.readouterr().err
    assert "error: mismatched types: 'x' is declared as int but initialized with float" in err
    assert "error: undefined variable 'y'" in err
    assert f"{src}:2:18" in err
    assert "2 errors found" in err


def test_check_reports_syntax_errors_before_semantics(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    src = tmp_path / "bad.mini"
    src.write_text("fn main() { let x: int = 1.5 }", "utf-8")
    assert main(["check", str(src)]) == EXIT_COMPILE_ERROR
    err = capsys.readouterr().err
    assert "expected ';'" in err
    assert "mismatched" not in err  # semantic analysis does not run on a broken AST
