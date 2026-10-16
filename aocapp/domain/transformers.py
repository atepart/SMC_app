"""Presentation order and exact conversion to the legacy width-step model."""

from dataclasses import dataclass
from math import floor, isclose, isfinite

# Physical order from FFO to SIS. IDs remain stable in SI parameter files.
SCHEMATIC_SECTIONS = {
    "Mex01": ((1, "T7"), (2, "MSL8"), (3, "T6")),
    "Mex02": ((4, "MSL7"), (5, "T5"), (6, "MSL6"), (7, "T4")),
    "Mex03": ((9, "T3"), (10, "MSL5"), (11, "T2"), (12, "MSL4"), (13, "T1")),
}
ELEMENT_ORDER = (
    "T7",
    "MSL8",
    "T6",
    "MSL7",
    "T5",
    "MSL6",
    "T4",
    "DC",
    "T3",
    "MSL5",
    "T2",
    "MSL4",
    "T1",
    "SIS-line",
    "SIS",
    "Ww4",
    "Ww3",
    "Radial",
    "Ww1",
)
ELEMENT_NUMBERS = {element: number for number, element in enumerate(ELEMENT_ORDER, 1)}


def element_group(element: str) -> str:
    """One display number shared by parameter groups, diagnostics and drawing."""
    titles = {
        "DC": "DC block",
        "SIS-line": "Линия у SIS",
        "SIS": "SIS",
        "Ww4": "Radial Stub · Lw4/Ww4",
        "Ww3": "Radial Stub · Lw3/Ww3",
        "Radial": "Radial Stub",
        "Ww1": "Radial Stub · Lw1/Ww1",
    }
    title = titles.get(element, "Трансформатор" if element.startswith("T") else "Линия")
    return f"{ELEMENT_NUMBERS[element]} · {title}"


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
