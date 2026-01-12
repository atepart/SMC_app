"""SIS junction impedance calculations."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import imag, log, pi

from .impedance import ImpedanceCalculator
from .models import FilmConductivity

MU0 = 4.0 * pi * 1e-7


@dataclass
class SISJunctionCalculator:
    """Impedance calculator for SIS junctions."""
    impedance: ImpedanceCalculator

    def impedance_sis(
        self,
        frequency_ghz: float,
        area_um2: float,
        rn_area_ohm_um2: float,
        capacitance_f_per_um2: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
        insulator_thickness_m: float,
        width_um: float = 4.0,
    ) -> complex:
        """Calculate SIS junction impedance.

        Args:
            frequency_ghz: Frequency in GHz.
            area_um2: Junction area in um^2.
            rn_area_ohm_um2: Normal resistance-area product in Ohm*um^2.
            capacitance_f_per_um2: Capacitance per unit area in F/um^2.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
            insulator_thickness_m: Insulator thickness in meters.
            width_um: Junction width in um.
        """
        z0 = 1.0 / (1.0 / rn_area_ohm_um2 + 1j * 2 * pi * frequency_ghz * 1e9 * capacitance_f_per_um2) / area_um2

        lambda_f_top = imag(self.impedance.film_impedance(frequency_ghz, top_film, top_thickness_m))
        lambda_f_bot = imag(self.impedance.film_impedance(frequency_ghz, bot_film, bot_thickness_m))
        l_sis = (lambda_f_top + lambda_f_bot + 2.0 * pi * frequency_ghz * 1e9 * MU0 * insulator_thickness_m / 2.0) * 0.5 * log(
            width_um * width_um / area_um2
        )

        return 1j * l_sis + z0
