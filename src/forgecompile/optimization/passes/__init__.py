"""All optimization passes. Importing this package registers them with the pass manager."""

from forgecompile.optimization.passes import (  # noqa: F401
    bce,
    constfold,
    copyprop,
    cse,
    dce,
    inline,
    licm,
    sccp,
    simplify,
    simplifycfg,
    strength,
)
