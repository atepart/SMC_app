"""Tests that keep the preview aligned with the calculated network."""

from __future__ import annotations

import pytest
from numpy import arange

from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.geometry import DC_FILL, TRANSFORMER_FILL, IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl


def test_preview_contains_every_calculated_matrix_group_and_transformer() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())

    assert [group.title for group in geometry.groups] == ["Mex01", "Mex02", "Mdcb", "Mex03", "Mrad", "MLsis", "Mex04"]
    assert sum(polygon.fill == TRANSFORMER_FILL for polygon in geometry.polygons) == 7
    assert {p.element_id for p in geometry.paths if p.element_id in {"radial-upper", "radial-lower"}} == {
        "radial-upper",
        "radial-lower",
    }
    dc_polygons = [shape for shape in geometry.polygons if shape.fill == DC_FILL]
    assert len(dc_polygons) == 2

    # Exactly two conductors face one another across an open slot.  Each inner
    # face is a straight vertical segment; there are no U-shaped return arms.
    left, right = sorted(dc_polygons, key=lambda shape: min(point.x for point in shape.points))
    left_inner_x = max(point.x for point in left.points)
    right_inner_x = min(point.x for point in right.points)
    assert left_inner_x < right_inner_x
    assert sum(point.x == left_inner_x for point in left.points) == 2
    assert sum(point.x == right_inner_x for point in right.points) == 2
    assert not any(shape.fill == DC_FILL for shape in geometry.rects)

    register = next(shape.rect for shape in geometry.rects if shape.stroke == "#94a3b8")
    assert register.y > max(group.rect.bottom for group in geometry.groups)
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
    assert "Wslot=4; Wэфф=3.5; Lslot=36" in svg
    assert 'orient="auto-start-reverse"' in svg
    assert "rotate(-90 " in svg
    assert "нумерация Mathcad" not in svg
    assert "MSL8" not in svg
    numbers = [label.text for label in geometry.labels if label.text.isdigit()]
    assert numbers == [str(index) for index in range(1, 13)]
    assert "Обозначения и размеры" in svg
    assert "DC-развязка" in svg
    assert "щелевая антенна" in svg
    assert "Радиальные шлейфы ×2" in svg
    assert "SIS · туннельный переход" in svg
    assert "схема не в масштабе" in svg


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

    assert "2  —  линия · W 41; L 23" in svg
    assert "DW=0.75" in svg
    assert "Wslot=4; Wэфф=3.25; Lslot=37" in svg


def test_sis_rectangle_and_circle_are_left_of_radial_neck() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    sis = next(circle for circle in geometry.circles if circle.fill == "#fff")
    box = next(shape.rect for shape in geometry.rects if shape.stroke_width == 1.2)
    assert box.x < sis.center.x < box.right
    assert box.y < sis.center.y < box.bottom
    output = next(p for p in geometry.paths if p.element_id == "radial-output")
    radial_center_x = output.bounds.x
    assert box.right < radial_center_x
    mlsis = next(group.rect for group in geometry.groups if group.title == "MLsis")
    assert mlsis.x < box.x and box.right < mlsis.right < radial_center_x
    # Downward fingers are longer below the feed than above it.
    for polygon in (p for p in geometry.polygons if p.fill == DC_FILL):
        assert max(p.y for p in polygon.points) - sis.center.y > sis.center.y - min(p.y for p in polygon.points)


@pytest.mark.parametrize("config", [S21Config(), S21Config(msl_8_len_m=1e-9, radial_r_max_m=90e-6, l_slot_m=80e-6)])
def test_number_callouts_and_legend_remain_separate(config) -> None:
    geometry = IntegratedStructureCalculator().calculate(config)
    number_labels = [label for label in geometry.labels if label.text.isdigit()]
    assert all(b.position.x - a.position.x >= 38 for a, b in zip(number_labels, number_labels[1:]))
    register = next(shape.rect for shape in geometry.rects if shape.stroke == "#94a3b8")
    assert all(point.y < register.y for poly in geometry.polygons for point in poly.points)
    assert all(path.bounds.bottom < register.y for path in geometry.paths)
    assert all(geometry.bounds.y < label.position.y < geometry.bounds.bottom for label in geometry.labels)


def test_clean_radial_reference_uses_bezier_rims_and_stepped_neck() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    paths = {path.element_id: path for path in geometry.paths}
    for name in ("radial-upper", "radial-lower"):
        # A real quadratic Bézier rim remains smooth at any SVG zoom.
        assert paths[name].data.count("Q") == 1
        assert paths[name].data.count("L") == 2
        assert "Z" not in paths[name].data
    assert paths["radial-output"].data.count("M") == 3
    svg = SvgRendererImpl().render(geometry)
    assert '<path id="radial-upper"' in svg
    # No extra rectangular feed/flange before the first transformer.
    first_taper_x = min(p.x for poly in geometry.polygons if poly.fill == TRANSFORMER_FILL for p in poly.points)
    overview = geometry.overview
    assert overview is not None
    assert not any(rect.rect.right <= first_taper_x for rect in overview.rects)


def test_every_number_and_size_matches_config_and_backend() -> None:
    from aocapp.domain.transformers import ELEMENT_NUMBERS

    values = {}
    for index in range(1, 8):
        values.update(
            {
                f"transf_{index}_w_start_m": (6 + index) * 1e-6,
                f"transf_{index}_w_end_m": (16 + index) * 1e-6,
                f"transf_{index}_dwdl_um": 2,
                f"transf_{index}_dl_m": (0.5 + index * 0.1) * 1e-6,
            }
        )
    config = S21Config(
        **values,
        zrad1_width_m=7.5e-6,
        zrad1_len_m=61e-6,
        zrad3_width_m=5.5e-6,
        zrad3_len_m=6.5e-6,
        zrad4_width_m=8.5e-6,
        zrad4_len_m=7.5e-6,
    )
    geometry = IntegratedStructureCalculator().calculate(config)
    svg = SvgRendererImpl().render(geometry)
    tapers = [shape for shape in geometry.polygons if shape.fill == TRANSFORMER_FILL]
    for index, shape in zip(range(7, 0, -1), tapers):
        w1 = getattr(config, f"transf_{index}_w_end_m")
        w2 = getattr(config, f"transf_{index}_w_start_m")
        dl = getattr(config, f"transf_{index}_dl_m")
        length = len(arange(min(w1, w2), max(w1, w2) + 0.01e-6, 2e-6)) * dl * 1e6
        number = ELEMENT_NUMBERS[f"T{index}"]
        assert f"{number}  —  переход · W1 {w1 * 1e6:g}; W2 {w2 * 1e6:g}; L {length:g}" in svg
        # Metal envelope uses the same reversed endpoints plus DW as calculation.
        assert shape.points[3].y - shape.points[0].y == pytest.approx((w1 + config.dw_m) * 1e6 * 2)
        assert shape.points[2].y - shape.points[1].y == pytest.approx((w2 + config.dw_m) * 1e6 * 2)
    for text in ("Ww1=7.5", "Lw1=61", "Ww3=5.5", "Lw3=6.5", "Ww4=8.5", "Lw4=7.5"):
        assert text in svg
