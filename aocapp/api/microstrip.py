"""Superconducting microstrip line calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from numpy import array, arctanh, cosh, exp, log, pi, sinh, sqrt, tanh

from .impedance import ImpedanceCalculator
from .models import FilmConductivity

MU0 = 4.0 * pi * 1e-7
EPS0 = 8.8542e-12


@dataclass
class MicrostripLineCalculator:
    """Microstrip line calculations for superconducting transmission lines."""
    impedance: ImpedanceCalculator

    def chi_kf1(self, width_m: float, insulator_thickness_m: float, top_thickness_m: float) -> Tuple[float, float]:
        """Compute chi and fringing field factor Kf1.

        Args:
            width_m: Microstrip width in meters.
            insulator_thickness_m: Insulator thickness in meters.
            top_thickness_m: Top electrode thickness in meters.
        """
        b = 1.0 + top_thickness_m / insulator_thickness_m
        p = 2.0 * b * b - 1.0 + 2.0 * b * sqrt(b * b - 1.0)

        ra = exp(
            -(
                1.0
                + pi * width_m / 2.0 / insulator_thickness_m
                + (p + 1.0) / sqrt(p) * arctanh(1.0 / sqrt(p))
                + log((p - 1.0) / 4.0 / p)
            )
        )
        ln_ra = (
            1.0
            + pi * width_m / 2.0 / insulator_thickness_m
            + (p + 1.0) / sqrt(p) * arctanh(1.0 / sqrt(p))
            + log((p - 1.0) / 4.0 / p)
        )
        eta = sqrt(p) * (
            pi * width_m / 2.0 / insulator_thickness_m
            + (p + 1.0) / 2.0 / sqrt(p) * (1.0 + log(4.0 / (p - 1.0)))
            - 2.0 * arctanh(1.0 / sqrt(p))
        )

        rbo = eta + (p + 1.0) / 2.0 * log(eta)
        rb1 = (
            rbo
            - sqrt((rbo - 1.0) * (rbo - p))
            + (p + 1.0) * arctanh(sqrt((rbo - p) / (rbo - 1.0)))
            - 2.0 * sqrt(p) * arctanh(sqrt((rbo - p) / p / (rbo - 1.0)))
            + pi * width_m * sqrt(p) / 2.0 / insulator_thickness_m
        )

        rb = rbo if width_m / insulator_thickness_m > 5 else rb1

        kfo = 2.0 * insulator_thickness_m / pi / width_m * (log(2.0 * rbo / ra))
        kf1 = 2.0 * insulator_thickness_m / pi / width_m * (log(2.0 * rb) + ln_ra)

        ra_val = (1.0 - ra) * (p - ra)
        is1 = log((2.0 * p - ra * (p + 1.0) + 2.0 * sqrt(p * ra_val)) / ra / (p - 1.0))

        rb_val = (rb - 1.0) * (rb - p)
        is2 = -log((-2.0 * p + rb * (p + 1.0) - 2.0 * sqrt(p * rb_val)) / rb / (p - 1.0))

        rbb = (rb + 1.0) * (rb + p)
        ig1 = -log((2.0 * p + rb * (p + 1.0) + 2.0 * sqrt(p * rbb)) / rb / (p - 1.0))

        raa = (ra + 1.0) * (ra + p)
        ig2 = log((2.0 * p + ra * (p + 1.0) + 2.0 * sqrt(p * raa)) / ra / (p - 1.0))

        chi = (is1 + is2 + ig1 + ig2 + pi) / 2.0 / log(2.0 * rb / ra)

        return chi, kf1

    def characteristic_impedance(
        self,
        frequency_ghz: float,
        width_m: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ) -> complex:
        """Calculate characteristic impedance of a microstrip line.

        Args:
            frequency_ghz: Frequency in GHz.
            width_m: Line width in meters.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        chi, kf1 = self.chi_kf1(width_m, insulator_thickness_m, top_thickness_m)
        g1 = insulator_thickness_m / width_m / kf1

        z_top = self.impedance.film_impedance(frequency_ghz, top_film, top_thickness_m)
        z_bot = self.impedance.film_impedance(frequency_ghz, bot_film, bot_thickness_m)

        res = (
            120.0
            * pi
            * g1
            / sqrt(dielectric_constant)
            * sqrt(1.0 - 1j * chi * (z_top + z_bot) / 2.0 / pi / frequency_ghz / 1e9 / 120.0 / pi / insulator_thickness_m / sqrt(EPS0 * MU0) + 0j)
        )
        return res

    def propagation_constant(
        self,
        frequency_ghz: float,
        width_m: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ) -> complex:
        """Calculate the propagation constant gamma for a microstrip line.

        Args:
            frequency_ghz: Frequency in GHz.
            width_m: Line width in meters.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        chi, _ = self.chi_kf1(width_m, insulator_thickness_m, top_thickness_m)

        z_top = self.impedance.film_impedance(frequency_ghz, top_film, top_thickness_m)
        z_bot = self.impedance.film_impedance(frequency_ghz, bot_film, bot_thickness_m)

        res = 1j * 2.0 * pi * frequency_ghz * 1e9 * sqrt(dielectric_constant * EPS0 * MU0) * sqrt(
            1.0 - 1j * chi * (z_top + z_bot) / 2.0 / pi / frequency_ghz / 1e9 / 120.0 / pi / insulator_thickness_m / sqrt(EPS0 * MU0)
        )
        return res

    def matrix(
        self,
        frequency_ghz: float,
        length_m: float,
        width_m: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ) -> complex:
        """Return the ABCD matrix for a microstrip line segment.

        Args:
            frequency_ghz: Frequency in GHz.
            length_m: Segment length in meters.
            width_m: Line width in meters.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        zo = self.characteristic_impedance(
            frequency_ghz,
            width_m,
            dielectric_constant,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )
        gamma = self.propagation_constant(
            frequency_ghz,
            width_m,
            dielectric_constant,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )

        a = cosh(gamma * length_m)
        b = zo * sinh(gamma * length_m)
        c = 1.0 / zo * sinh(gamma * length_m)
        d = cosh(gamma * length_m)

        return array([[a, b], [c, d]], dtype=complex)

    def transform_impedance(
        self,
        frequency_ghz: float,
        load_impedance: complex,
        length_m: float,
        width_m: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ) -> complex:
        """Transform a load impedance through a microstrip section.

        Args:
            frequency_ghz: Frequency in GHz.
            load_impedance: Load impedance to transform.
            length_m: Segment length in meters.
            width_m: Line width in meters.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        zo = self.characteristic_impedance(
            frequency_ghz,
            width_m,
            dielectric_constant,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )
        gamma = self.propagation_constant(
            frequency_ghz,
            width_m,
            dielectric_constant,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )
        return zo * (load_impedance + zo * tanh(gamma * length_m)) / (zo + load_impedance * tanh(gamma * length_m))

    def transform_admittance(
        self,
        frequency_ghz: float,
        load_admittance: complex,
        length_m: float,
        width_m: float,
        dielectric_constant: float,
        insulator_thickness_m: float,
        top_film: FilmConductivity,
        bot_film: FilmConductivity,
        top_thickness_m: float,
        bot_thickness_m: float,
    ) -> complex:
        """Transform a load admittance through a microstrip section.

        Args:
            frequency_ghz: Frequency in GHz.
            load_admittance: Load admittance to transform.
            length_m: Segment length in meters.
            width_m: Line width in meters.
            dielectric_constant: Relative permittivity.
            insulator_thickness_m: Insulator thickness in meters.
            top_film: Top film conductivity dataset.
            bot_film: Bottom film conductivity dataset.
            top_thickness_m: Top film thickness in meters.
            bot_thickness_m: Bottom film thickness in meters.
        """
        yo = 1.0 / self.characteristic_impedance(
            frequency_ghz,
            width_m,
            dielectric_constant,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )
        gamma = self.propagation_constant(
            frequency_ghz,
            width_m,
            dielectric_constant,
            insulator_thickness_m,
            top_film,
            bot_film,
            top_thickness_m,
            bot_thickness_m,
        )
        return yo * (load_admittance + yo * tanh(gamma * length_m)) / (yo + load_admittance * tanh(gamma * length_m))
