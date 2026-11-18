"""WP-057 / BUG-023: S21 of the Mathcad HD35-M and HD35-L worksheets.

``tests/data/S21_HD35-{M,L}-dB.tab`` are Fedor's curves (letter of 10.11.2026)
from the legacy backend notebooks ``Checking_HD35-M/L.ipynb``; he checked them
against the worksheets to 7–8 significant digits.  ``tests/data/HD35-{M,L}.smcdesign``
hold the same inputs as parameter files of the program.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from smcapp.api import SuperconductingGapCalculator
from smcapp.domain.dielectrics import ANODIZATION_M_PER_V, dielectric_errors, dielectric_stack, layers_from_legacy_stack
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.design_files import DESIGN_VERSION, DesignFileService
from smcapp.infrastructure.s21_calculator import S21CalculatorImpl, build_default_s21_calculator

DATA = Path(__file__).parent / "data"
KB_EV = 1.38065 / 1.6022 * 1e-4  # Boltzmann's constant in eV/K with the backend's rounding


@pytest.mark.parametrize("name", ["HD35-M", "HD35-L"])
def test_full_sweep_matches_the_worksheet_curve(name) -> None:
    config = DesignFileService().load(DATA / f"{name}.smcdesign")
    reference = np.loadtxt(DATA / f"S21_{name}-dB.tab")

    result = build_default_s21_calculator().calculate(config)

    assert result.frequencies_ghz == pytest.approx(reference[:, 0].tolist(), abs=1e-9)
    # Before WP-057 (strong-coupling Δ(T), σ grid 20 GHz) the gap was 0.87 / 1.57 dB.
    assert np.abs(np.array(result.s21_db, dtype=float) - reference[:, 1]).max() < 1e-4


def test_worksheet_designs_use_the_worksheet_inputs() -> None:
    m = DesignFileService().load(DATA / "HD35-M.smcdesign")
    lower = DesignFileService().load(DATA / "HD35-L.smcdesign")
    for config in (m, lower):
        assert (config.ins_h1_m, config.ins_h2_m, config.anod_voltage_v) == (0.15e-6, 0.25e-6, 10.0)
        assert (config.eps_ins, config.eps_anod) == (4.2, 9.8)
        assert (config.temperature_k, config.tc_top_k, config.tc_bot_k) == (4.4, 13.0, 9.5)
        # Δ0 = 1.835·kB·Tc (EL1) and 1.815·kB·Tc (EL2) of the notebooks.
        assert (config.alpha_top, config.alpha_bot) == (3.67, 3.63)
        assert (config.d_top_m, config.d_bot_m) == (0.5e-6, 0.2e-6)
        assert config.film_freq_step_ghz == 5.0
    assert (m.sis_area_um2, lower.sis_area_um2) == (1.0, 1.2)
    assert (m.radial_r_max_m, lower.radial_r_max_m) == (34e-6, 42e-6)


# --- Dielectric stack (D1) ----------------------------------------------------------


def test_dielectric_stack_matches_fedors_notebook() -> None:
    stack = S21Config().dielectric_stack()
    # Checking_HD35-M.ipynb: H12, E12, H1, E1 of the worksheet.
    assert stack.h12_m == pytest.approx(0.415729e-6, rel=1e-12)
    assert stack.e12 == pytest.approx(4.2928099, abs=1e-7)
    assert stack.h1_m == pytest.approx(1.65729e-7, rel=1e-12)
    assert stack.e1 == pytest.approx(4.4408406, abs=1e-7)
    config = S21Config()
    assert (config.h12_m, config.e12, config.h1_m, config.e1) == (stack.h12_m, stack.e12, stack.h1_m, stack.e1)


def test_dielectric_stack_edges() -> None:
    # Without anodization the stack is the insulator alone.
    bare = dielectric_stack(0.15e-6, 0.25e-6, 0.0, 4.2, 9.8)
    assert (bare.h1_m, bare.h12_m) == (0.15e-6, pytest.approx(0.40e-6))
    assert bare.e1 == pytest.approx(4.2) and bare.e12 == pytest.approx(4.2)
    # A vanishing insulator leaves the anodic oxide: ε → ε_Al.
    thin = dielectric_stack(1e-15, 1e-15, 10.0, 4.2, 9.8)
    assert thin.e1 == pytest.approx(9.8, rel=1e-6) and thin.h1_m == pytest.approx(ANODIZATION_M_PER_V * 10)
    # Equal permittivities give that permittivity at any thickness.
    assert dielectric_stack(0.1e-6, 0.2e-6, 30.0, 5.0, 5.0).e12 == pytest.approx(5.0)


@pytest.mark.parametrize(
    "layers, message",
    [
        ((0.0, 0.25e-6, 10.0, 4.2, 9.8), "толщина h1 должна быть больше 0"),
        ((0.15e-6, 0.0, 10.0, 4.2, 9.8), "толщина h2 должна быть больше 0"),
        ((0.15e-6, 0.25e-6, -1.0, 4.2, 9.8), "V anod не может быть отрицательным"),
        ((0.15e-6, 0.25e-6, 10.0, 0.0, 9.8), "ε i должна быть больше 0"),
        ((0.15e-6, 0.25e-6, 10.0, 4.2, -9.8), "ε Al должна быть больше 0"),
        ((0.15e-6, math.nan, 10.0, 4.2, 9.8), "конечными числами"),
    ],
)
def test_invalid_dielectric_layers_are_refused(layers, message) -> None:
    assert any(message in error for error in dielectric_errors(*layers))
    with pytest.raises(ValueError, match=message):
        dielectric_stack(*layers)
    names = ("ins_h1_m", "ins_h2_m", "anod_voltage_v", "eps_ins", "eps_anod")
    with pytest.raises(ValueError, match=message):
        S21Config(**dict(zip(names, layers))).validate()


# --- Δ(T) (D4) ----------------------------------------------------------------------


def test_gap_is_the_worksheet_tanh_formula() -> None:
    gap = SuperconductingGapCalculator()
    delta0 = 1.835 * KB_EV * 13.0
    assert gap.delta_bcs_approx(4.4, 13.0, delta0) == pytest.approx(
        delta0 * math.tanh(1.74 * math.sqrt(13.0 / 4.4 - 1.0)), rel=1e-15
    )
    # Notebook output: Delta_top = 0.002024180311170856 eV, Delta_bot = 0.0014173156769580536 eV.
    assert gap.delta_bcs_approx(4.4, 13.0, delta0) == pytest.approx(0.002024180311170856, rel=1e-12)
    assert gap.delta_bcs_approx(4.4, 9.5, 1.815 * KB_EV * 9.5) == pytest.approx(0.0014173156769580536, rel=1e-12)


def test_gap_edges_near_zero_and_critical_temperature() -> None:
    gap = SuperconductingGapCalculator()
    delta0 = 1.8e-3
    assert gap.delta_bcs_approx(1e-3, 9.5, delta0) == pytest.approx(delta0, rel=1e-12)  # T → 0
    near = gap.delta_bcs_approx(9.5 * (1 - 1e-6), 9.5, delta0)  # T → Tc: Δ ≈ 1.74·Δ0·√(1 − T/Tc)
    assert near == pytest.approx(1.74 * delta0 * math.sqrt(1e-6), rel=1e-5)
    assert gap.delta_bcs_approx(9.5, 9.5, delta0) == 0.0
    assert gap.delta_bcs_approx(12.0, 9.5, delta0) == 0.0  # above Tc there is no gap


def test_calculator_uses_the_tanh_gap_not_strong_coupling() -> None:
    calls = []

    class Spy(SuperconductingGapCalculator):
        def delta_bcs_approx(self, *args):
            calls.append(("tanh", args))
            return super().delta_bcs_approx(*args)

        def delta_strong_coupling(self, *args):  # pragma: no cover - must not be called
            calls.append(("strong", args))
            return super().delta_strong_coupling(*args)

    config = S21Config(s21_freq_start_ghz=600.0, s21_freq_stop_ghz=601.0, s21_freq_step_ghz=5.0)
    config = replace(config, film_freq_start_ghz=590.0, film_freq_stop_ghz=611.0, film_freq_step_ghz=10.0)
    result = replace(build_default_s21_calculator(), gap_calc=Spy()).calculate(config)
    delta0 = S21CalculatorImpl._delta0_from_alpha_tc(config.alpha_top, config.tc_top_k)
    assert calls == [
        ("tanh", (config.temperature_k, config.tc_top_k, delta0)),
        ("tanh", (config.temperature_k, config.tc_bot_k, delta0)),
    ]
    assert any("tanh(1.74*sqrt(Tc/T - 1))" in line for line in result.log_messages)
    assert any("H12 = 0.415729 um, E12 = 4.2928099" in line for line in result.log_messages)


@pytest.mark.parametrize("temperature, electrode", [(9.5, "EL1"), (10.0, "EL1"), (9.0, "EL2")])
def test_temperature_not_below_tc_is_refused(temperature, electrode) -> None:
    config = S21Config(temperature_k=temperature, tc_top_k=9.5, tc_bot_k=9.0)
    with pytest.raises(ValueError, match=f"T env = {temperature:g} K не ниже Tc {electrode}"):
        config.validate()


# --- σ grid ---------------------------------------------------------------------------


def test_default_sigma_grid_has_5_ghz_step_and_covers_the_sweep() -> None:
    config = S21Config()
    assert config.film_freq_step_ghz == 5.0
    film = np.arange(config.film_freq_start_ghz, config.film_freq_stop_ghz, config.film_freq_step_ghz)
    sweep = np.arange(config.s21_freq_start_ghz, config.s21_freq_stop_ghz, config.s21_freq_step_ghz)
    assert film[0] <= sweep[0] and film[-1] >= sweep[-1]
    assert set(sweep) <= set(film)  # sweep points fall on grid nodes: no interpolation error
    config.validate()


@pytest.mark.parametrize(
    "film, sweep, ok",
    [
        ((20.0, 1110.0, 5.0), (100.0, 1110.0, 5.0), True),  # both end on 1105 GHz
        ((20.0, 1110.0, 20.0), (100.0, 1110.0, 5.0), False),  # σ ends on 1100, sweep on 1105
        ((20.0, 1110.0, 20.0), (100.0, 1101.0, 5.0), True),  # sweep ends on 1100
    ],
)
def test_sweep_beyond_the_last_sigma_point_is_refused(film, sweep, ok) -> None:
    config = S21Config(
        film_freq_start_ghz=film[0],
        film_freq_stop_ghz=film[1],
        film_freq_step_ghz=film[2],
        s21_freq_start_ghz=sweep[0],
        s21_freq_stop_ghz=sweep[1],
        s21_freq_step_ghz=sweep[2],
    )
    if ok:
        config.validate()
    else:
        with pytest.raises(ValueError, match="Сетка σ .* кончается на 1100 GHz, а sweep доходит до 1105 GHz"):
            config.validate()


# --- Old files with H12/E12/H1/E1 ---------------------------------------------------------


def _old_file(tmp_path, version: int = 2, **stored) -> Path:
    path = DesignFileService().save(tmp_path / "current.smcdesign", S21Config())
    payload = json.loads(path.read_text())
    payload["version"] = version
    parameters = payload["parameters"]
    for name in ("ins_h1_m", "ins_h2_m", "anod_voltage_v", "eps_ins", "eps_anod"):
        del parameters[name]
    parameters.update(stored)
    old = tmp_path / f"old-v{version}.smcdesign"
    old.write_text(json.dumps(payload))
    return old


def test_old_file_layers_are_rebuilt_without_notes_when_permittivities_agree(tmp_path) -> None:
    stored = {"h12_m": 0.465729e-6, "e12": 4.28265, "h1_m": 1.65729e-7, "e1": 4.44084}
    config, notes = DesignFileService().load_with_notes(_old_file(tmp_path, **stored))
    assert notes == ()
    assert (config.ins_h1_m, config.ins_h2_m) == (pytest.approx(0.15e-6), pytest.approx(0.30e-6))
    assert (config.anod_voltage_v, config.eps_ins, config.eps_anod) == (10.0, 4.2, 9.8)
    # Thicknesses are kept exactly, permittivities within the stored rounding.
    assert config.h12_m == pytest.approx(0.465729e-6, rel=1e-12)
    assert config.h1_m == pytest.approx(1.65729e-7, rel=1e-12)
    assert config.e12 == pytest.approx(4.28265, abs=1e-5) and config.e1 == pytest.approx(4.44084, abs=1e-5)


def test_old_file_without_dielectrics_gets_the_old_defaults(tmp_path) -> None:
    config, notes = DesignFileService().load_with_notes(_old_file(tmp_path))
    assert notes == ()
    assert config.h12_m == pytest.approx(0.465729e-6, rel=1e-12)


def test_old_file_with_other_permittivity_reports_the_change(tmp_path) -> None:
    stored = {"h12_m": 0.415729e-6, "e12": 4.5, "h1_m": 1.65729e-7, "e1": 4.44084}
    config, notes = DesignFileService().load_with_notes(_old_file(tmp_path, version=2, **stored))
    assert config.ins_h2_m == pytest.approx(0.25e-6)
    assert config.e12 == pytest.approx(4.2928099, abs=1e-7)
    assert len(notes) == 2
    assert "h1 = 150 nm, h2 = 250 nm, V anod = 10 V, ε i = 4.2, ε Al = 9.8" in notes[0]
    assert notes[1] == "ε₁₂: в файле 4.50000, по слоям 4.29281"
    # Saved again it is version 3 with the layers and without H12/E12/H1/E1.
    saved = json.loads(DesignFileService().save(tmp_path / "new.smcdesign", config).read_text())
    assert saved["version"] == DESIGN_VERSION == 3
    assert {"h12_m", "e12", "h1_m", "e1"}.isdisjoint(saved["parameters"])
    assert saved["parameters"]["ins_h2_m"] == pytest.approx(0.25e-6)


def test_old_file_whose_h1_exceeds_h12_is_refused(tmp_path) -> None:
    path = _old_file(tmp_path, h12_m=0.2e-6, h1_m=0.3e-6)
    with pytest.raises(ValueError, match="не раскладываются на слои"):
        DesignFileService().load(path)


def test_current_file_refuses_the_old_direct_fields(tmp_path) -> None:
    path = DesignFileService().save(tmp_path / "current.smcdesign", S21Config())
    payload = json.loads(path.read_text())
    payload["parameters"]["h12_m"] = 0.4e-6
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Неизвестные параметры дизайна: h12_m"):
        DesignFileService().load(path)


def test_legacy_layers_helper() -> None:
    h1, h2 = layers_from_legacy_stack(1.65729e-7, 0.415729e-6)
    assert (h1, h2) == (pytest.approx(0.15e-6), pytest.approx(0.25e-6))
