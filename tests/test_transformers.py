"""Exact transformer conversion, checked against actual backend slices."""

from unittest.mock import Mock

import numpy as np
import pytest

from smcapp.api.impedance_transformers import ImpedanceTransformerCalculator
from smcapp.domain.transformers import derive_transformer_steps, transformer_length_m, transformer_slice_count


@pytest.mark.parametrize(
    "w1,w2,length,n,dl",
    [
        (6, 18, 7, 2, 1),
        (18, 6, 3, 2, 3 / 7),  # dl < 0.5 µm allowed since WP-054, so n=2 wins over 4
        (14, 49, 9.6, 1, 9.6 / 36),
        (14, 49, 4, 5, 0.5),  # n=1 would need dl≈0.11 µm
        (6.5, 18.5, 3.5, 2, 0.5),
        (6, 18, 10.5, 2, 1.5),
        (6, 6, 1, 2, 1),
    ],
)
def test_conversion_and_backend_geometry(w1, w2, length, n, dl) -> None:
    steps = derive_transformer_steps(w1 * 1e-6, w2 * 1e-6, length * 1e-6)
    assert steps.n_um == n
    assert steps.dl_m * 1e6 == pytest.approx(dl)
    assert steps.intervals == abs(w1 - w2) / n
    microstrip = Mock()
    microstrip.matrix.return_value = np.eye(2)
    calculator = ImpedanceTransformerCalculator(microstrip)
    calculator.transformer_matrix(100, w1 * 1e-6, w2 * 1e-6, steps.n_um, 4, 1e-6, None, None, 1e-6, 1e-6, steps.dl_m)
    calls = microstrip.matrix.call_args_list
    assert len(calls) == steps.intervals + 1
    assert sum(call.args[1] for call in calls) == pytest.approx(length * 1e-6)
    assert calls[0].args[2] == pytest.approx(w1 * 1e-6)
    assert calls[-1].args[2] == pytest.approx(w2 * 1e-6)


@pytest.mark.parametrize(
    "w1,w2,length", [(6, 18.5, 7), (6, 18, 100), (6, 6, 8), (0, 18, 7), (6, 18, 0), (6, float("nan"), 7)]
)
def test_impossible_input_is_rejected(w1, w2, length) -> None:
    with pytest.raises(ValueError):
        derive_transformer_steps(w1 * 1e-6, w2 * 1e-6, length * 1e-6)


def _steps(w1, w2, length):
    steps = derive_transformer_steps(w1 * 1e-6, w2 * 1e-6, length * 1e-6)
    return steps.n_um, round(steps.dl_m * 1e6, 9)


@pytest.mark.parametrize(
    "w1,w2,length,expected",
    [
        (8, 10, 4.5, (2, 2.25)),  # n=2 is preferred: dl=2.25 µm was refused outside 7 and 9 before WP-054
        (8, 10, 10, (2, 5)),  # the upper bound is included
        (8, 10, 15, (1, 5)),  # n=2 would need dl=7.5 µm
        (6, 10, 0.5, (4, 0.25)),  # n=2 would need dl≈0.17 µm
        (6, 10, 0.6, (2, 0.2)),  # the lower bound is included
    ],
)
def test_every_transformer_chooses_dl_from_0_2_to_5_um(w1, w2, length, expected) -> None:
    """WP-054 (owner, 09.11.2026): dl = 0.2…5 µm for every transformer, corners included."""
    assert _steps(w1, w2, length) == expected


@pytest.mark.parametrize("w1,w2,length", [(8, 10, 15.03), (8, 10, 30), (6, 10, 0.39)])
def test_dl_outside_0_2_to_5_um_is_rejected(w1, w2, length) -> None:
    with pytest.raises(ValueError, match="dl от 0.2 до 5 µm"):
        _steps(w1, w2, length)


@pytest.mark.parametrize("w1,w2,n", [(6, 18, 6), (6, 17.995, 6), (18, 6, 1.7), (6, 6, 2)])
def test_legacy_length_matches_inclusive_backend_arange(w1, w2, n) -> None:
    microstrip = Mock()
    microstrip.matrix.return_value = np.eye(2)
    calculator = ImpedanceTransformerCalculator(microstrip)
    calculator.transformer_matrix(100, w1 * 1e-6, w2 * 1e-6, n, 4, 1e-6, None, None, 1e-6, 1e-6, 0.9e-6)
    assert transformer_length_m(w1 * 1e-6, w2 * 1e-6, n, 0.9e-6) == pytest.approx(microstrip.matrix.call_count * 0.9e-6)


@pytest.mark.parametrize("w1,w2,n", [(6, 18, 6), (6, 17.995, 6), (18, 6, 1.7), (6, 6, 2), (14, 50, 6)])
def test_slice_count_shown_as_n_matches_backend(w1, w2, n) -> None:
    """The panel's n (number of slices) is exactly what the calculator slices."""
    microstrip = Mock()
    microstrip.matrix.return_value = np.eye(2)
    calculator = ImpedanceTransformerCalculator(microstrip)
    calculator.transformer_matrix(100, w1 * 1e-6, w2 * 1e-6, n, 4, 1e-6, None, None, 1e-6, 1e-6, 0.9e-6)
    assert transformer_slice_count(w1 * 1e-6, w2 * 1e-6, n) == microstrip.matrix.call_count


def test_slice_count_rejects_non_positive_width_step() -> None:
    with pytest.raises(ValueError, match="dw"):
        transformer_slice_count(6e-6, 18e-6, 0)
