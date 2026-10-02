"""Small statistics helpers (no SciPy dependency): correlations used by the experiments."""

from __future__ import annotations

import math


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient (linear association), in [-1, 1]."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("need two equally long sequences of length >= 2")
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def ranks(values: list[float]) -> list[float]:
    """1-based ranks; ties get the average of the ranks they span."""
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            result[order[k]] = average
        i = j + 1
    return result


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation: Pearson correlation of the ranks (monotone association)."""
    return pearson(ranks(xs), ranks(ys))
