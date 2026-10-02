"""ForgeCompile: an ML-guided optimizing compiler for MiniLang.

Pipeline (see docs/ARCHITECTURE.md):

    MiniLang source -> tokens -> AST -> checked AST -> ForgeCompile IR
    -> optimized IR -> LLVM IR -> native executable
"""

__version__ = "0.0.1"
