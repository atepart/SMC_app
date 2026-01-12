"""Surface impedance calculations for superconducting films."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from numpy import imag, pi, real, sqrt, tanh
from scipy.interpolate import interp1d

from .models import FilmConductivity

MU0 = 4.0 * pi * 1e-7


@dataclass
class ImpedanceCalculator:
    """Surface impedance calculations for superconducting and normal films."""
    def film_impedance(self, frequency_ghz: float, film: FilmConductivity, thickness_m: float) -> complex:
        """Calculate surface impedance per square for a superconducting film.

        Args:
            frequency_ghz: Frequency in GHz.
            film: Conductivity dataset for the film.
            thickness_m: Film thickness in meters.
        """
        freq_arr, sigma1_arr, sigma2_arr = film.as_arrays()
        s1 = interp1d(freq_arr, sigma1_arr)
        s2 = interp1d(freq_arr, sigma2_arr)
        sigma = lambda freq: (s1(freq) - 1j * s2(freq))

        res = sqrt(1j * 2.0 * pi * frequency_ghz * 1e9 * MU0 / sigma(frequency_ghz) + 0j) / tanh(
            sqrt(1j * 2.0 * pi * frequency_ghz * 1e9 * MU0 * sigma(frequency_ghz) + 0j) * thickness_m
        )
        return res

    def normal_impedance(self, frequency_ghz: float, sigma0: float, thickness_m: float, tau: float = 0.0) -> complex:
        """Calculate surface impedance per square for a normal metal.

        Args:
            frequency_ghz: Frequency in GHz.
            sigma0: DC conductivity, 1/(Ohm*m).
            thickness_m: Film thickness in meters.
            tau: Relaxation time in seconds.
        """
        sigma = sigma0 / (1.0 + 1j * 2.0 * pi * frequency_ghz * 1e9 * tau)
        res = sqrt(1j * 2.0 * pi * frequency_ghz * 1e9 * MU0 / sigma + 0j) / tanh(
            sqrt(1j * 2.0 * pi * frequency_ghz * 1e9 * MU0 * sigma + 0j) * thickness_m
        )
        return res

    def datasets(self, film: FilmConductivity, thickness_m: float, name: str) -> Tuple[str, str]:
        """Write impedance datasets (Re/Im) to tab-separated files.

        Args:
            film: Conductivity dataset for the film.
            thickness_m: Film thickness in meters.
            name: Name suffix for output files.
        """
        freq_arr, sigma1_arr, sigma2_arr = film.as_arrays()
        r_dataset = []
        x_dataset = []

        for freq, s1, s2 in zip(freq_arr, sigma1_arr, sigma2_arr):
            sigma = s1 - 1j * s2
            z1 = sqrt(1j * 2.0 * pi * freq * 1e9 * MU0 / sigma + 0j) / tanh(
                sqrt(1j * 2.0 * pi * freq * 1e9 * MU0 * sigma + 0j) * thickness_m
            )
            res = z1 * (
                1.0
                - 1j * pi * freq * 1e9 * MU0 * thickness_m / z1
                + sqrt(1.0 + (1j * pi * freq * 1e9 * MU0 * thickness_m / z1) * (1j * pi * freq * 1e9 * MU0 * thickness_m / z1))
            )
            r_dataset.append(real(res))
            x_dataset.append(imag(res))

        re_file = f"Re_{name}.tab"
        im_file = f"Im_{name}.tab"

        with open(re_file, "w") as file_re:
            for freq, value in zip(freq_arr, r_dataset):
                file_re.write(f"{freq}\t{value}\n")

        with open(im_file, "w") as file_im:
            for freq, value in zip(freq_arr, x_dataset):
                file_im.write(f"{freq}\t{value}\n")

        return re_file, im_file
