"""Unit tests for the AST-level 'completes normally' analysis."""

from __future__ import annotations

import pytest

from forgecompile.ast import nodes as ast
from forgecompile.frontend import parse_source
from forgecompile.semantic.control_flow import completes_normally


def body(text: str) -> ast.Block:
    return parse_source(f"fn f() {{ {text} }}").functions[0].body


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", True),
        ("print(1);", True),
        ("return;", False),
        ("print(1); return;", False),
        ("if c { return; }", True),
        ("if c { return; } else { return; }", False),
        ("if c { return; } else { print(1); }", True),
        ("if a { return; } else if b { return; } else { return; }", False),
        ("if a { return; } else if b { return; }", True),
        ("while c { return; }", True),  # may run zero times
        ("for i in 0..3 { return; }", True),  # may run zero times
        ("while true { }", False),  # infinite loop never falls through
        ("while true { break; }", True),
        ("while true { if c { break; } }", True),
        ("while true { while c { break; } }", False),  # break targets the inner loop
        ("while true { for i in 0..2 { break; } }", False),
        ("{ { return; } }", False),
    ],
)
def test_completes_normally(text: str, expected: bool) -> None:
    assert completes_normally(body(text)) is expected
