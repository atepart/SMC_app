"""Two-column HFSS/experiment import tests."""

from __future__ import annotations

import pytest

from aocapp.infrastructure.trace_files import TraceFileReader


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
