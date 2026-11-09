"""Read comparison traces (HFSS, experiment) from text tables.

Reading, choosing columns and units are separate steps (``BUG-024``, ``WP-055``):
:func:`read_data_table` parses every column of the file as written, finding the
column separator and the decimal mark itself unless they are given;
:func:`select_trace` takes the X (frequency) and Y columns and reports the
frequency unit named in the header of the X column; :func:`convert_trace`
converts the frequencies to GHz once, with the unit the user confirmed, and
records what the Y values are (:data:`Y_QUANTITIES`).  HFSS and Experiment
share all steps; the kind only chooses the curve on the plot, never the unit.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

# Supported frequency units and their factors to GHz, the plot's internal unit.
FREQUENCY_UNITS: dict[str, float] = {"Hz": 1e-9, "kHz": 1e-6, "MHz": 1e-3, "GHz": 1.0, "THz": 1e3}
_UNIT_BY_LOWER = {unit.lower(): unit for unit in FREQUENCY_UNITS}

# Column separators by key, with the dialog's names.  "any" is the old reader:
# whitespace, commas and semicolons in any mix, decimal point only.
SEPARATORS: dict[str, str] = {
    "tab": "Табуляция",
    "semicolon": "Точка с запятой «;»",
    "space": "Пробелы и табуляция",
    "comma": "Запятая «,»",
    "any": "Любой (пробелы, «,», «;»)",
}
DECIMAL_MARKS: dict[str, str] = {".": "Точка «.»", ",": "Запятая «,»"}
# Tried in this order; the one that reads the most data rows wins, ties by order.
# Columns are usually split by tabs or spaces and a comma is a decimal mark
# (owner, 09.11.2026), so a comma between columns ("comma", and "any" which
# mixes it in) comes last: it wins only when it reads more rows, i.e. when the
# whitespace readings would have taken data rows for a header.
_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("tab", "."),
    ("tab", ","),
    ("semicolon", "."),
    ("semicolon", ","),
    ("space", "."),
    ("space", ","),
    ("comma", "."),
    ("any", "."),
)


@dataclass(frozen=True)
class YQuantity:
    """What the Y column holds and where it is drawn.

    ``axis`` is ``"left"`` (S21 in dB, with the calculation) or ``"right"``
    (current).  ``logarithmic`` values are already log10 of the quantity and
    are drawn on a linear right axis; plain current goes on a log-scale one.
    """

    key: str
    title: str
    axis: str
    family: str
    unit: str
    factor: float = 1.0
    logarithmic: bool = False

    @property
    def axis_label(self) -> str:
        if self.family == "s21":
            return "S21, dB"
        if self.family == "normalized":
            return "log₁₀(I/I_g)" if self.logarithmic else "I/I_g"
        return f"log₁₀(I / {self.unit})" if self.logarithmic else f"I, {self.unit}"

    @property
    def placement(self) -> str:
        if self.axis == "left":
            return "левая ось, вместе с остальными кривыми"
        if self.logarithmic:
            return "правая ось, линейная шкала (значения уже логарифм)"
        return "правая ось, логарифмическая шкала"


def _current(key: str, unit: str, factor: float, logarithmic: bool) -> YQuantity:
    title = f"I, {unit}" if unit else "I/I_g"
    return YQuantity(
        key=key,
        title=f"{title} Log" if logarithmic else title,
        axis="right",
        family="current" if unit else "normalized",
        unit=unit,
        factor=factor,
        logarithmic=logarithmic,
    )


Y_QUANTITIES: dict[str, YQuantity] = {
    "dB": YQuantity(key="dB", title="S21, dB", axis="left", family="s21", unit="dB"),
    "A": _current("A", "A", 1.0, False),
    "mA": _current("mA", "mA", 1e-3, False),
    "µA": _current("µA", "µA", 1e-6, False),
    "I/Ig": _current("I/Ig", "", 1.0, False),
    "A log": _current("A log", "A", 1.0, True),
    "mA log": _current("mA log", "mA", 1e-3, True),
    "µA log": _current("µA log", "µA", 1e-6, True),
    "I/Ig log": _current("I/Ig log", "", 1.0, True),
}


@dataclass(frozen=True)
class DataTable:
    """Every column of a text table exactly as written; empty cells are ``None``."""

    source: Path
    columns: tuple[str, ...]
    rows: tuple[tuple[float | None, ...], ...]
    header_lines: tuple[str, ...]
    separator: str
    decimal: str
    # Header text of each column (all header rows joined), ``None`` if unknown.
    column_headers: tuple[str | None, ...] = ()

    @property
    def header(self) -> str | None:
        return self.header_lines[0] if self.header_lines else None

    def column_header(self, index: int) -> str | None:
        return self.column_headers[index] if index < len(self.column_headers) else None


@dataclass(frozen=True)
class TraceTable:
    """The X/Y columns of a comparison file as written, before any unit conversion.

    ``header_unit`` is the frequency unit named in the header of the X column,
    or ``None``; ``unit_note`` then says why it is not known.
    """

    frequencies: tuple[float, ...]
    coefficients: tuple[float, ...]
    source: Path
    header: str | None
    header_unit: str | None
    unit_note: str
    x_name: str = "Столбец 1"
    y_name: str = "Столбец 2"
    skipped_rows: int = 0


@dataclass(frozen=True)
class ComparisonTrace:
    """One immutable frequency/Y series displayed behind theory.

    ``frequencies`` are in GHz; ``unit`` is the unit of the file and
    ``unit_source`` tells where it came from (header or the user's choice).
    ``quantity`` is a key of :data:`Y_QUANTITIES`: dB on the left axis, current
    on the right one.
    """

    frequencies: tuple[float, ...]
    coefficients: tuple[float, ...]
    source: Path
    unit: str = "GHz"
    unit_source: str = ""
    quantity: str = "dB"

    @property
    def y_quantity(self) -> YQuantity:
        return Y_QUANTITIES[self.quantity]


# A unit mentioned as a word of its own: "Freq [GHz]", "Freq (GHz)", "f_GHz", "GHz".
_UNIT_WORD = re.compile(r"(?<![A-Za-z])([kKmMgGtT]?[hH][zZ])(?![A-Za-z])")
_BRACKETS = re.compile(r"[\[(]\s*([^\])]*?)\s*[\])]")
# Space-separated header words, keeping a bracketed unit with its name ("Freq [GHz] S21 [dB]").
_HEADER_WORDS = re.compile(r'"[^"]*"|[^\s\[(]+(?:\s*[\[(][^\])]*[\])])?|[\[(][^\])]*[\])]')
_SPECIAL_NUMBER = re.compile(r"[+-]?(nan|inf|infinity)", re.IGNORECASE)


def _number_pattern(decimal: str) -> re.Pattern[str]:
    mark = re.escape(decimal)
    # "100." is a number, "100," is not: a trailing comma is a separator ("100, -12.5").
    fraction = r"\d*" if decimal == "." else r"\d+"
    return re.compile(rf"[+-]?(?:\d+(?:{mark}{fraction})?|{mark}\d+)(?:[eE][+-]?\d+)?")


_NUMBERS = {mark: _number_pattern(mark) for mark in DECIMAL_MARKS}


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
    words = _HEADER_WORDS.findall(text)
    return words[0].strip('"').strip() if words else ""


def detect_unit_in_column(column: str) -> tuple[str | None, str]:
    """Frequency unit named in one column's header text, or ``None`` and the reason."""
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


def detect_frequency_unit(header: str | None) -> tuple[str | None, str]:
    """Unit named in the frequency (first) column of *header*, or ``None`` and the reason."""
    if header is None:
        return None, "в файле нет заголовка с единицей частоты"
    return detect_unit_in_column(frequency_column_header(header))


_CURRENT_UNITS = {"a": "A", "ma": "mA", "µa": "µA", "μa": "µA", "ua": "µA", "а": "A", "ма": "mA", "мка": "µA"}


def detect_y_quantity(column: str | None) -> str | None:
    """Guess the Y quantity from a column header ("S21 [dB]", "I (mA)", "lg I/Ig"); ``None`` if unclear."""
    if not column:
        return None
    text = column.strip().lower()
    logarithmic = re.search(r"(?<![a-z])(log|lg|log10)(?![a-z])", text) is not None
    suffix = " log" if logarithmic else ""
    if re.search(r"(?<![a-z])i\s*/\s*i_?g(?![a-z])", text):
        return "I/Ig" + suffix
    if re.search(r"(?<![a-z])db(?![a-z])", text):
        return "dB"
    candidates = _BRACKETS.findall(text) + [part.strip() for part in re.split(r"[,_]", text)[1:]]
    for candidate in candidates:
        unit = _CURRENT_UNITS.get(candidate.strip())
        if unit is not None:
            return unit + suffix
    return None


def _read_text(source: Path) -> str:
    try:
        return source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        hint = " Это проект Origin: выгрузите лист в текст (.txt/.dat)." if source.suffix.lower() == ".opj" else ""
        raise ValueError(f"Файл не является текстовой таблицей (UTF-8).{hint}") from exc


def _split(line: str, separator: str) -> list[str]:
    """Cells of one line; quoted names may contain the separator ("dB(S(2,1))")."""
    if separator == "space":
        return [cell.strip('"').strip() for cell in _HEADER_WORDS.findall(line)]
    if separator == "any":
        return [cell for cell in re.split(r"[\s,;]+", line) if cell]
    delimiter = {"tab": "\t", "semicolon": ";", "comma": ","}[separator]
    cells = [cell.strip() for cell in next(csv.reader([line], delimiter=delimiter, skipinitialspace=True))]
    while cells and not cells[-1]:
        cells.pop()  # trailing separators: Origin pads short columns
    return cells


def _split_data(line: str, separator: str) -> list[str]:
    if separator == "space":
        return line.split()
    return _split(line, separator)


def _value(cell: str, decimal: str) -> float | None | str:
    """A number, ``None`` for an empty cell, or the marker ``"nan"``; raises for text."""
    if not cell:
        return None
    if _SPECIAL_NUMBER.fullmatch(cell):
        return "nan"
    if not _NUMBERS[decimal].fullmatch(cell):
        raise ValueError(cell)
    return float(cell.replace(",", ".")) if decimal == "," else float(cell)


_SEPARATOR_HINT = " Возможно, выбран не тот разделитель столбцов или десятичный разделитель."


@dataclass
class _Attempt:
    separator: str
    decimal: str
    rows: list[tuple[float | None, ...]]
    header_lines: list[tuple[int, str]]
    error: str | None = None
    empty_cells: int = 0


def _attempt(lines: list[tuple[int, str]], separator: str, decimal: str) -> _Attempt:
    attempt = _Attempt(separator, decimal, [], [])
    width = 0
    for line_number, line in lines:
        cells = _split_data(line, separator)
        try:
            values = [_value(cell, decimal) for cell in cells]
        except ValueError:
            values = None
        if not attempt.rows and (values is None or all(value is None for value in values)):
            attempt.header_lines.append((line_number, line))
            continue
        if not attempt.rows:
            width = len(cells)
            if width < 2:
                attempt.error = f"Строка {line_number}: нужно минимум два столбца (X и Y), найден {width}."
                return attempt
        if len(cells) > width or (len(cells) < width and separator in ("space", "any")):
            attempt.error = f"Строка {line_number}: ожидалось {width} столбца, найдено {len(cells)}."
            return attempt
        if values is None:
            attempt.error = f"Строка {line_number}: значения должны быть числами: {line!r}."
            return attempt
        if "nan" in values:
            attempt.error = f"Строка {line_number}: NaN и бесконечность не поддерживаются."
            return attempt
        if any(value is not None and not math.isfinite(value) for value in values):
            attempt.error = f"Строка {line_number}: NaN и бесконечность не поддерживаются."
            return attempt
        values += [None] * (width - len(values))
        attempt.empty_cells += sum(value is None for value in values)
        attempt.rows.append(tuple(values))  # type: ignore[arg-type]
    if not attempt.rows:
        if attempt.header_lines:
            attempt.error = (
                f"Файл содержит только заголовок (строка {attempt.header_lines[0][0]}) и ни одной строки с числами."
                + (_SEPARATOR_HINT if any(re.search(r"\d", line) for _n, line in attempt.header_lines) else "")
            )
        else:
            attempt.error = "Файл пуст: нет ни одной строки с числами."
    return attempt


def _column_headers(header_lines: list[str], separator: str, width: int) -> tuple[str | None, ...]:
    """Header text of each column from every header row that splits into *width* cells."""
    parts: list[list[str]] = [[] for _ in range(width)]
    for line in header_lines:
        cells = _split(line, separator)
        if separator == "any" and len(cells) != width:
            cells = _split(line, "space")
        if len(cells) != width:
            continue
        for index, cell in enumerate(cells):
            if cell:
                parts[index].append(cell)
    return tuple(", ".join(part) if part else None for part in parts)


def read_data_table(path: str | Path, separator: str | None = None, decimal: str | None = None) -> DataTable:
    """Parse a text table with two or more numeric columns.

    Empty lines and ``#`` comments are skipped; text rows before the first
    numeric row are the header (Origin writes names, units and comments).  The
    column separator and decimal mark are found automatically unless given;
    any malformed row after the header is reported with its line number.
    """
    if separator is not None and separator not in SEPARATORS:
        raise ValueError(f"Неизвестный разделитель столбцов: {separator}.")
    if decimal is not None and decimal not in DECIMAL_MARKS:
        raise ValueError(f"Неизвестный десятичный разделитель: {decimal}.")
    if decimal == "," and separator in ("comma", "any"):
        raise ValueError("Запятая не может быть одновременно разделителем столбцов и десятичным разделителем.")
    source = Path(path).expanduser()
    text = _read_text(source)
    lines = [
        (line_number, line)
        for line_number, original in enumerate(text.splitlines(), start=1)
        # Leading tabs are kept: an empty first cell must not shift the columns.
        if (line := original.split("#", 1)[0].rstrip().lstrip(" ﻿")).strip()
    ]
    candidates = [(sep, mark) for sep, mark in _CANDIDATES if separator in (None, sep) and decimal in (None, mark)] or [
        (separator or "any", decimal or ".")
    ]
    attempts = [_attempt(lines, sep, mark) for sep, mark in candidates]
    good = [attempt for attempt in attempts if attempt.error is None]
    if not good:
        furthest = max(attempts, key=lambda attempt: (len(attempt.rows), -attempts.index(attempt)))
        raise ValueError(furthest.error)
    best = max(good, key=lambda attempt: (len(attempt.rows), -attempt.empty_cells, -good.index(attempt)))
    width = len(best.rows[0])
    header_lines = [line for _number, line in best.header_lines]
    headers = _column_headers(header_lines, best.separator, width)
    return DataTable(
        source=source,
        columns=tuple(header or f"Столбец {index + 1}" for index, header in enumerate(headers)),
        rows=tuple(best.rows),
        header_lines=tuple(header_lines),
        separator=best.separator,
        decimal=best.decimal,
        column_headers=headers,
    )


def select_trace(table: DataTable, x_column: int = 0, y_column: int = 1) -> TraceTable:
    """Take X (frequency) and Y columns, skip rows with an empty cell in them, sort by X."""
    width = len(table.columns)
    if not (0 <= x_column < width and 0 <= y_column < width):
        raise ValueError(f"В таблице {width} столбцов: нет столбца {max(x_column, y_column) + 1}.")
    if x_column == y_column:
        raise ValueError("Столбцы X и Y должны быть разными.")
    pairs = [
        (row[x_column], row[y_column]) for row in table.rows if row[x_column] is not None and row[y_column] is not None
    ]
    if not pairs:
        raise ValueError("В выбранных столбцах X и Y нет ни одной пары чисел.")
    pairs.sort(key=lambda pair: pair[0])  # type: ignore[arg-type,return-value]
    x_header = table.column_header(x_column)
    if x_header is not None:
        unit, note = detect_unit_in_column(x_header)
    elif x_column == 0:
        unit, note = detect_frequency_unit(table.header)
    else:
        unit, note = None, "в заголовке нет имени этого столбца" if table.header else "в файле нет заголовка"
    return TraceTable(
        frequencies=tuple(pair[0] for pair in pairs),  # type: ignore[misc]
        coefficients=tuple(pair[1] for pair in pairs),  # type: ignore[misc]
        source=table.source,
        header=table.header,
        header_unit=unit,
        unit_note=note,
        x_name=table.columns[x_column],
        y_name=table.columns[y_column],
        skipped_rows=len(table.rows) - len(pairs),
    )


def read_trace_table(path: str | Path) -> TraceTable:
    """The first two columns of a table: frequency and S21 (old two-column import)."""
    return select_trace(read_data_table(path), 0, 1)


def convert_trace(table: TraceTable, unit: str, unit_source: str, quantity: str = "dB") -> ComparisonTrace:
    """Convert the table's frequencies from *unit* to GHz, exactly once; Y stays as written."""
    if unit not in FREQUENCY_UNITS:
        raise ValueError(f"Неизвестная единица частоты: {unit}.")
    if quantity not in Y_QUANTITIES:
        raise ValueError(f"Неизвестная величина оси Y: {quantity}.")
    factor = FREQUENCY_UNITS[unit]
    return ComparisonTrace(
        frequencies=tuple(value * factor for value in table.frequencies),
        coefficients=table.coefficients,
        source=table.source,
        unit=unit,
        unit_source=unit_source,
        quantity=quantity,
    )


def right_axis_values(trace: ComparisonTrace, axis: YQuantity) -> tuple[list[float], list[float], int]:
    """Frequencies and log10 of Y in the right axis' unit; non-positive currents are dropped.

    The right axis is drawn in log10 space in both of its modes: with plain
    current its ticks read 10^y (log scale), with "Log" data they read y.
    Currents in A/mA/µA are moved into the axis' unit; I/I_g is never mixed
    with a current, it keeps its own values.  Returns the dropped count.
    """
    quantity = trace.y_quantity
    if quantity.axis != "right":
        raise ValueError(f"Величина {quantity.title} рисуется на левой оси.")
    shift = 0.0
    if quantity.family == axis.family == "current":
        shift = math.log10(quantity.factor / axis.factor)
    frequencies: list[float] = []
    values: list[float] = []
    dropped = 0
    for frequency, value in zip(trace.frequencies, trace.coefficients):
        if quantity.logarithmic:
            values.append(value + shift)
        elif value > 0:
            values.append(math.log10(value) + shift)
        else:
            dropped += 1
            continue
        frequencies.append(frequency)
    return frequencies, values, dropped
