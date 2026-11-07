"""Shared data models for API calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class FilmConductivity:
    """Conductivity dataset for a superconducting film.

    Attributes:
        frequencies_ghz: Frequency points in GHz.
        sigma1: Real part of conductivity at the frequency points, 1/(Ohm*m).
        sigma2: Imaginary part of conductivity at the frequency points, 1/(Ohm*m).
        Values can be complex if numerical integration introduces small imaginary parts.
    """

    frequencies_ghz: Sequence[float]
    sigma1: Sequence[complex]
    sigma2: Sequence[complex]

    def as_arrays(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the dataset as NumPy arrays."""
        return (
            np.asarray(self.frequencies_ghz, dtype=float),
            np.asarray(self.sigma1, dtype=complex),
            np.asarray(self.sigma2, dtype=complex),
        )

    def as_tuple(self) -> Tuple[Sequence[float], Sequence[complex], Sequence[complex]]:
        """Return the dataset as a tuple of sequences."""
        return (self.frequencies_ghz, self.sigma1, self.sigma2)
