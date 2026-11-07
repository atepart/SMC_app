"""Radial stub admittance calculations."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import pi

from .microstrip import MicrostripLineCalculator
from .models import FilmConductivity

RADIAL_STEP_M = 1.0e-6
"""Radial slice length ``ΔRAD`` of the Mathcad HD35 worksheets."""


def radial_slice_count(radius_max_m: float) -> int:
    """Return ``N = round(Rmax/ΔRAD)``, the number of radial slices."""
    return max(0, int(round(radius_max_m / RADIAL_STEP_M)))


@dataclass
class RadialStubCalculator:
    """Admittance calculation for radial stubs."""

    microstrip: MicrostripLineCalculator

    def admittance(
        self,
        frequency_ghz: float,
        radius_min_m: float,
        radius_max_m: float,
        angle_deg: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ) -> complex:
        """Calculate radial stub admittance.

        The stub is cut into ``N = round(Rmax/ΔRAD)`` microstrip slices of
        ``ΔRAD = 1 µm``.  Starting from an open end at the outer radius, slice
        ``r = N…1`` of width ``Rmin + ΔRAD·(r−1)·θ`` transforms the impedance
        toward the neck, so the stub length is exactly ``N·ΔRAD``.

        Args:
            frequency_ghz: Frequency in GHz.
            radius_min_m: Inner radius in meters.
            radius_max_m: Outer radius in meters.
            angle_deg: Stub angle in degrees.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        step = RADIAL_STEP_M
        angle_rad = 2.0 * pi / 360.0 * angle_deg

        z0 = 1.0e10
        z = z0

        # Mathcad HD35: r = N…1 from the open outer edge to the neck, each
        # slice ΔRAD long and WID[r] = Wneck + ΔRAD·(r−1)·θ wide.
        for index in range(radial_slice_count(radius_max_m), 0, -1):
            width = radius_min_m + step * (index - 1) * angle_rad
            z = self.microstrip.transform_impedance(
                frequency_ghz,
                z,
                step,
                width,
                dielectric_constant,
                insulator_thickness_m,
                top_film,
                bot_film,
                top_thickness_m,
                bot_thickness_m,
            )

        return 1.0 / z
