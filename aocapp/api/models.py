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
    """
    frequencies_ghz: Sequence[float]
    sigma1: Sequence[float]
    sigma2: Sequence[float]

    def as_arrays(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the dataset as NumPy arrays."""
        return (
            np.asarray(self.frequencies_ghz, dtype=float),
            np.asarray(self.sigma1, dtype=float),
            np.asarray(self.sigma2, dtype=float),
        )

    def as_tuple(self) -> Tuple[Sequence[float], Sequence[float], Sequence[float]]:
        """Return the dataset as a tuple of sequences."""
        return (self.frequencies_ghz, self.sigma1, self.sigma2)
