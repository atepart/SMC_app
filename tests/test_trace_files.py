"""Two-column HFSS/experiment import: one parser, the frequency unit only from the header (BUG-024)."""

from __future__ import annotations

from pathlib import Path

import pytest

from smcapp.infrastructure.trace_files import FREQUENCY_UNITS, convert_trace, detect_frequency_unit, read_trace_table

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
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n0.2\tabc\n', "Строка 3: частота и S21 должны быть числами"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n\n0.3\t-4\t5\n', "Строка 4: ожидалось два столбца"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\n', "Строка 2: ожидалось два столбца"),
        ("100 -10\n110 NaN\n", "Строка 2: NaN"),
        ("100 -10\n110 -9 extra\n", "Строка 2: ожидалось два столбца"),
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
