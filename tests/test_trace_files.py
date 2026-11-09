"""Two-column HFSS/experiment import: one parser, the frequency unit only from the header (BUG-024)."""

from __future__ import annotations

from pathlib import Path

import pytest

from smcapp.infrastructure.trace_files import (
    FREQUENCY_UNITS,
    Y_QUANTITIES,
    ComparisonTrace,
    convert_trace,
    detect_frequency_unit,
    detect_y_quantity,
    read_data_table,
    read_trace_table,
    right_axis_values,
    select_trace,
)

DATA = Path(__file__).resolve().parent / "data"


def test_reader_accepts_header_comments_and_sorts_frequency(tmp_path) -> None:
    path = tmp_path / "exp.txt"
    path.write_text("Frequency S21\n# GHz dB\n120  -8.0\n100, -12.5\n110; -9.25\n", encoding="utf-8")

    table = read_trace_table(path)

    assert table.frequencies == (100.0, 110.0, 120.0)
    assert table.coefficients == (-12.5, -9.25, -8.0)
    assert table.header == "Frequency S21"
    # A unit in a comment or another column is not the frequency column's unit.
    assert table.header_unit is None and "нет единицы" in table.unit_note


def test_hfss_example_converts_thz_from_header() -> None:
    # Synthetic stand-in in the HFSS .tab format until the owner's real file arrives (WP-040).
    table = read_trace_table(DATA / "hfss_s21_example.tab")
    assert table.header_unit == "THz"
    trace = convert_trace(table, table.header_unit, table.unit_note)

    assert len(trace.frequencies) == 81
    assert trace.frequencies[0] == pytest.approx(100.0)
    assert trace.frequencies[-1] == pytest.approx(900.0)
    assert trace.coefficients[0] == pytest.approx(-1.821818542601)
    assert trace.unit == "THz"


@pytest.mark.parametrize(
    "text",
    [
        '"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-12.5\n0.2\t-9.25\n',
        "Freq [THz]\tdB(S(2,1)) []\n0.1 -12.5\n0.2 -9.25\n",
        '"Freq [THz]","dB(S(2,1)) []"\n0.1,-12.5\n0.2, -9.25\n',
        '"Freq [THz]";"dB(S(2,1)) []"\n0.1;-12.5\n\n0.2 ; -9.25\n',
        '﻿"Freq [THz]"  "dB(S(2,1)) []"\r\n\r\n0.2    -9.25\r\n0.1\t\t-12.5\r\n',
    ],
    ids=["tab-quoted", "tab-unquoted", "comma", "semicolon-blank-line", "bom-crlf-unsorted"],
)
def test_hfss_headers_quotes_and_separators(tmp_path, text) -> None:
    path = tmp_path / "s21.tab"
    path.write_bytes(text.encode("utf-8"))

    table = read_trace_table(path)
    trace = convert_trace(table, table.header_unit, "")

    assert table.header_unit == "THz"
    assert trace.frequencies == pytest.approx((100.0, 200.0))
    assert trace.coefficients == (-12.5, -9.25)
    assert trace.source == path


@pytest.mark.parametrize(
    "header, unit",
    [
        ('"Freq [GHz]"\t"dB(S(2,1)) []"', "GHz"),
        ("Freq [GHz]\tS21", "GHz"),
        ("Freq (GHz)\tS21 (dB)", "GHz"),  # BUG-024: was not recognised by HFSS and gave ×1000
        ("Freq (GHz) S21 (dB)", "GHz"),
        ("f_MHz, S21", "MHz"),
        ("Frequency [kHz] S21", "kHz"),
        ("Freq [Hz]\tS21", "Hz"),
        ("freq [thz]\ts21", "THz"),
    ],
)
def test_unit_recognised_in_frequency_column(header, unit) -> None:
    assert detect_frequency_unit(header)[0] == unit


@pytest.mark.parametrize(
    "header, reason",
    [
        (None, "нет заголовка"),
        ('"F"\t"S21"', "нет единицы"),  # was silently THz in HFSS
        ("Frequency S21 [GHz]", "нет единицы"),  # a unit in another column does not count
        ("Freq [s]\tS21", "не поддерживается"),
        ("Freq [GHz/THz]\tS21", "несколько единиц"),
    ],
)
def test_missing_unsupported_or_ambiguous_unit_is_not_guessed(header, reason) -> None:
    unit, note = detect_frequency_unit(header)
    assert unit is None and reason in note


def test_same_file_gives_same_coordinates_whatever_the_kind(tmp_path) -> None:
    """BUG-024 regression: the SMC export 100…1095 without units, chosen as GHz."""
    path = tmp_path / "HD35-H2.tab"
    path.write_text("".join(f"{100 + 5 * i}\t{-30 + i * 0.1}\n" for i in range(200)), encoding="utf-8")
    table = read_trace_table(path)

    assert table.header_unit is None
    trace = convert_trace(table, "GHz", "выбрано при импорте")
    assert (trace.frequencies[0], trace.frequencies[-1], len(trace.frequencies)) == (100.0, 1095.0, 200)


@pytest.mark.parametrize("unit", list(FREQUENCY_UNITS))
def test_every_unit_converts_to_ghz(tmp_path, unit) -> None:
    path = tmp_path / "t.txt"
    path.write_text("2 -3\n", encoding="utf-8")
    trace = convert_trace(read_trace_table(path), unit, "")
    assert trace.frequencies == (pytest.approx(2 * {"Hz": 1e-9, "kHz": 1e-6, "MHz": 1e-3, "GHz": 1, "THz": 1e3}[unit]),)
    with pytest.raises(ValueError, match="Неизвестная единица"):
        convert_trace(read_trace_table(path), "mm", "")


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "пуст"),
        ("\n  \n\t\n", "пуст"),
        ("Frequency S21\n", "только заголовок"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n\n', "только заголовок"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n0.2\tabc\n', "Строка 3: значения должны быть числами"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n\n0.3\t-4\t5\n', "Строка 4: ожидалось 2 столбца, найдено 3"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\n', "Строка 2: нужно минимум два столбца"),
        ("100 -10\n110 NaN\n", "Строка 2: NaN"),
        ("100 -10\n110 -9 extra\n", "Строка 2: ожидалось 2 столбца, найдено 3"),
    ],
    ids=["empty", "blank", "header-only", "header-blank", "text-value", "three-columns", "one-column", "nan", "extra"],
)
def test_errors_with_line_numbers(tmp_path, text, message) -> None:
    path = tmp_path / "broken.tab"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        read_trace_table(path)


def test_binary_origin_project_gets_a_clear_message(tmp_path) -> None:
    """BUG-026: an Origin .opj is binary; say so instead of a UnicodeDecodeError."""
    path = tmp_path / "testing.opj"
    path.write_bytes(b"CPYA 4 2946 161#\n\xf8\x00\x01\xff")
    with pytest.raises(ValueError, match="проект Origin"):
        read_trace_table(path)


# WP-055: decimal commas, several columns, the Y quantity and the right axis.


@pytest.mark.parametrize(
    "text, separator, decimal",
    [
        ("Freq [GHz]\tS21 [dB]\n100,5\t-12,25\n110\t-9,5\n", "tab", ","),
        ("Freq [GHz];S21 [dB]\n100,5;-12,25\n110;-9,5\n", "semicolon", ","),
        ("Freq [GHz]  S21 [dB]\n100,5   -12,25\n110 -9,5\n", "space", ","),
        ("Freq [GHz],S21 [dB]\n100.5,-12.25\n110,-9.5\n", "comma", "."),
        ("Freq [GHz]\tS21 [dB]\n100.5\t-12.25\n110\t-9.5\n", "tab", "."),
        ("Freq [GHz] S21 [dB]\n100.5, -12.25\n110; -9.5\n", "any", "."),
    ],
    ids=["tab-comma", "semicolon-comma", "space-comma", "csv-point", "tab-point", "mixed-point"],
)
def test_separator_and_decimal_mark_are_found(tmp_path, text, separator, decimal) -> None:
    path = tmp_path / "t.txt"
    path.write_text(text, encoding="utf-8")

    table = read_data_table(path)

    assert (table.separator, table.decimal) == (separator, decimal)
    trace = select_trace(table, 0, 1)
    assert trace.frequencies == (100.5, 110.0) and trace.coefficients == (-12.25, -9.5)
    assert trace.header_unit == "GHz" and trace.x_name == "Freq [GHz]" and trace.y_name == "S21 [dB]"


def test_origin_table_with_three_header_rows_and_empty_cells(tmp_path) -> None:
    path = tmp_path / "origin.dat"
    path.write_text(
        "Freq\tS21\tI\nGHz\tdB\tmA\n\tsample\t\n100,0\t-12,5\t0,01\n110,0\t-9,5\t\n120,0\t\t0,03\n",
        encoding="utf-8",
    )
    table = read_data_table(path)

    assert table.columns == ("Freq, GHz", "S21, dB", "I, mA")
    assert table.header_lines == ("Freq\tS21\tI", "GHz\tdB\tmA", "\tsample")
    assert table.rows == ((100.0, -12.5, 0.01), (110.0, -9.5, None), (120.0, None, 0.03))

    s21 = select_trace(table, 0, 1)
    assert s21.frequencies == (100.0, 110.0) and s21.skipped_rows == 1 and s21.header_unit == "GHz"
    current = select_trace(table, 0, 2)
    assert current.frequencies == (100.0, 120.0) and current.coefficients == (0.01, 0.03)
    assert detect_y_quantity(table.column_header(2)) == "mA"
    assert detect_y_quantity(table.column_header(1)) == "dB"


def test_columns_can_be_any_pair_and_unit_comes_from_the_x_column(tmp_path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("I [mA];Freq [THz]\n0,5;0,1\n0,7;0,2\n", encoding="utf-8")
    table = read_data_table(path)

    trace = select_trace(table, 1, 0)
    assert trace.frequencies == (0.1, 0.2) and trace.coefficients == (0.5, 0.7)
    assert trace.header_unit == "THz"
    assert select_trace(table, 0, 1).header_unit is None  # "I [mA]" names no frequency unit
    with pytest.raises(ValueError, match="должны быть разными"):
        select_trace(table, 1, 1)
    with pytest.raises(ValueError, match="нет столбца 3"):
        select_trace(table, 0, 2)


def test_explicit_separator_and_mark_override_the_guess(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("1,5 2,5\n3,5 4,5\n", encoding="utf-8")

    assert read_data_table(path).rows == ((1.5, 2.5), (3.5, 4.5))
    assert read_data_table(path, "any", ".").rows == ((1.0, 5.0, 2.0, 5.0), (3.0, 5.0, 4.0, 5.0))
    with pytest.raises(ValueError, match="только заголовок.*не тот разделитель"):
        read_data_table(path, "space", ".")
    with pytest.raises(ValueError, match="одновременно"):
        read_data_table(path, "comma", ",")


def test_trailing_comma_is_a_separator_not_a_decimal_mark(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("100, -12.5\n110, -9\n", encoding="utf-8")
    table = read_data_table(path)
    assert (table.separator, table.decimal) == ("comma", ".")
    assert table.rows == ((100.0, -12.5), (110.0, -9.0))


@pytest.mark.parametrize(
    "header, quantity",
    [
        ("S21 [dB]", "dB"),
        ("dB(S(2,1)) []", "dB"),
        ("I [mA]", "mA"),
        ("I (uA)", "µA"),
        ("I, µA", "µA"),
        ("I_A", "A"),
        ("I/Ig", "I/Ig"),
        ("lg I/I_g", "I/Ig log"),
        ("log I [mA]", "mA log"),
        ("Signal", None),
        (None, None),
        ("Amplitude", None),
    ],
)
def test_y_quantity_guessed_from_the_column_header(header, quantity) -> None:
    assert detect_y_quantity(header) == quantity


def test_convert_keeps_the_quantity_and_refuses_unknown_ones(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("100 0.5\n", encoding="utf-8")
    table = read_trace_table(path)
    assert convert_trace(table, "GHz", "", "mA").y_quantity is Y_QUANTITIES["mA"]
    with pytest.raises(ValueError, match="Неизвестная величина"):
        convert_trace(table, "GHz", "", "V")


def _trace(values, quantity) -> ComparisonTrace:
    return ComparisonTrace(tuple(range(100, 100 + 10 * len(values), 10)), tuple(values), DATA, quantity=quantity)


def test_right_axis_values_are_log10_in_the_axis_unit() -> None:
    # Plain current: log10, non-positive values cannot be shown on a log scale.
    frequencies, values, dropped = right_axis_values(_trace([0.01, 0.0, -1.0, 1.0], "mA"), Y_QUANTITIES["mA"])
    assert frequencies == [100, 130] and values == pytest.approx([-2.0, 0.0]) and dropped == 2
    # The same current on a µA axis is 1000 times larger.
    assert right_axis_values(_trace([0.01], "mA"), Y_QUANTITIES["µA"])[1] == pytest.approx([1.0])
    # "Log" data already is log10 and may be negative; only the unit shift applies.
    assert right_axis_values(_trace([-2.0, 0.5], "mA log"), Y_QUANTITIES["mA log"])[1] == pytest.approx([-2.0, 0.5])
    assert right_axis_values(_trace([-2.0], "mA log"), Y_QUANTITIES["A"])[1] == pytest.approx([-5.0])
    # I/I_g is never moved into a current unit.
    assert right_axis_values(_trace([10.0], "I/Ig"), Y_QUANTITIES["mA"])[1] == pytest.approx([1.0])
    with pytest.raises(ValueError, match="левой оси"):
        right_axis_values(_trace([-3.0], "dB"), Y_QUANTITIES["mA"])


def test_quantity_labels_and_placement() -> None:
    assert Y_QUANTITIES["dB"].axis == "left" and Y_QUANTITIES["dB"].axis_label == "S21, dB"
    assert Y_QUANTITIES["mA"].axis_label == "I, mA" and "логарифмическая" in Y_QUANTITIES["mA"].placement
    assert Y_QUANTITIES["µA log"].axis_label == "log₁₀(I / µA)" and "линейная" in Y_QUANTITIES["µA log"].placement
    assert Y_QUANTITIES["I/Ig log"].title == "I/I_g Log" and Y_QUANTITIES["I/Ig"].axis_label == "I/I_g"


@pytest.mark.parametrize(
    "text, separator, decimal, rows",
    [
        ("100,5\t-12,25\n110\t-9\n", "tab", ",", ((100.5, -12.25), (110.0, -9.0))),
        ("100,5   -12,25\n110 -9\n", "space", ",", ((100.5, -12.25), (110.0, -9.0))),
        ("100,5 \t -12,25\n", "tab", ",", ((100.5, -12.25),)),
        ("100,5 \t -12,25\n110 -9\n", "space", ",", ((100.5, -12.25), (110.0, -9.0))),
        ("100 -12\n110 -9\n", "space", ".", ((100.0, -12.0), (110.0, -9.0))),
        ("100.5 -12.25\n", "space", ".", ((100.5, -12.25),)),
        # A comma between columns only when nothing else gives two columns.
        ("100.5,-12.25\n110,-9\n", "comma", ".", ((100.5, -12.25), (110.0, -9.0))),
        ("100,5\n110,5\n", "comma", ".", ((100.0, 5.0), (110.0, 5.0))),
    ],
    ids=[
        "tab-comma",
        "spaces-comma",
        "tab-and-spaces",
        "tab-then-spaces",
        "integers",
        "spaces-point",
        "csv",
        "comma-only-fallback",
    ],
)
def test_whitespace_columns_and_decimal_comma_come_first(tmp_path, text, separator, decimal, rows) -> None:
    """Owner, 09.11.2026: columns are split by spaces or tabs; a comma is usually a decimal mark."""
    path = tmp_path / "t.txt"
    path.write_text(text, encoding="utf-8")
    table = read_data_table(path)
    assert (table.separator, table.decimal, table.rows) == (separator, decimal, rows)
