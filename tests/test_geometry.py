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
    dc_rects = [shape.rect for shape in geometry.rects if shape.fill == DC_FILL]
    assert len(dc_rects) == 8

    # Four long arms form two separate folded-U conductors.  In particular,
    # the facing inner arms must not bridge the central galvanic gap.
    arms = sorted((rect for rect in dc_rects if rect.height > rect.width * 2.0), key=lambda rect: rect.x)
    assert len(arms) == 4
    assert arms[1].right < arms[2].x

    register = next(shape.rect for shape in geometry.rects if shape.stroke == "#94a3b8")
    assert register.x > max(group.rect.right for group in geometry.groups)
    assert all(group.title_rotation_deg == 0.0 for group in geometry.groups)


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
    assert "ФФО" in svg
    assert "SIS/load" not in svg
    assert "Wslot=4 µm; Wэфф=3.5 µm" in svg
    assert 'orient="auto-start-reverse"' in svg
    assert "rotate(-90 " in svg
    assert {f"T{index}" for index in range(1, 8)} <= {label.text for label in geometry.labels}
    assert {f"MSL{index}" for index in range(4, 9)} <= {label.text for label in geometry.labels}
    assert not any(label.text.strip().isdigit() for label in geometry.labels)
    assert "Размеры из параметров, µm" in svg
    assert "DC-break" in svg
    assert "Radial shunt ×2" in svg
    assert "SIS" in svg


def test_size_register_uses_raw_inputs_and_backend_corrected_widths() -> None:
    geometry = IntegratedStructureCalculator().calculate(
        S21Config(
            dw_m=0.75e-6,
            msl_8_width_m=41e-6,
            msl_8_len_m=23e-6,
            w_slot_m=4e-6,
            l_slot_m=37e-6,
        )
    )
    svg = SvgRendererImpl().render(geometry)

    assert "MSL8: W=41 (Wэфф=41.75); L=23" in svg
    assert "slot: W=4 (Wэфф=3.25); L=37" in svg
