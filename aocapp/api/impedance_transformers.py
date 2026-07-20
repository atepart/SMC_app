"""Step impedance transformer calculations."""

from __future__ import annotations

from dataclasses import dataclass

from numpy import arange, array

from .microstrip import MicrostripLineCalculator
from .models import FilmConductivity


@dataclass
class ImpedanceTransformerCalculator:
    """Step impedance transformer calculator."""

    microstrip: MicrostripLineCalculator

    def transformer_matrix(
        self,
        frequency_ghz: float,
        width_start_m: float,
        width_end_m: float,
        width_step_per_length_um: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
        length_step_m: float = 1.0e-6,
    ):
        """Calculate the ABCD matrix for a stepped impedance transformer.

        Args:
            frequency_ghz: Frequency in GHz.
            width_start_m: Start width in meters.
            width_end_m: End width in meters.
            width_step_per_length_um: Width change per unit length in um/um.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
            length_step_m: Step length in meters.
        """
        eps = 0.01e-6
        if width_start_m < width_end_m:
            widths = arange(width_start_m, width_end_m + eps, width_step_per_length_um * 1e-6)
        else:
            widths = arange(width_end_m, width_start_m + eps, width_step_per_length_um * 1e-6)[::-1]

        res = array([[1.0, 0.0], [0.0, 1.0]], dtype=complex)

        for width in widths:
            res = res.dot(
                self.microstrip.matrix(
                    frequency_ghz,
                    length_step_m,
                    width,
                    dielectric_constant,
                    insulator_thickness_m,
                    top_film,
                    bot_film,
                    top_thickness_m,
                    bot_thickness_m,
                )
            )

        return res
