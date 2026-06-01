"""Simple file input/output helpers."""

from __future__ import annotations

from pathlib import Path
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
        output_path = Path(filename).expanduser()
        if output_path.parent != Path("."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as file:
            for x_val, y_val in zip(x_values, y_values):
                file.write(f"{x_val}\t{y_val}\n")

    def read(self, filename: str) -> Tuple[list[float], list[float]]:
        """Read a two-column tab-separated file into lists.

        Args:
            filename: Input file path.
        """
        with Path(filename).expanduser().open("r") as file:
            lines = file.readlines()

        data0 = []
        data1 = []
        for line in lines:
            left, right = line.split("\t")
            data0.append(float(left))
            data1.append(float(right))

        return data0, data1
