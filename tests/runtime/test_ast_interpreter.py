"""Reference AST interpreter: observable behaviour per LANGUAGE.md §7."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from forgecompile.driver import check_source
from forgecompile.runtime.ast_interpreter import ExecutionResult, StepLimitExceeded, run_program

Run = Callable[[str], ExecutionResult]


def main(body: str, extra: str = "") -> str:
    return f"{extra}\nfn main() -> int {{\n{body}\n}}\n"


def test_print_formats(ast_run: Run) -> None:
    result = ast_run(
        main("print(42); print(-7); print(true); print(2.5); print(1.0 / 3.0); return 0;")
    )
    assert result.stdout == "42\n-7\ntrue\n2.500000\n0.333333\n"


def test_exit_status_is_main_result_mod_256(ast_run: Run) -> None:
    assert ast_run(main("return 300;")).exit_code == 44
    assert ast_run(main("return -1;")).exit_code == 255
    assert ast_run("fn main() { print(1); }").exit_code == 0


def test_integer_semantics(ast_run: Run) -> None:
    source = main(
        """
        print(-7 / 2);          // truncation toward zero
        print(-7 % 2);          // sign of dividend
        print(9223372036854775807 + 1);     // wrap-around
        let min = -9223372036854775807 - 1;
        print(min / -1);        // INT_MIN / -1 wraps to INT_MIN
        print(-min);
        return 0;
        """
    )
    assert ast_run(source).stdout.split() == [
        "-3", "-1", "-9223372036854775808", "-9223372036854775808", "-9223372036854775808",
    ]  # fmt: skip


def test_float_semantics(ast_run: Run) -> None:
    source = main(
        """
        let zero = 0.0;
        print(1.0 / zero);
        print(-1.0 / zero);
        print(zero / zero);
        print(-7.5 % 2.0);
        let nan = zero / zero;
        print(nan == nan);
        print(nan != nan);
        print(nan < 1.0);
        return 0;
        """
    )
    assert ast_run(source).stdout.split() == [
        "inf",
        "-inf",
        "nan",
        "-1.500000",
        "false",
        "true",
        "false",
    ]


def test_casts(ast_run: Run) -> None:
    source = main(
        """
        print(2.9 as int); print(-2.9 as int); print(1e300 as int);
        print(true as int); print(false as float); print(3 as float);
        print(0 as bool); print(-5 as bool); print(0.0 as bool);
        let zero = 0.0;
        print((zero / zero) as int); print((zero / zero) as bool);
        return 0;
        """
    )
    assert ast_run(source).stdout.split() == [
        "2", "-2", "9223372036854775807", "1", "0.000000", "3.000000",
        "false", "true", "false", "0", "true",
    ]  # fmt: skip


def test_division_by_zero_is_a_runtime_error_with_partial_output(ast_run: Run) -> None:
    result = ast_run(main("print(1); let z = 0; print(5 / z); print(2); return 0;"))
    assert result.stdout == "1\n"
    assert result.exit_code == 101
    assert result.trap == "division by zero"


def test_out_of_bounds_is_a_runtime_error(ast_run: Run) -> None:
    result = ast_run(main("let a: [int; 3]; let i = 3; a[i] = 1; return 0;"))
    assert result.exit_code == 101
    assert result.trap == "index 3 out of bounds for array of length 3"


def test_short_circuit_skips_rhs(ast_run: Run) -> None:
    extra = "fn noisy(x: bool) -> bool { print(x); return x; }"
    result = ast_run(
        main(
            "let a = noisy(false) && noisy(true); let b = noisy(true) || noisy(false); return 0;",
            extra,
        )
    )
    assert result.stdout == "false\ntrue\n"


def test_left_to_right_evaluation_order(ast_run: Run) -> None:
    extra = "fn f(x: int) -> int { print(x); return x; }"
    result = ast_run(main("let a: [int; 4]; a[f(1)] = f(2) + f(3) * f(4); return 0;", extra))
    assert result.stdout.split() == ["1", "2", "3", "4"]


def test_assignment_target_checked_before_rhs(ast_run: Run) -> None:
    extra = "fn f(x: int) -> int { print(x); return x; }"
    result = ast_run(main("let a: [int; 2]; a[f(5)] = f(9); return 0;", extra))
    assert result.stdout == "5\n"  # the RHS never runs: the index traps first
    assert result.exit_code == 101


def test_arrays_are_passed_by_reference_including_rows(ast_run: Run) -> None:
    extra = "fn fill(row: [int; 2], v: int) { row[0] = v; row[1] = v + 1; }"
    result = ast_run(
        main(
            "let m: [[int; 2]; 2]; fill(m[1], 7); print(m[0][0]); print(m[1][1]); return 0;", extra
        )
    )
    assert result.stdout.split() == ["0", "8"]


def test_declarations_in_loops_are_reinitialized(ast_run: Run) -> None:
    source = main(
        """
        for i in 0..3 {
            let a: [int; 2];
            let x: int;
            print(a[0] + x);
            a[0] = 5; x = 7;
        }
        return 0;
        """
    )
    assert ast_run(source).stdout.split() == ["0", "0", "0"]


def test_for_loop_bound_evaluated_once(ast_run: Run) -> None:
    source = main(
        "let n = 3; let count = 0; for i in 0..n { n = 10; count = count + 1; } print(count); return 0;"
    )
    assert ast_run(source).stdout == "3\n"


def test_break_and_continue(ast_run: Run) -> None:
    source = main(
        """
        for i in 0..10 {
            if i % 2 == 0 { continue; }
            if i > 6 { break; }
            print(i);
        }
        return 0;
        """
    )
    assert ast_run(source).stdout.split() == ["1", "3", "5"]


def test_deep_recursion(ast_run: Run) -> None:
    extra = "fn depth(n: int) -> int { if n == 0 { return 0; } return 1 + depth(n - 1); }"
    assert ast_run(main("print(depth(2000)); return 0;", extra)).stdout == "2000\n"


def test_step_limit() -> None:
    program = check_source("fn main() { while true { } }").ast
    with pytest.raises(StepLimitExceeded):
        run_program(program, max_steps=1000)
