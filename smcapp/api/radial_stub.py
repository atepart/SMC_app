"""Radial stub admittance calculations."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import arange, pi

from .microstrip import MicrostripLineCalculator
from .models import FilmConductivity


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
        dr = 2.0e-6
        angle_rad = 2.0 * pi / 360.0 * angle_deg

        z0 = 1.0e10
        z = z0

        for radius in arange(0.0, radius_max_m - 1e-6, dr)[::-1]:
            width = radius_min_m + angle_rad * radius
            z = self.microstrip.transform_impedance(
                frequency_ghz,
                z,
                dr,
                width,
                dielectric_constant,
                insulator_thickness_m,
                top_film,
                bot_film,
                top_thickness_m,
                bot_thickness_m,
            )

        return 1.0 / z
