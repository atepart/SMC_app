"""Result aggregation helpers for network matrices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from numpy import abs, array, log10, real, sqrt


@dataclass
class ResultsCalculator:
    """Helpers for combining matrices and computing S-parameters."""

    def group(self, frequency_ghz: float, matrices: Iterable[Callable[[float], array]]):
        """Multiply a sequence of ABCD matrices evaluated at a frequency.

        Args:
            frequency_ghz: Frequency in GHz.
            matrices: Iterable of callables returning ABCD matrices.
        """
        result = array([[1.0, 0.0], [0.0, 1.0]])
        for matrix_fn in matrices:
            result = result.dot(matrix_fn(frequency_ghz))
        return result

    def s21_db(
        self,
        frequency_ghz: float,
        z_gen: Callable[[float], complex],
        z_load: Callable[[float], complex],
        matrix_fn: Callable[[float], array],
    ) -> float:
        """Calculate S21 in dB for a two-port network.

        Args:
            frequency_ghz: Frequency in GHz.
            z_gen: Generator impedance function.
            z_load: Load impedance function.
            matrix_fn: Function returning the ABCD matrix.
        """
        r_load = real(z_load(frequency_ghz))
        r_gen = real(z_gen(frequency_ghz))

        matrix = matrix_fn(frequency_ghz)
        a = matrix[0][0] * z_gen(frequency_ghz) / sqrt(r_load * r_gen)
        b = matrix[0][1] * 1.0 / sqrt(r_load * r_gen)
        c = matrix[1][0] * z_load(frequency_ghz) * z_gen(frequency_ghz) / sqrt(r_load * r_gen)
        d = matrix[1][1] * z_load(frequency_ghz) / sqrt(r_load * r_gen)

        s21 = 4.0 / abs(a + b + c + d) ** 2
        return 10.0 * log10(s21)
