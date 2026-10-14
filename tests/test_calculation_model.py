"""Regression checks for the audited legacy-to-domain calculation mapping."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from numpy.testing import assert_allclose

from aocapp.api.complex_integration import ComplexIntegrator
from aocapp.api.dc_block import DCBlockCalculator
from aocapp.api.impedance import ImpedanceCalculator
from aocapp.api.microstrip import MicrostripLineCalculator
from aocapp.api.models import FilmConductivity
from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.s21_calculator import S21CalculatorImpl


def test_alpha_gap_relation_preserves_legacy_default_and_is_not_constant() -> None:
    legacy_default_ev = S21CalculatorImpl._delta0_from_alpha_tc(3.54, 9.5)
    changed_alpha_ev = S21CalculatorImpl._delta0_from_alpha_tc(4.0, 9.5)

    assert legacy_default_ev == pytest.approx(1.45e-3, rel=1e-3)
    assert changed_alpha_ev / legacy_default_ev == pytest.approx(4.0 / 3.54)


def test_sis_capacitance_display_scale_does_not_change_backend_value() -> None:
    config = S21Config()

    assert S21Config.field_scale("sis_cap_f_per_um2") == 1e12
    assert config.sis_cap_f_per_um2 * S21Config.field_scale("sis_cap_f_per_um2") == pytest.approx(0.083)


@pytest.mark.parametrize("frequency_ghz,offset_um", [(100, 8), (650, 4), (895, 16), (650, 35.9)])
def test_dc_block_api_matches_legacy_for_lso_edits(monkeypatch, frequency_ghz, offset_um) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    legacy = importlib.import_module("DC_Block")
    calculator = DCBlockCalculator(ComplexIntegrator(), MicrostripLineCalculator(ImpedanceCalculator()))
    config = S21Config(lso_m=offset_um * 1e-6)
    # Fixed film data isolate the ported DC block from the separate MB solver.
    film = FilmConductivity([100, 500, 900], [1e5, 2e5, 3e5], [1e8, 8e7, 6e7])
    inputs = (
        frequency_ghz,
        config.w_slot_m - config.dw_m,
        config.l_slot_m,
        config.lso_m,
        config.w_ms_m + config.dw_m,
        config.l_ms_m,
        config.e_sub,
        config.h_sub_m,
        config.e12,
        config.h12_m,
    )
    actual = calculator.matrix(*inputs, film, film, config.d_top_m, config.d_bot_m)
    expected = legacy.M_DCB(*inputs, film.as_tuple(), film.as_tuple(), config.d_top_m, config.d_bot_m)
    assert_allclose(actual, expected, rtol=1e-11, atol=1e-12)
