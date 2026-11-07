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


class HfssTabReader:
    """Parse an HFSS ``.tab`` export: a header row, then frequency/S21 pairs.

    HFSS writes ``"Freq [THz]"<TAB>"dB(S(2,1)) []"`` and then one row per
    frequency.  Columns may be separated by tabs, spaces, commas or
    semicolons.  The frequency unit is taken from the first ``[…Hz]`` of the
    header (THz when the header names none) and converted to GHz; the second
    column is S21 in dB.  Empty lines are skipped; any other malformed row is
    reported with its line number.
    """

    _separator = re.compile(r"[\s,;]+")
    _unit = re.compile(r"\[\s*([kMGT]?Hz)\s*\]", re.IGNORECASE)
    _to_ghz = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0, "thz": 1e3}

    def load(self, path: str | Path) -> ComparisonTrace:
        source = Path(path).expanduser()
        lines = [
            (number, text.strip())
            for number, text in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1)
            if text.strip()
        ]
        if not lines:
            raise ValueError("Файл HFSS пуст.")

        scale = self._to_ghz["thz"]
        first_number, first_line = lines[0]
        if self._pair(first_line) is None:
            # Header row such as "Freq [THz]"\t"dB(S(2,1)) []".
            unit = self._unit.search(first_line)
            if unit is not None:
                scale = self._to_ghz[unit.group(1).lower()]
            lines = lines[1:]

        rows: list[tuple[float, float]] = []
        for line_number, line in lines:
            columns = [part for part in self._separator.split(line) if part]
            if len(columns) != 2:
                raise ValueError(
                    f"Строка {line_number}: ожидалось два столбца (частота и S21), найдено {len(columns)}."
                )
            pair = self._pair(line)
            if pair is None:
                raise ValueError(f"Строка {line_number}: частота и S21 должны быть числами: {line!r}.")
            frequency, coefficient = pair
            if not math.isfinite(frequency) or not math.isfinite(coefficient):
                raise ValueError(f"Строка {line_number}: NaN и бесконечность не поддерживаются.")
            rows.append((frequency * scale, coefficient))

        if not rows:
            raise ValueError(f"Файл HFSS содержит только заголовок (строка {first_number}) и ни одной точки.")
        rows.sort(key=lambda pair: pair[0])
        return ComparisonTrace(
            frequencies=tuple(pair[0] for pair in rows),
            coefficients=tuple(pair[1] for pair in rows),
            source=source,
        )

    def _pair(self, line: str) -> tuple[float, float] | None:
        """Return the two numbers of a data row, or ``None`` when it is not one."""
        columns = [part for part in self._separator.split(line) if part]
        if len(columns) != 2:
            return None
        try:
            return float(columns[0]), float(columns[1])
        except ValueError:
            return None
