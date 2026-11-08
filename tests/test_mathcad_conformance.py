"""WP-046 / BUG-023: calculation fixes D2 and D5 against the Mathcad HD35-H2 sheet.

Reference numbers are intermediate results cached in the owner's worksheet
``HD35-H2.xmcd`` (diagnosis ``docs/screenshots/MATHCAD-HD35-H2/check_points.txt``).
The worksheet curve itself is not stored in the repository.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace

import pytest
from numpy import pi

from smcapp.api import (
    FilmConductivity,
    ImpedanceCalculator,
    MicrostripLineCalculator,
    RadialStubCalculator,
    ResultsCalculator,
    SuperconductingGapCalculator,
)
from smcapp.api.radial_stub import RADIAL_STEP_M, radial_slice_count
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.design_files import DesignFileService
from smcapp.infrastructure.s21_calculator import S21CalculatorImpl, build_default_s21_calculator

_HA_M = 1.47 * 1.07e-9 * 10  # anodic Al2O3 thickness of the worksheet


def _series_permittivity(insulator_m: float, e_ins: float = 4.2, e_anod: float = 9.8) -> float:
    return e_ins * e_anod * (insulator_m + _HA_M) / (e_ins * _HA_M + e_anod * insulator_m)


# HD35-H2 inputs of the radial-stub branch and Mex04.  D1 (H12/E12 of the sheet,
# h2i = 0.25 µm) and D3 (Mathcad electrode 2 is the upper one) are still open
# owner decisions, so they are applied here as inputs: the worksheet H12/E12 and
# the Mathcad electrode 2 in EL1.
HD35_H2 = dict(
    temperature_k=4.4,
    tc_top_k=13.0,
    alpha_top=3.67,
    sigma0_top=0.975e6,
    d_top_m=0.5e-6,
    tc_bot_k=9.5,
    alpha_bot=3.63,
    sigma0_bot=18e6,
    d_bot_m=0.2e-6,
    h12_m=0.40e-6 + _HA_M,
    e12=_series_permittivity(0.40e-6),
    dw_m=0.5e-6,
    zrad0_ohm=50.0,
    zrad1_len_m=70e-6,
    zrad1_width_m=4e-6,
    radial_r_min_m=4e-6,
    radial_r_max_m=36e-6,
    radial_angle_deg=112.0,
    zrad3_len_m=6e-6,
    zrad3_width_m=4e-6,
    zrad4_len_m=3e-6,
    zrad4_width_m=6e-6,
    mex4_len_m=3e-6,
    mex4_width_m=6e-6,
)


class _WorksheetGap(SuperconductingGapCalculator):
    """Δ(T) of the worksheet; D4 (gap model) is still an open owner decision."""

    def delta_strong_coupling(self, temperature_k, critical_temperature_k, delta0=-1.0):
        return self.delta_bcs_approx(temperature_k, critical_temperature_k, delta0)


@dataclass
class _GroupSpy(ResultsCalculator):
    """Keep the outermost cascade ``(Mex04, Mex03, M_DCB, Mex02, Mex01)``."""

    cascade: tuple = ()

    def group(self, frequency_ghz, matrices):
        matrices = tuple(matrices)
        # Mex03 also has five factors; it is grouped inside the outer cascade.
        if len(matrices) == 5 and not self.cascade:
            self.cascade = matrices
        return super().group(frequency_ghz, matrices)


@dataclass
class _RadialSpy(RadialStubCalculator):
    admittances: dict | None = None

    def admittance(self, frequency_ghz, *args):
        value = super().admittance(frequency_ghz, *args)
        if self.admittances is not None:
            self.admittances[frequency_ghz] = value
        return value


def _relative(actual: complex, expected: complex) -> float:
    return abs(actual - expected) / abs(expected)


@pytest.fixture(scope="module")
def hd35_at_820ghz():
    """Run the real calculator at 820 GHz with exact (non-interpolated) films."""
    calculator = build_default_s21_calculator()
    radial = _RadialSpy(microstrip=calculator.microstrip, admittances={})
    results = _GroupSpy()
    calculator = replace(calculator, gap_calc=_WorksheetGap(), radial_stub=radial, results=results)
    config = replace(
        S21Config(),
        **HD35_H2,
        film_freq_start_ghz=810.0,
        film_freq_stop_ghz=821.0,
        film_freq_step_ghz=10.0,
        s21_freq_start_ghz=820.0,
        s21_freq_stop_ghz=821.0,
        s21_freq_step_ghz=10.0,
    )
    calculator.calculate(config)
    return radial.admittances[820.0], results.cascade[0](820.0)


def test_d5_radial_stub_impedance_matches_worksheet(hd35_at_820ghz) -> None:
    admittance, _ = hd35_at_820ghz
    zds0 = 1.0 / admittance
    # Mathcad ZDS[0](820) = 0.245567+5.20737j.  With 2 µm slices it was
    # 0.229643+5.88439j (relative error 1.3e-1).
    assert _relative(zds0, 0.245567 + 5.20737j) < 3e-3


def test_d2_mex04_matches_worksheet_at_sweep_frequency(hd35_at_820ghz) -> None:
    _, mex04 = hd35_at_820ghz
    expected = {
        (0, 0): 0.988351 + 0.000358875j,
        (0, 1): 0.0620743 + 2.01886j,  # was 0.00287+1.63584j with the line at f0 = 650 GHz
        (1, 0): 0.00560259 - 0.0710182j,
        (1, 1): 1.15721 + 0.00656362j,
    }
    for index, value in expected.items():
        assert _relative(mex04[index], value) < 3e-3, index


class _ConstantFilm:
    """Cheap Mattis–Bardeen stand-in: these tests only follow call arguments."""

    def sigma1(self, sigma0, frequency_ghz, temperature_k, gap_ev):
        return 1e5

    def sigma2(self, sigma0, frequency_ghz, temperature_k, gap_ev):
        return 1e8


@dataclass
class _MatrixSpy(MicrostripLineCalculator):
    calls: list | None = None

    def matrix(self, frequency_ghz, length_m, width_m, *args):
        if self.calls is not None:
            self.calls.append((frequency_ghz, length_m, width_m))
        return super().matrix(frequency_ghz, length_m, width_m, *args)


def test_d2_mex04_line_follows_sweep_frequency_not_650_ghz() -> None:
    calculator = build_default_s21_calculator()
    microstrip = _MatrixSpy(impedance=ImpedanceCalculator(), calls=[])
    calculator = replace(calculator, mb_calc=_ConstantFilm(), microstrip=microstrip)
    calculator = replace(calculator, radial_stub=RadialStubCalculator(microstrip=microstrip))
    config = S21Config(s21_freq_start_ghz=300.0, s21_freq_stop_ghz=1000.0, s21_freq_step_ghz=600.0)

    calculator.calculate(config)
    mex4 = (config.mex4_len_m, config.mex4_width_m + config.dw_m)
    frequencies = [f for f, length, width in microstrip.calls if (length, width) == mex4]
    assert sorted(set(frequencies)) == [300.0, 900.0]


@dataclass
class _TransformSpy(MicrostripLineCalculator):
    slices: list | None = None

    def transform_impedance(self, frequency_ghz, load, length_m, width_m, *args):
        self.slices.append((length_m, width_m))
        return super().transform_impedance(frequency_ghz, load, length_m, width_m, *args)


@pytest.mark.parametrize("radius_um,count", [(36.0, 36), (35.6, 36), (35.4, 35), (1.0, 1), (0.4, 0)])
def test_d5_radial_stub_slices_from_outer_edge_to_neck(radius_um, count) -> None:
    microstrip = _TransformSpy(impedance=ImpedanceCalculator(), slices=[])
    film = FilmConductivity([100.0, 1000.0], [1e5, 1e5], [1e8, 1e8])
    stub = RadialStubCalculator(microstrip=microstrip)
    admittance = stub.admittance(650.0, 4e-6, radius_um * 1e-6, 112.0, 4.29, 0.416e-6, film, film, 0.5e-6, 0.2e-6)

    theta = 112.0 * 2.0 * pi / 360.0
    assert radial_slice_count(radius_um * 1e-6) == count
    assert len(microstrip.slices) == count
    assert all(length == RADIAL_STEP_M == 1e-6 for length, _ in microstrip.slices)
    # WID[r] = Wneck + ΔRAD·(r−1)·θ for r = N…1: the last slice is the neck itself.
    expected_widths = [4e-6 + 1e-6 * (r - 1) * theta for r in range(count, 0, -1)]
    assert [width for _, width in microstrip.slices] == pytest.approx(expected_widths, rel=1e-12)
    if count == 0:
        assert admittance == pytest.approx(1e-10)


def test_retired_f0_parameter_is_accepted_and_not_saved_again(tmp_path) -> None:
    original = S21Config(temperature_k=4.4, radial_r_max_m=36e-6)
    parameters = {"temperature_k": 4.4, "radial_r_max_m": 36e-6, "f0_ghz": 650.0}
    source = tmp_path / "HD35-old.aocdesign"
    source.write_text(json.dumps({"format": "AOCapp Design", "version": 1, "parameters": parameters}))

    service = DesignFileService()
    loaded = service.load(source)
    assert loaded == original
    assert not hasattr(loaded, "f0_ghz")
    saved = json.loads(service.save(tmp_path / "new.smcdesign", loaded).read_text())
    assert "f0_ghz" not in saved["parameters"]
    assert "f0_ghz" not in {info.name for info in S21Config().ui_fields()}
