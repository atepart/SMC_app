"""Read two-column comparison traces (HFSS, experiment): frequency and S21 in dB.

Reading and units are separate steps (``BUG-024``): :func:`read_trace_table`
parses the numbers as written and reports the frequency unit found in the
header of the frequency column, then :func:`convert_trace` converts to GHz once
with the unit the user confirmed.  HFSS and Experiment share both steps; the
kind only chooses the curve on the plot, never the unit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

# Supported frequency units and their factors to GHz, the plot's internal unit.
FREQUENCY_UNITS: dict[str, float] = {"Hz": 1e-9, "kHz": 1e-6, "MHz": 1e-3, "GHz": 1.0, "THz": 1e3}
_UNIT_BY_LOWER = {unit.lower(): unit for unit in FREQUENCY_UNITS}


@dataclass(frozen=True)
class TraceTable:
    """Numbers of a comparison file exactly as written, before any unit conversion.

    ``header_unit`` is the frequency unit named in the header of the first
    column, or ``None``; ``unit_note`` then says why it is not known.
    """

    frequencies: tuple[float, ...]
    coefficients: tuple[float, ...]
    source: Path
    header: str | None
    header_unit: str | None
    unit_note: str


@dataclass(frozen=True)
class ComparisonTrace:
    """One immutable frequency/coefficient series displayed behind theory.

    ``frequencies`` are in GHz; ``unit`` is the unit of the file and
    ``unit_source`` tells where it came from (header or the user's choice).
    """

    frequencies: tuple[float, ...]
    coefficients: tuple[float, ...]
    source: Path
    unit: str = "GHz"
    unit_source: str = ""


_SEPARATOR = re.compile(r"[\s,;]+")
# A unit mentioned as a word of its own: "Freq [GHz]", "Freq (GHz)", "f_GHz", "GHz".
_UNIT_WORD = re.compile(r"(?<![A-Za-z])([kKmMgGtT]?[hH][zZ])(?![A-Za-z])")
_BRACKETS = re.compile(r"[\[(]\s*([^\])]*?)\s*[\])]")


def frequency_column_header(header: str) -> str:
    """The header text of the first (frequency) column."""
    text = header.strip().lstrip("﻿")
    quoted = re.match(r'"([^"]*)"', text)
    if quoted:  # HFSS quotes every column name
        return quoted.group(1).strip()
    # Tabs and semicolons first: a comma may sit inside a later name, "dB(S(2,1))".
    for separator in (r"\t|;", ","):
        columns = [part for part in re.split(separator, text) if part.strip()]
        if len(columns) >= 2:
            return columns[0].strip()
    # Space-separated: keep a bracketed unit with its column name ("Freq [GHz] S21 [dB]").
    words = re.findall(r'"[^"]*"|[^\s\[(]+(?:\s*[\[(][^\])]*[\])])?|[\[(][^\])]*[\])]', text)
    return words[0].strip('"').strip() if words else ""


def detect_frequency_unit(header: str | None) -> tuple[str | None, str]:
    """Unit named in the frequency column of *header*, or ``None`` and the reason."""
    if header is None:
        return None, "в файле нет заголовка с единицей частоты"
    column = frequency_column_header(header)
    units = {_UNIT_BY_LOWER[match.lower()] for match in _UNIT_WORD.findall(column)}
    if len(units) == 1:
        return units.pop(), f"из заголовка «{column}»"
    if len(units) > 1:
        return (
            None,
            f"в заголовке «{column}» несколько единиц: {', '.join(sorted(units, key=list(FREQUENCY_UNITS).index))}",
        )
    bracketed = [text for text in _BRACKETS.findall(column) if text]
    if bracketed:
        return None, f"единица «{bracketed[0]}» в заголовке «{column}» не поддерживается"
    return None, f"в заголовке «{column}» нет единицы частоты"


def _numbers(line: str) -> tuple[list[str], tuple[float, float] | None]:
    columns = [part for part in _SEPARATOR.split(line) if part]
    if len(columns) != 2:
        return columns, None
    try:
        return columns, (float(columns[0]), float(columns[1]))
    except ValueError:
        return columns, None


def read_trace_table(path: str | Path) -> TraceTable:
    """Parse whitespace, comma or semicolon separated frequency/S21 pairs.

    Empty lines and ``#`` comments are skipped.  One textual header before the
    data is allowed; any other malformed row is reported with its line number.
    Frequencies stay as written: no unit is assumed here.
    """
    source = Path(path).expanduser()
    try:
        text = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        hint = " Это проект Origin: выгрузите лист в текст (.txt/.dat)." if source.suffix.lower() == ".opj" else ""
        raise ValueError(f"Файл не является текстовой таблицей (UTF-8).{hint}") from exc
    header: str | None = None
    header_line = 0
    rows: list[tuple[float, float]] = []
    for line_number, original in enumerate(text.splitlines(), start=1):
        line = original.split("#", 1)[0].strip()
        if not line:
            continue
        columns, pair = _numbers(line)
        if pair is None:
            if not rows and header is None:
                header, header_line = line, line_number
                continue
            if len(columns) != 2:
                raise ValueError(
                    f"Строка {line_number}: ожидалось два столбца (частота и S21), найдено {len(columns)}."
                )
            raise ValueError(f"Строка {line_number}: частота и S21 должны быть числами: {line!r}.")
        if not all(math.isfinite(value) for value in pair):
            raise ValueError(f"Строка {line_number}: NaN и бесконечность не поддерживаются.")
        rows.append(pair)

    if not rows:
        if header is not None:
            raise ValueError(f"Файл содержит только заголовок (строка {header_line}) и ни одной пары частота/S21.")
        raise ValueError("Файл пуст: нет ни одной пары частота/S21.")
    rows.sort(key=lambda pair: pair[0])
    unit, note = detect_frequency_unit(header)
    return TraceTable(
        frequencies=tuple(pair[0] for pair in rows),
        coefficients=tuple(pair[1] for pair in rows),
        source=source,
        header=header,
        header_unit=unit,
        unit_note=note,
    )


def convert_trace(table: TraceTable, unit: str, unit_source: str) -> ComparisonTrace:
    """Convert the table's frequencies from *unit* to GHz, exactly once."""
    if unit not in FREQUENCY_UNITS:
        raise ValueError(f"Неизвестная единица частоты: {unit}.")
    factor = FREQUENCY_UNITS[unit]
    return ComparisonTrace(
        frequencies=tuple(value * factor for value in table.frequencies),
        coefficients=table.coefficients,
        source=table.source,
        unit=unit,
        unit_source=unit_source,
    )
