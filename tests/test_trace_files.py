"""Two-column HFSS/experiment import tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from aocapp.infrastructure.trace_files import HfssTabReader, TraceFileReader


def test_trace_reader_accepts_header_comments_and_sorts_frequency(tmp_path) -> None:
    path = tmp_path / "hfss.txt"
    path.write_text("Frequency S21\n# GHz dB\n120  -8.0\n100, -12.5\n110; -9.25\n", encoding="utf-8")

    trace = TraceFileReader().load(path)

    assert trace.frequencies == (100.0, 110.0, 120.0)
    assert trace.coefficients == (-12.5, -9.25, -8.0)


@pytest.mark.parametrize(
    "text, message",
    [
        ("Frequency S21\n", "не содержит"),
        ("100 -10\n110 NaN\n", "NaN"),
        ("100 -10\n110 -9 extra\n", "ровно два"),
    ],
)
def test_trace_reader_reports_bad_rows(tmp_path, text, message) -> None:
    path = tmp_path / "broken.txt"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        TraceFileReader().load(path)


DATA = Path(__file__).resolve().parent / "data"


def test_hfss_reader_loads_example_converting_thz_to_ghz() -> None:
    # Synthetic stand-in in the HFSS .tab format until the owner's real file arrives.
    trace = HfssTabReader().load(DATA / "hfss_s21_example.tab")

    assert len(trace.frequencies) == 81
    assert trace.frequencies[0] == pytest.approx(100.0)
    assert trace.frequencies[-1] == pytest.approx(900.0)
    assert trace.coefficients[0] == pytest.approx(-1.821818542601)
    assert all(-20 < value < 0 for value in trace.coefficients)


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
def test_hfss_reader_accepts_header_quotes_and_separators(tmp_path, text) -> None:
    path = tmp_path / "s21.tab"
    path.write_bytes(text.encode("utf-8"))

    trace = HfssTabReader().load(path)

    assert trace.frequencies == pytest.approx((100.0, 200.0))
    assert trace.coefficients == (-12.5, -9.25)
    assert trace.source == path


@pytest.mark.parametrize(
    "header, first_ghz",
    [('"Freq [GHz]"\t"dB(S(2,1)) []"', 100.0), ('"Freq [THz]"\t"dB(S(2,1)) []"', 100_000.0), ('"F"\t"S21"', 100_000.0)],
)
def test_hfss_reader_takes_frequency_unit_from_header(tmp_path, header, first_ghz) -> None:
    path = tmp_path / "s21.tab"
    path.write_text(f"{header}\n100\t-3\n", encoding="utf-8")

    assert HfssTabReader().load(path).frequencies == (pytest.approx(first_ghz),)


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "пуст"),
        ("\n  \n\t\n", "пуст"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n', "только заголовок"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n\n', "только заголовок"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n0.2\tabc\n', "Строка 3: частота и S21 должны быть числами"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n\n0.3\t-4\t5\n', "Строка 4: ожидалось два столбца"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\n', "Строка 2: ожидалось два столбца"),
        ('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\tNaN\n', "Строка 2: NaN"),
    ],
    ids=["empty", "blank", "header-only", "header-blank", "text-value", "three-columns", "one-column", "nan"],
)
def test_hfss_reader_reports_errors_with_line_numbers(tmp_path, text, message) -> None:
    path = tmp_path / "broken.tab"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        HfssTabReader().load(path)
