"""Simple file input/output helpers."""

from __future__ import annotations

from typing import Iterable, Tuple


class IOService:
    """Simple IO helpers for tab-separated datasets."""
    def write(self, filename: str, data: Tuple[Iterable[float], Iterable[float]]) -> None:
        """Write two-column data to a tab-separated file.

        Args:
            filename: Output file path.
            data: Tuple of x and y sequences.
        """
        x_values, y_values = data
        with open(filename, "w") as file:
            for x_val, y_val in zip(x_values, y_values):
                file.write(f"{x_val}\t{y_val}\n")

    def read(self, filename: str) -> Tuple[list[float], list[float]]:
        """Read a two-column tab-separated file into lists.

        Args:
            filename: Input file path.
        """
        with open(filename, "r") as file:
            lines = file.readlines()

        data0 = []
        data1 = []
        for line in lines:
            left, right = line.split("\t")
            data0.append(float(left))
            data1.append(float(right))

        return data0, data1
