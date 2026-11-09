"""Exact conversion between transformer sizes and the legacy width-step model.

Element order and numbering live in :mod:`smcapp.domain.circuit`.
"""

from dataclasses import dataclass
from math import floor, isclose, isfinite


def transformer_slice_count(w1_m: float, w2_m: float, n_um: float) -> int:
    """Number of slices the calculator's inclusive arange makes for width step *n_um*."""
    if not all(isfinite(value) for value in (w1_m, w2_m, n_um)) or n_um <= 0:
        raise ValueError("Шаг ширины dw должен быть положительным конечным числом")
    # arange stops before max(widths) + 0.01 µm, exactly as in the backend.
    ratio = (abs(w1_m - w2_m) * 1e6 + 0.01) / n_um
    return max(1, -floor(-ratio))


def transformer_length_m(w1_m: float, w2_m: float, n_um: float, dl_m: float) -> float:
    """Match the calculator's inclusive arange, including its endpoint tolerance."""
    if not all(isfinite(value) for value in (w1_m, w2_m, n_um, dl_m)) or n_um <= 0 or dl_m <= 0:
        raise ValueError("Шаг ширины и длина ступени должны быть положительными конечными числами")
    return transformer_slice_count(w1_m, w2_m, n_um) * dl_m


@dataclass(frozen=True)
class TransformerSteps:
    n_um: int
    intervals: int
    dl_m: float


# Slice length of the automatic n/dl choice, the same for every transformer
# (owner, 09.11.2026; before that 0.5…1.5 µm and 0.5…3 µm at the DC block).
DL_MIN_UM = 0.2
DL_MAX_UM = 5.0


def derive_transformer_steps(w1_m: float, w2_m: float, length_m: float) -> TransformerSteps:
    """Choose integer n and ΔW/n without rounding the requested geometry.

    The issue's formula defines n as a width increment (µm), despite calling
    it a step count. The number of slices is ΔW/n + 1. Prefer n=2, then 4;
    otherwise choose the smallest feasible integer increment. The slice
    length dl must lie in ``DL_MIN_UM…DL_MAX_UM``.
    """
    if not all(isfinite(value) and value > 0 for value in (w1_m, w2_m, length_m)):
        raise ValueError("W1, W2 и L должны быть положительными конечными числами")
    delta_um = abs(w1_m - w2_m) * 1e6
    delta = round(delta_um)
    if not isclose(delta_um, delta, abs_tol=1e-7, rel_tol=0):
        raise ValueError("Разность W1 и W2 должна быть целой в µm для целых dw и |W1−W2|/dw")
    candidates = []
    for n in range(1, max(delta, 4) + 1):
        if delta % n:
            continue
        intervals = delta // n
        dl_um = length_m * 1e6 / (intervals + 1)
        if DL_MIN_UM - 1e-9 <= dl_um <= DL_MAX_UM + 1e-9:
            candidates.append(TransformerSteps(n, intervals, dl_um * 1e-6))
    if not candidates:
        raise ValueError(f"Для W1, W2 и L нет целого dw с целым |W1−W2|/dw и dl от {DL_MIN_UM:g} до {DL_MAX_UM:g} µm")
    return min(candidates, key=lambda steps: (0 if steps.n_um == 2 else 1 if steps.n_um == 4 else 2, steps.n_um))
