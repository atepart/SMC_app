"""Two-column HFSS/experiment import: one parser, the frequency unit only from the header (BUG-024)."""

from __future__ import annotations

import math
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
    right_axis_span_db,
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
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n\n0.3\t-4\t5\n', "Строка 4: ожидалось 2 столбца, найдено 3"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\n', "Строка 2: нужно минимум два столбца"),
        ("100 -10\n110 -9 extra\n", "Строка 2: ожидалось 2 столбца, найдено 3"),
        # WP-063: values that are all skipped leave no point at all.
        ("Freq [GHz]\tI\n100\t--\n110\t--\n120\tn/a\n", "Нет ни одной строки хотя бы с двумя числами \\(строки 2–4\\)"),
        ("100\tNaN\n", "Нет ни одной строки хотя бы с двумя числами \\(строка 1\\)"),
    ],
    ids=["empty", "blank", "header-only", "header-blank", "three-columns", "one-column", "extra", "all-dashes", "nan"],
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
        ("(I/Ig)^2", "(I/Ig)²"),
        ("lg (I/I_g)²", "(I/Ig)² log"),
        ("log I^2 [mA^2]", "mA² log"),
        ("lg I² (µA²)", "µA² log"),
        # WP-067: a logarithm only of a square; lg I and I² alone are no quantity.
        ("lg I/I_g", None),
        ("log I [mA]", None),
        ("I^2 [mA^2]", None),
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


def test_right_axis_values_are_lg_of_the_squared_current_in_the_axis_unit() -> None:
    """WP-064: the right axis shows I² (a decade of I² is 10 dB); its coordinate is lg I²."""
    # Plain current: 2·lg I; I ≤ 0 is dropped (open owner question a).
    frequencies, values, dropped = right_axis_values(_trace([0.01, 0.0, -1.0, 1.0], "mA"), Y_QUANTITIES["mA"])
    assert frequencies == [100, 130] and values == pytest.approx([-4.0, 0.0]) and dropped == 2
    # The same current on a µA axis: I is 1000 times larger, I² 10⁶ times (mA² → µA²).
    assert right_axis_values(_trace([0.01], "mA"), Y_QUANTITIES["µA"])[1] == pytest.approx([2.0])
    # The owner's example: 38.7…122.5 µA ⇒ I² ≈ 1500…15000 µA², a span of −10 dB.
    low, high = right_axis_values(_trace([38.7298, 122.474], "µA"), Y_QUANTITIES["µA"])[1]
    assert 10.0**low == pytest.approx(1500.0, rel=1e-5) and 10.0**high == pytest.approx(15000.0, rel=1e-5)
    assert right_axis_span_db(low, high) == pytest.approx(-10.0, abs=1e-4)
    # WP-067: "Log" data already is lg I² and may be negative: drawn as it is, plus the unit shift (mA² → A² is −6).
    assert right_axis_values(_trace([-2.0, 0.5], "mA² log"), Y_QUANTITIES["mA² log"])[1] == pytest.approx([-2.0, 0.5])
    assert right_axis_values(_trace([-2.0], "mA² log"), Y_QUANTITIES["A"])[1] == pytest.approx([-8.0])
    # I/I_g is never moved into a current unit; I/I_g is squared, (I/I_g)² is not squared again.
    assert right_axis_values(_trace([10.0], "I/Ig"), Y_QUANTITIES["mA"])[1] == pytest.approx([2.0])
    frequencies, values, dropped = right_axis_values(_trace([100.0, 0.0, -4.0], "(I/Ig)²"), Y_QUANTITIES["I/Ig"])
    assert frequencies == [100] and values == pytest.approx([2.0]) and dropped == 2
    assert right_axis_values(_trace([2.0, -1.0], "(I/Ig)² log"), Y_QUANTITIES["(I/Ig)²"])[1] == pytest.approx(
        [2.0, -1.0]
    )
    with pytest.raises(ValueError, match="левой оси"):
        right_axis_values(_trace([-3.0], "dB"), Y_QUANTITIES["mA"])


@pytest.mark.parametrize(
    "low, high, expected",
    [
        (math.log10(1500), math.log10(15000), -10.0),
        (math.log10(150), math.log10(15000), -20.0),
        (math.log10(15000), math.log10(15000), 0.0),
        (3.2, 4.2, -10.0),  # "Log" data: lg I² read linearly, as the owner's lgI^2 chart
    ],
)
def test_right_axis_span_in_db(low, high, expected) -> None:
    assert right_axis_span_db(low, high) == pytest.approx(expected)


def test_quantity_labels_and_placement() -> None:
    assert Y_QUANTITIES["dB"].axis == "left" and Y_QUANTITIES["dB"].axis_label == "S21, dB"
    assert Y_QUANTITIES["mA"].axis_label == "I², mA²" and "I² в логарифмической" in Y_QUANTITIES["mA"].placement
    assert Y_QUANTITIES["µA² log"].title == "I², µA² Log" and Y_QUANTITIES["µA² log"].axis_label == "lg(I² / µA²)"
    assert "уже lg(I² / µA²), рисуются как есть" in Y_QUANTITIES["µA² log"].placement
    assert Y_QUANTITIES["I/Ig"].title == "I/I_g" and Y_QUANTITIES["I/Ig"].axis_label == "(I/I_g)²"
    assert Y_QUANTITIES["(I/Ig)²"].title == "(I/I_g)²" and Y_QUANTITIES["(I/Ig)²"].axis_label == "(I/I_g)²"
    assert "без возведения в квадрат" in Y_QUANTITIES["(I/Ig)²"].placement
    assert (
        Y_QUANTITIES["(I/Ig)² log"].title == "(I/I_g)² Log" and Y_QUANTITIES["(I/Ig)² log"].axis_label == "lg (I/I_g)²"
    )
    assert Y_QUANTITIES["µA"].squared_unit == "µA²"
    # Owner 19.11.2026: no «Log» without the square.
    assert [quantity.title for quantity in Y_QUANTITIES.values()] == [
        "S21, dB",
        "I, A",
        "I, mA",
        "I, µA",
        "I/I_g",
        "(I/I_g)²",
        "I², A² Log",
        "I², mA² Log",
        "I², µA² Log",
        "(I/I_g)² Log",
    ]


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


# WP-063 / BUG-029: a point whose X or Y is not a number ("--", "n/a", NaN) is skipped.


def test_owner_file_with_dashes_skips_the_points_without_data() -> None:
    """Owner's experiment (11.11.2026): tab, decimal comma, CRLF; lines 201–210 are "800,56262\t--"."""
    table = read_data_table(DATA / "exp_hd34_11_12_dashes.tab")
    assert (table.separator, table.decimal, len(table.columns)) == ("tab", ",", 2)
    assert table.cell_text(200, 1) == "--" and table.rows[200] == (800.56262, None)

    trace = select_trace(table, 0, 1)

    assert len(trace.frequencies) == 200 and trace.skipped_rows == 10
    assert trace.frequencies[0] == 1.44354 and trace.coefficients[0] == -0.14139
    assert trace.frequencies[-1] == 796.56702 and trace.coefficients[-1] == -0.08148
    assert trace.skipped_lines == tuple(range(201, 211)) and trace.skipped_summary == "строки 201–210"


@pytest.mark.parametrize(
    "mark",
    ["--", "-", "+", "—", "n/a", "N/A", "NaN", "nan", "inf", "-Infinity", "***", "?", "1e999", "abc", "12,5,1"],
)
def test_any_value_that_is_not_a_number_skips_its_point(tmp_path, mark) -> None:
    path = tmp_path / "t.txt"
    path.write_text(f"Freq [GHz]\tS21 [dB]\n100\t-10\n110\t{mark}\n120\t-12\n130,0\t-13\n", encoding="utf-8")
    trace = select_trace(read_data_table(path, "tab", "."), 0, 1)
    assert trace.frequencies == (100.0, 120.0) and trace.coefficients == (-10.0, -12.0)
    assert trace.skipped_rows == 2 and trace.skipped_lines == (3, 5)
    assert trace.skipped_summary == "строки 3, 5"


def test_dashes_at_the_start_of_data_and_in_x(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("f, GHz\tI, mA\n100\t--\n--\t2\n120\t3\n130\t4\n", encoding="utf-8")
    table = read_data_table(path)
    # The dash rows are data, not header: the header keeps its names only.
    assert table.header_lines == ("f, GHz\tI, mA",) and table.columns == ("f, GHz", "I, mA")
    assert table.rows == ((100.0, None), (None, 2.0), (120.0, 3.0), (130.0, 4.0))
    trace = select_trace(table, 0, 1)
    assert trace.frequencies == (120.0, 130.0) and trace.skipped_summary == "строки 2–3"


def test_dash_in_an_unselected_column_keeps_the_point(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("Freq\tS21\tI\n100,0\t-12,5\t--\n110,0\t-9,5\t0,02\n120,0\t--\t0,03\n", encoding="utf-8")
    table = read_data_table(path)
    s21 = select_trace(table, 0, 1)
    assert s21.frequencies == (100.0, 110.0) and s21.skipped_lines == (4,)
    current = select_trace(table, 0, 2)
    assert current.frequencies == (110.0, 120.0) and current.skipped_summary == "строка 2"


def test_exponents_stay_numbers(tmp_path) -> None:
    """HFSS writes 1.2e-3; the owner's rule (digits, sign, mark) must not drop such points."""
    path = tmp_path / "hfss.csv"
    path.write_text('"Freq [GHz]","dB(S(2,1)) []"\n1.0E+02,-1.25e+01\n1.1e2,--\n120,-9.5E0\n', encoding="utf-8")
    table = read_data_table(path)
    assert (table.separator, table.decimal) == ("comma", ".")
    trace = select_trace(table, 0, 1)
    assert trace.frequencies == (100.0, 120.0) and trace.coefficients == (-12.5, -9.5)


def test_empty_cells_and_dashes_are_counted_together(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("100\t-10\n110\t\n120\t--\n130\t-13\n", encoding="utf-8")
    trace = select_trace(read_data_table(path), 0, 1)
    assert trace.frequencies == (100.0, 130.0) and trace.skipped_rows == 2 and trace.skipped_summary == "строки 2–3"


def test_wrong_separator_cannot_win_by_skipping_everything(tmp_path) -> None:
    """With the comma as a column separator every row would read "1", "44354\t-0", "14139" — one skip each."""
    path = tmp_path / "t.txt"
    path.write_text("1,44354\t-0,14139\n5,43913\t0,25892\n800,56262\t--\n", encoding="utf-8")
    table = read_data_table(path)
    assert (table.separator, table.decimal) == ("tab", ",")
    assert table.rows == ((1.44354, -0.14139), (5.43913, 0.25892), (800.56262, None))


def test_line_ranges_are_compressed() -> None:
    from smcapp.infrastructure.trace_files import describe_lines

    assert describe_lines(()) == ""
    assert describe_lines((7,)) == "строка 7"
    assert describe_lines((12, 10, 11, 3, 7)) == "строки 3, 7, 10–12"
    assert describe_lines(tuple(range(1, 20, 2))) == "строки 1, 3, 5, 7 и ещё 6"
