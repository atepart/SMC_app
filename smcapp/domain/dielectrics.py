"""Insulator stack of the Mathcad HD35 worksheets (BUG-023 D1, WP-057).

The worksheet does not take H12/E12/H1/E1 as inputs.  It builds them from the
deposited insulator layers and the anodic Al₂O₃ grown at ``V_anod``:

* ``Ha = 1.47·1.07 nm/V · V_anod`` (``HaAl``), permittivity ``ε_Al`` (``EAl``);
* ``H1 = h1 + Ha`` and ``H12 = h1 + h2 + Ha``;
* ``E(h) = ε_i·ε_Al·(h + Ha) / (ε_i·Ha + ε_Al·h)`` — the two layers in series;
* ``E1 = E(h1)`` and ``E12 = E(h1 + h2)``.

With the worksheet inputs h1 = 0.15 µm, h2 = 0.25 µm, V = 10 V, ε_i = 4.2,
ε_Al = 9.8 this gives H12 = 0.415729 µm, E12 = 4.29281, H1 = 0.165729 µm and
E1 = 4.44084 — the numbers of Fedor's HD35-M notebook.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ANODIZATION_M_PER_V = 1.47 * 1.07e-9
"""Anodic Al₂O₃ thickness per volt of the worksheet (``HaAl = 1.47·1.07 nm·V``)."""

# Fixed by the old files that stored H12/E12/H1/E1 directly (format version ≤ 2):
# their stack is rebuilt with these anodization parameters.
LEGACY_ANOD_VOLTAGE_V = 10.0
LEGACY_EPS_INS = 4.2
LEGACY_EPS_ANOD = 9.8


@dataclass(frozen=True)
class DielectricStack:
    """Effective thickness (m) and permittivity of the two microstrip stacks."""

    h1_m: float
    e1: float
    h12_m: float
    e12: float


def anodic_thickness_m(anod_voltage_v: float) -> float:
    return ANODIZATION_M_PER_V * anod_voltage_v


def series_permittivity(insulator_m: float, anodic_m: float, eps_ins: float, eps_anod: float) -> float:
    """``E(h)`` of the worksheet: insulator *insulator_m* in series with the anodic layer."""
    return eps_ins * eps_anod * (insulator_m + anodic_m) / (eps_ins * anodic_m + eps_anod * insulator_m)


def dielectric_errors(h1_m: float, h2_m: float, anod_voltage_v: float, eps_ins: float, eps_anod: float) -> list[str]:
    """Russian messages for inputs the worksheet formulas cannot take."""
    errors = []
    values = (h1_m, h2_m, anod_voltage_v, eps_ins, eps_anod)
    if not all(math.isfinite(value) for value in values):
        return ["Диэлектрики: значения должны быть конечными числами."]
    if h1_m <= 0:
        errors.append("Диэлектрики: толщина h1 должна быть больше 0.")
    if h2_m <= 0:
        errors.append("Диэлектрики: толщина h2 должна быть больше 0.")
    if anod_voltage_v < 0:
        errors.append("Диэлектрики: напряжение анодирования V anod не может быть отрицательным.")
    if eps_ins <= 0:
        errors.append("Диэлектрики: ε i должна быть больше 0.")
    if eps_anod <= 0:
        errors.append("Диэлектрики: ε Al должна быть больше 0.")
    return errors


def dielectric_stack(
    h1_m: float, h2_m: float, anod_voltage_v: float, eps_ins: float, eps_anod: float
) -> DielectricStack:
    """H1, E1, H12, E12 from the layers; raises ``ValueError`` for invalid inputs."""
    errors = dielectric_errors(h1_m, h2_m, anod_voltage_v, eps_ins, eps_anod)
    if errors:
        raise ValueError(" ".join(errors))
    anodic = anodic_thickness_m(anod_voltage_v)
    return DielectricStack(
        h1_m=h1_m + anodic,
        e1=series_permittivity(h1_m, anodic, eps_ins, eps_anod),
        h12_m=h1_m + h2_m + anodic,
        e12=series_permittivity(h1_m + h2_m, anodic, eps_ins, eps_anod),
    )


def layers_from_legacy_stack(h1_total_m: float, h12_total_m: float) -> tuple[float, float]:
    """``(h1, h2)`` of an old file's H1/H12 at the legacy anodization (10 V)."""
    anodic = anodic_thickness_m(LEGACY_ANOD_VOLTAGE_V)
    return h1_total_m - anodic, h12_total_m - h1_total_m
