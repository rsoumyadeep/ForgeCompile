/*
 * ForgeCompile native runtime: output and runtime-error reporting.
 *
 * Linked into every native executable alongside the generated LLVM IR. It
 * implements exactly the observable behaviour specified in docs/LANGUAGE.md
 * section 7, which the IR interpreter implements in Python:
 *
 *   print(int)    -> decimal + "\n"
 *   print(bool)   -> "true" / "false" + "\n"
 *   print(float)  -> printf("%.6f"), but NaN is always "nan" and infinities are
 *                    "inf" / "-inf" (C libraries differ on these spellings)
 *   runtime error -> flush stdout, "runtime error: <message>" on stderr, exit 101
 *
 * The %.6f formatting of finite doubles was checked against Python's formatting
 * on 4,000+ values, including random bit patterns, for the C library that
 * zig cc links on Windows (UCRT). No mismatches were found (docs/LLVM_BACKEND.md).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#define FC_RUNTIME_ERROR_EXIT 101

/* Called once from the generated C `main` before any MiniLang code runs. */
void fc_runtime_init(void) {
#ifdef _WIN32
    /* Text mode would turn "\n" into "\r\n"; MiniLang output is exactly "\n". */
    _setmode(_fileno(stdout), _O_BINARY);
#endif
}

void fc_print_i64(int64_t value) { printf("%lld\n", (long long)value); }

void fc_print_bool(int32_t value) { fputs(value ? "true\n" : "false\n", stdout); }

void fc_print_f64(double value) {
    if (isnan(value)) {
        fputs("nan\n", stdout);
    } else if (isinf(value)) {
        fputs(value > 0 ? "inf\n" : "-inf\n", stdout);
    } else {
        printf("%.6f\n", value);
    }
}

static void fc_die(const char *message) {
    fflush(stdout); /* output printed before the error is part of observable behaviour */
    fprintf(stderr, "runtime error: %s\n", message);
    exit(FC_RUNTIME_ERROR_EXIT);
}

void fc_trap_division(void) { fc_die("division by zero"); }

void fc_trap_remainder(void) { fc_die("remainder by zero"); }

void fc_trap_bounds(int64_t index, int64_t length) {
    fflush(stdout);
    fprintf(stderr, "runtime error: index %lld out of bounds for array of length %lld\n",
            (long long)index, (long long)length);
    exit(FC_RUNTIME_ERROR_EXIT);
}
