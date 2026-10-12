"""Presentation order and exact conversion to the legacy width-step model."""

from dataclasses import dataclass
from math import floor, isclose, isfinite

# Physical order from FFO to SIS. IDs remain stable in SI parameter files.
SCHEMATIC_SECTIONS = {
    "Mex01": ((1, "T7"), (2, "MSL8"), (3, "T6")),
    "Mex02": ((4, "MSL7"), (5, "T5"), (6, "MSL6"), (7, "T4")),
    "Mex03": ((8, "T3"), (9, "MSL5"), (10, "T2"), (11, "MSL4"), (12, "T1")),
}
ELEMENT_NUMBERS = {element: number for sections in SCHEMATIC_SECTIONS.values() for number, element in sections}


def transformer_length_m(w1_m: float, w2_m: float, n_um: float, dl_m: float) -> float:
    """Match the calculator's inclusive arange, including its endpoint tolerance."""
    if not all(isfinite(value) for value in (w1_m, w2_m, n_um, dl_m)) or n_um <= 0 or dl_m <= 0:
        raise ValueError("Шаг ширины и длина ступени должны быть положительными конечными числами")
    # arange stops before max(widths) + 0.01 µm, exactly as in the backend.
    ratio = (abs(w1_m - w2_m) * 1e6 + 0.01) / n_um
    count = max(1, -floor(-ratio))
    return count * dl_m


@dataclass(frozen=True)
class TransformerSteps:
    n_um: int
    intervals: int
    dl_m: float


def derive_transformer_steps(w1_m: float, w2_m: float, length_m: float) -> TransformerSteps:
    """Choose integer n and ΔW/n without rounding the requested geometry.

    The issue's formula defines n as a width increment (µm), despite calling
    it a step count. The number of slices is ΔW/n + 1. Prefer n=2, then 4;
    otherwise choose the smallest feasible integer increment.
    """
    if not all(isfinite(value) and value > 0 for value in (w1_m, w2_m, length_m)):
        raise ValueError("W1, W2 и L должны быть положительными конечными числами")
    delta_um = abs(w1_m - w2_m) * 1e6
    delta = round(delta_um)
    if not isclose(delta_um, delta, abs_tol=1e-7, rel_tol=0):
        raise ValueError("Разность W1 и W2 должна быть целой в µm для целых n и |W1−W2|/n")
    candidates = []
    for n in range(1, max(delta, 4) + 1):
        if delta % n:
            continue
        intervals = delta // n
        dl_um = length_m * 1e6 / (intervals + 1)
        if 0.5 - 1e-9 <= dl_um <= 1.5 + 1e-9:
            candidates.append(TransformerSteps(n, intervals, dl_um * 1e-6))
    if not candidates:
        raise ValueError("Для W1, W2 и L нет целого n с целым |W1−W2|/n и dl от 0.5 до 1.5 µm")
    return min(candidates, key=lambda steps: (0 if steps.n_um == 2 else 1 if steps.n_um == 4 else 2, steps.n_um))
