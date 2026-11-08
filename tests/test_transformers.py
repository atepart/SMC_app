"""Exact transformer conversion, checked against actual backend slices."""

from unittest.mock import Mock

import numpy as np
import pytest

from smcapp.api.impedance_transformers import ImpedanceTransformerCalculator
from smcapp.domain.transformers import derive_transformer_steps, transformer_dl_max_um, transformer_length_m


@pytest.mark.parametrize(
    "w1,w2,length,n,dl",
    [
        (6, 18, 7, 2, 1),
        (18, 6, 3, 4, 0.75),
        (14, 49, 9.6, 5, 1.2),
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
    "w1,w2,length", [(6, 18.5, 7), (6, 18, 100), (6, 6, 2), (0, 18, 7), (6, 18, 0), (6, float("nan"), 7)]
)
def test_impossible_input_is_rejected(w1, w2, length) -> None:
    with pytest.raises(ValueError):
        derive_transformer_steps(w1 * 1e-6, w2 * 1e-6, length * 1e-6)


def _steps(w1, w2, length, corner: bool):
    steps = derive_transformer_steps(w1 * 1e-6, w2 * 1e-6, length * 1e-6, max_dl_um=transformer_dl_max_um(corner))
    return steps.n_um, round(steps.dl_m * 1e6, 9)


@pytest.mark.parametrize(
    "w1,w2,length,corner,other",
    [
        # n=2 is preferred once dl=2.25 µm is allowed; otherwise n=1, dl=1.5.
        (8, 10, 4.5, (2, 2.25), (1, 1.5)),
        (6, 10, 6, (2, 2), (1, 1.2)),
        (8, 10, 9, (1, 3), None),  # the upper bound is included
        (6, 10, 1.5, (2, 0.5), (2, 0.5)),  # the lower bound is included
    ],
)
def test_corner_transformers_accept_dl_up_to_3_um(w1, w2, length, corner, other) -> None:
    """GitHub #10: elements 7 and 9 accept dl = 0.5…3 µm, the others 0.5…1.5 µm."""
    assert _steps(w1, w2, length, True) == corner
    if other is None:
        with pytest.raises(ValueError, match="dl от 0.5 до 1.5 µm"):
            _steps(w1, w2, length, False)
    else:
        assert _steps(w1, w2, length, False) == other


@pytest.mark.parametrize("w1,w2,length", [(8, 10, 9.03), (8, 10, 12), (6, 10, 0.4)])
def test_corner_transformers_still_reject_dl_outside_0_5_to_3_um(w1, w2, length) -> None:
    with pytest.raises(ValueError, match="dl от 0.5 до 3 µm"):
        _steps(w1, w2, length, True)


def test_default_limit_is_unchanged() -> None:
    with pytest.raises(ValueError, match="dl от 0.5 до 1.5 µm"):
        derive_transformer_steps(6e-6, 10e-6, 9e-6)


@pytest.mark.parametrize("w1,w2,n", [(6, 18, 6), (6, 17.995, 6), (18, 6, 1.7), (6, 6, 2)])
def test_legacy_length_matches_inclusive_backend_arange(w1, w2, n) -> None:
    microstrip = Mock()
    microstrip.matrix.return_value = np.eye(2)
    calculator = ImpedanceTransformerCalculator(microstrip)
    calculator.transformer_matrix(100, w1 * 1e-6, w2 * 1e-6, n, 4, 1e-6, None, None, 1e-6, 1e-6, 0.9e-6)
    assert transformer_length_m(w1 * 1e-6, w2 * 1e-6, n, 0.9e-6) == pytest.approx(microstrip.matrix.call_count * 0.9e-6)
