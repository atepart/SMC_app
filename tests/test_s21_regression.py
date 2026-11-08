"""WP-044 stage 1: list-based Mex01/Mex02/Mex03 give bit-for-bit the former S21.

``tests/data/s21_reference_before_wp044.json`` was produced by the calculator
with fixed ``transf_1..7``/``msl_4..8`` fields (commit ccad0c9) before the
sections became lists. Values are stored as ``float.hex`` so the comparison is
exact.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from smcapp.domain.circuit import LineSection, TransformerSection
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.s21_calculator import build_default_s21_calculator

REFERENCE = json.loads((Path(__file__).parent / "data" / "s21_reference_before_wp044.json").read_text())


def _variant() -> S21Config:
    """Every Mex section changed in one element, as in the stored reference run.

    Former fields: transf_6_w_end_m=20 µm (3 · W1), msl_8_len_m=31 µm (2 · L),
    msl_7_width_m=9 µm (4 · W), transf_5_dl_m=0.7 µm (5), msl_4_len_m=22 µm
    (12 · L), transf_2_w_start_m=19 µm (11 · W2).
    """
    config = S21Config(s21_freq_start_ghz=200.0, s21_freq_stop_ghz=800.0, s21_freq_step_ghz=50.0)
    t1, line2, t3 = config.mex01
    line4, t5, line6 = config.mex02
    line10, t11, line12, t13 = config.mex03
    return replace(
        config,
        mex01=(t1, replace(line2, length_m=31e-6), replace(t3, w1_m=20e-6)),
        mex02=(replace(line4, width_m=9e-6), replace(t5, dl_m=0.7e-6), line6),
        mex03=(line10, replace(t11, w2_m=19e-6), replace(line12, length_m=22e-6), t13),
    )


@pytest.mark.parametrize(("name", "config_factory"), [("default", S21Config), ("variant", _variant)])
def test_s21_matches_fixed_field_calculator_bit_for_bit(name, config_factory):
    reference = REFERENCE[name]
    result = build_default_s21_calculator().calculate(config_factory())

    assert [float(f) for f in result.frequencies_ghz] == reference["frequencies_ghz"]
    assert [float(value).hex() for value in result.s21_db] == reference["s21_db"]


def test_default_sections_keep_the_former_element_values():
    config = S21Config()
    # Drawing order 1…13; W1 is the former Wend, W2 the former Wstart.
    assert config.mex01 == (
        TransformerSection(14e-6, 49e-6, 5.0, 1.2e-6),
        LineSection(50e-6, 13e-6),
        TransformerSection(48e-6, 18e-6, 3.0, 1.2e-6),
    )
    assert config.mex02 == (
        LineSection(18e-6, 24e-6),
        TransformerSection(18e-6, 6e-6, 3.0, 1.2e-6),
        LineSection(4e-6, 25e-6),
    )
    assert config.corner_left == TransformerSection(6e-6, 10e-6, 1.0, 1.2e-6)
    assert config.corner_right == TransformerSection(10e-6, 6e-6, 1.0, 1.2e-6)
    assert config.mex03 == (
        LineSection(4e-6, 10e-6),
        TransformerSection(4e-6, 18e-6, 2.0, 0.9e-6),
        LineSection(18e-6, 27e-6),
        TransformerSection(18e-6, 6e-6, 6.0, 0.9e-6),
    )
