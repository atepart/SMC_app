"""Regression checks for the audited legacy-to-domain calculation mapping."""

from __future__ import annotations

import pytest

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
