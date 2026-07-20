"""Read two-column comparison traces exported by measurement tools."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ComparisonTrace:
    """One immutable frequency/coefficient series displayed behind theory."""

    frequencies: tuple[float, ...]
    coefficients: tuple[float, ...]
    source: Path


class TraceFileReader:
    """Parse whitespace, comma or semicolon separated numeric pairs.

    Empty lines and ``#`` comments are ignored.  One leading textual header is
    accepted because HFSS and laboratory exports commonly include column names;
    malformed data after the first numeric row is reported with its line number.
    """

    _separator = re.compile(r"[\s,;]+")

    def load(self, path: str | Path) -> ComparisonTrace:
        source = Path(path).expanduser()
        rows: list[tuple[float, float]] = []
        skipped_header = False
        for line_number, original in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
            line = original.split("#", 1)[0].strip()
            if not line:
                continue
            columns = [part for part in self._separator.split(line) if part]
            if len(columns) != 2:
                if not rows and not skipped_header:
                    skipped_header = True
                    continue
                raise ValueError(f"Строка {line_number}: ожидалось ровно два столбца.")
            try:
                frequency, coefficient = (float(value) for value in columns)
            except ValueError as exc:
                if not rows and not skipped_header:
                    skipped_header = True
                    continue
                raise ValueError(f"Строка {line_number}: значения должны быть числами.") from exc
            if not math.isfinite(frequency) or not math.isfinite(coefficient):
                raise ValueError(f"Строка {line_number}: NaN и бесконечность не поддерживаются.")
            rows.append((frequency, coefficient))

        if not rows:
            raise ValueError("Файл не содержит числовых пар частота/коэффициент.")
        rows.sort(key=lambda pair: pair[0])
        return ComparisonTrace(
            frequencies=tuple(pair[0] for pair in rows),
            coefficients=tuple(pair[1] for pair in rows),
            source=source,
        )
