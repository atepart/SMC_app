"""Tests that keep the preview aligned with the calculated network."""

from __future__ import annotations

import pytest

from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.geometry import DC_FILL, RADIAL_FILL, TRANSFORMER_FILL, IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl


def test_preview_contains_every_calculated_matrix_group_and_transformer() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())

    assert [group.title for group in geometry.groups] == ["Mex01", "Mex02", "Mdcb", "Mex03", "Mrad", "MLsis", "Mex04"]
    assert sum(polygon.fill == TRANSFORMER_FILL for polygon in geometry.polygons) == 7
    assert sum(polygon.fill == RADIAL_FILL for polygon in geometry.polygons) == 2
    assert sum(rect.fill == DC_FILL for rect in geometry.rects) == 4


def test_transformer_length_matches_backend_slice_formula() -> None:
    calculator = IntegratedStructureCalculator()

    # T1: widths 6→18 µm in 6 µm steps produces [6, 12, 18].
    # Three slices at dL=0.9 µm result in a 2.7 µm physical length.
    length_um = calculator._transformer_physical_length_um(6e-6, 18e-6, 6.0, 0.9e-6)

    assert length_um == pytest.approx(2.7)


def test_svg_renders_dotted_matrix_frames_and_engineering_labels() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())

    svg = SvgRendererImpl().render(geometry)

    assert 'stroke-dasharray="2 2"' in svg
    assert "Mex01" in svg
    assert "Mdcb" in svg
    assert "Mex04" in svg
    assert "50 Ω" in svg
    assert "Wslot=3.5 µm" in svg
