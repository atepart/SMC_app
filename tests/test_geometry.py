"""Physical scale, topology and dimension contracts for the SVG pipeline."""

from __future__ import annotations

import re
from dataclasses import replace
from math import hypot
from xml.etree import ElementTree

import pytest
from numpy import arange

from aocapp.domain.models import Point, Rect, StructureGeometry, TextLabel
from aocapp.domain.s21_models import S21Config
from aocapp.domain.transformers import ELEMENT_NUMBERS
from aocapp.infrastructure.geometry import DC_FILL, LENGTH_SCALE, WIDTH_SCALE, IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl


def _elements(geometry):
    return {element.element_id: element for element in geometry.elements}


def _parameters(element):
    return {parameter.label: parameter.value for parameter in element.parameters}


def _endpoints(data):
    start = re.match(r"M([^,]+),([^ ]+)", data)
    end = re.search(r" L([^, ]+),([^ ]+)$", data)
    assert start and end
    return Point(*map(float, start.groups())), Point(*map(float, end.groups()))


def test_preview_contains_every_section_without_matrix_frames() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    assert [e.number for e in geometry.elements if e.number is not None] == list(range(1, 13))
    assert len([e for e in geometry.elements if e.element_id.startswith("T")]) == 7
    assert len(geometry.elements) == 19
    assert set(_elements(geometry)) >= {"DC", "SIS", "SIS-line", "Ww1", "Ww3", "Ww4", "Radial"}
    # The overview has only two DC electrodes, with a genuinely open slot.
    left, right = [p for p in geometry.overview.polygons if p.fill == DC_FILL]
    left_inner = max(p.x for p in left.points)
    right_inner = min(p.x for p in right.points)
    assert left_inner < right_inner
    assert sum(p.x == left_inner for p in left.points) == 2
    assert sum(p.x == right_inner for p in right.points) == 2


def test_transformer_length_matches_backend_slice_formula() -> None:
    assert IntegratedStructureCalculator._transformer_physical_length_um(6e-6, 18e-6, 6, 0.9e-6) == pytest.approx(2.7)


def test_svg_has_element_dimensions_and_no_calculation_boxes() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    svg = SvgRendererImpl().render(geometry)
    ElementTree.fromstring(svg)
    for obsolete in ("Mex01", "Mex02", "Mex03", "Mex04", "Mrad", "Mdcb", "MLsis", "stroke-dasharray"):
        assert obsolete not in svg
    for label in (
        "ФФО",
        "50 Ω",
        "DC block",
        "Радиальные шлейфы ×2",
        "SIS · условный символ",
        "W1=14 µm",
        "W2=49 µm",
        "L=9.6 µm",
    ):
        assert label in svg
    assert 'orient="auto-start-reverse"' in svg
    assert "rotate(-90 " in svg
    assert "Wslotэфф=3.5" in svg
    assert "W1эфф=14.5" in svg
    assert geometry.overview.dimensions == []
    assert {dim.element_id for dim in geometry.dimensions} == set(_elements(geometry)) - {"SIS"}


def test_qt_renders_multiline_parameters_on_separate_baselines() -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    geometry = StructureGeometry(
        polygons=[],
        rects=[],
        circles=[],
        lines=[],
        dimensions=[],
        labels=[TextLabel(Point(10, 25), "Lso=8 µm\nWms=9 µm", font_size=16)],
        bounds=Rect(0, 0, 200, 70),
    )
    renderer = QSvgRenderer(SvgRendererImpl().render(geometry).encode())
    picture = QImage(200, 70, QImage.Format.Format_ARGB32)
    picture.fill(0xFFFFFFFF)
    painter = QPainter(picture)
    renderer.render(painter)
    painter.end()
    # Each requested baseline must contain ink, with whitespace between rows.
    ink_rows = [y for y in range(70) if any(picture.pixelColor(x, y).lightness() < 100 for x in range(10, 150))]
    assert any(12 <= y < 25 for y in ink_rows)
    assert any(32 <= y < 45 for y in ink_rows)
    assert not any(28 <= y <= 32 for y in ink_rows)


def test_dimensions_use_raw_inputs_and_corrected_metal_widths() -> None:
    config = S21Config(dw_m=0.75e-6, msl_8_width_m=41e-6, msl_8_len_m=23e-6, w_slot_m=4e-6, l_slot_m=37e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    line = _elements(geometry)["MSL8"]
    assert _parameters(line) == pytest.approx({"W": 41, "L": 23})
    assert line.input_port.width == pytest.approx(41.75 * 2)
    assert line.bounds.width == pytest.approx(23 * 2)
    svg = SvgRendererImpl().render(geometry)
    for text in ("W=41 µm", "L=23 µm", "Wэфф=41.75", "Wslotэфф=3.25", "Lslot=37"):
        assert text in svg


def test_sis_is_a_readable_symbol_in_the_calculated_feed() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    elements = _elements(geometry)
    symbol = geometry.overview.circles[0]
    feed = elements["SIS-line"]
    assert feed.bounds.x < symbol.center.x < feed.bounds.right
    assert 0 < symbol.radius < min(feed.bounds.width, feed.bounds.height) / 2
    assert feed.bounds.right < elements["Radial"].input_port.center.x
    assert _parameters(elements["SIS"]) == pytest.approx({"S": 0.8, "W SIS (расч.)": 4})
    changed = IntegratedStructureCalculator().calculate(S21Config(sis_area_um2=20, sis_width_um=8))
    # Area/model-width edits must not invent a different lead length or metal.
    assert changed.overview.polygons == geometry.overview.polygons
    assert changed.overview.rects == geometry.overview.rects
    assert changed.overview.paths == geometry.overview.paths
    assert changed.overview.circles == geometry.overview.circles
    assert _parameters(_elements(changed)["SIS"]) == pytest.approx({"S": 20, "W SIS (расч.)": 8})


def test_sis_radial_conductor_has_no_artificial_internal_dividers() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    elements = _elements(geometry)
    for name in ("Ww4", "Ww3", "Radial", "Ww1"):
        x = elements[name].input_port.center.x
        assert not any(line.start.x == line.end.x == x for line in geometry.overview.lines)


def test_sis_line_dimensions_use_its_editable_fields_not_sis_model_width() -> None:
    config = S21Config(mex4_len_m=12e-6, mex4_width_m=9e-6, sis_width_um=25, sis_area_um2=1.2)
    geometry = IntegratedStructureCalculator().calculate(config)
    line = _elements(geometry)["SIS-line"]
    assert _parameters(line) == pytest.approx({"L": 12, "W": 9})
    assert line.bounds.width == pytest.approx(24)
    assert line.bounds.height == pytest.approx(19)
    assert {dim.label for dim in geometry.dimensions if dim.element_id == "SIS-line"} == {"L=12", "Wэфф=9.5"}


@pytest.mark.parametrize("config", [S21Config(), S21Config(msl_8_len_m=1e-9, radial_r_max_m=90e-6, l_slot_m=80e-6)])
def test_number_labels_and_dimension_views_remain_separate(config) -> None:
    geometry = IntegratedStructureCalculator().calculate(config)
    labels = [label for label in geometry.overview.labels if label.text.isdigit()]
    # Labels are 10 units high and <=12 wide; require real clearance in 2D.
    assert all(
        abs(a.position.x - b.position.x) >= 18 or abs(a.position.y - b.position.y) >= 14
        for i, a in enumerate(labels)
        for b in labels[i + 1 :]
    )
    assert all(geometry.bounds.y < label.position.y < geometry.bounds.bottom for label in geometry.labels)
    main_bottom = max(e.bounds.bottom for e in geometry.elements)
    assert all(min(d.start.y, d.end.y) > main_bottom for d in geometry.dimensions)


@pytest.mark.parametrize("angle", [1, 60, 113, 180, 220, 359])
def test_radial_arcs_use_radius_angle_and_exact_shared_join_points(angle) -> None:
    config = S21Config(radial_angle_deg=angle, zrad3_width_m=7e-6, zrad1_width_m=5e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    elements = _elements(geometry)
    radial = elements["Radial"]
    assert radial.input_port == elements["Ww3"].output_port
    assert radial.output_port == elements["Ww1"].input_port
    paths = {p.element_id: p for p in geometry.overview.paths}
    dimension_fan = next(p for p in geometry.paths if p.element_id == "radial-dimension-view")
    angle_label = next(label for label in geometry.labels if label.text == f"θ={angle:g}°")
    assert dimension_fan.bounds.bottom < angle_label.position.y - angle_label.font_size
    for name, start, end in (
        ("radial-upper", radial.input_port.top, radial.output_port.top),
        ("radial-lower", radial.input_port.bottom, radial.output_port.bottom),
    ):
        path = paths[name]
        assert path.data.count("A") == 1
        actual_start, actual_end = _endpoints(path.data)
        assert actual_start.x == pytest.approx(start.x, abs=1e-9)
        assert actual_start.y == pytest.approx(start.y, abs=1e-9)
        assert actual_end.x == pytest.approx(end.x, abs=1e-9)
        assert actual_end.y == pytest.approx(end.y, abs=1e-9)
        assert f"A76,76 0 {int(angle > 180)}" in path.data
    # No extra flange before the first taper.
    first = elements["T7"].bounds.x
    assert not any(rect.rect.right <= first for rect in geometry.overview.rects)


def test_every_transformer_size_matches_actual_backend_slices() -> None:
    values = {}
    for i in range(1, 8):
        values.update(
            {
                f"transf_{i}_w_start_m": (6 + i) * 1e-6,
                f"transf_{i}_w_end_m": (16 + i) * 1e-6,
                f"transf_{i}_dwdl_um": 2,
                f"transf_{i}_dl_m": (0.5 + i * 0.1) * 1e-6,
            }
        )
    config = S21Config(**values)
    geometry = IntegratedStructureCalculator().calculate(config)
    elements = _elements(geometry)
    for i in range(1, 8):
        element = elements[f"T{i}"]
        w1, w2 = getattr(config, f"transf_{i}_w_end_m"), getattr(config, f"transf_{i}_w_start_m")
        dl = getattr(config, f"transf_{i}_dl_m")
        length = len(arange(min(w1, w2), max(w1, w2) + 0.01e-6, 2e-6)) * dl * 1e6
        assert element.number == ELEMENT_NUMBERS[f"T{i}"]
        assert _parameters(element) == pytest.approx({"W1": w1 * 1e6, "W2": w2 * 1e6, "L": length})
        assert element.input_port.width == pytest.approx((w1 + config.dw_m) * 1e6 * 2)
        assert element.output_port.width == pytest.approx((w2 + config.dw_m) * 1e6 * 2)
        assert element.bounds.width == pytest.approx(length * 2)


@pytest.mark.parametrize("length_um,width_um", [(0.001, 0.5), (23, 41), (500, 200)])
def test_line_dimensions_are_unclamped_with_one_scale(length_um, width_um) -> None:
    config = S21Config(msl_8_len_m=length_um * 1e-6, msl_8_width_m=width_um * 1e-6)
    line = _elements(IntegratedStructureCalculator().calculate(config))["MSL8"]
    assert LENGTH_SCALE == WIDTH_SCALE
    assert line.bounds.width == pytest.approx(length_um * LENGTH_SCALE)
    assert line.bounds.height == pytest.approx((width_um + config.dw_m * 1e6) * WIDTH_SCALE)


def test_dc_slot_and_feed_dimensions_follow_calculation_inputs() -> None:
    config = S21Config(w_slot_m=2e-6, l_slot_m=120e-6, mex4_len_m=20e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    dc = _elements(geometry)["DC"]
    left, right = dc.polygon[:7], dc.polygon[7:]
    assert min(p.x for p in right) - max(p.x for p in left) == pytest.approx((2 - config.dw_m * 1e6) * 2)
    assert max(p.y for p in left) - left[2].y == pytest.approx(120 * 2)
    feed = _elements(geometry)["SIS-line"]
    assert feed.bounds.width == pytest.approx(20 * 2)
    assert feed.bounds.height == pytest.approx((config.mex4_width_m + config.dw_m) * 1e6 * 2)
    assert len([d for d in geometry.dimensions if d.element_id == "DC"]) == 5


@pytest.mark.parametrize("offset_um", [8, 16])
def test_lso_arrow_is_tied_to_marked_apex_and_parallel_start(offset_um) -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config(lso_m=offset_um * 1e-6))
    dc = _elements(geometry)["DC"]
    apex, parallel = [c.center for c in geometry.circles if c.fill == "#64748b"]
    arrow = next(d for d in geometry.dimensions if d.element_id == "DC" and d.label.startswith("Lso="))
    assert arrow.start.y == apex.y
    assert arrow.end.y == parallel.y
    assert arrow.label == f"Lso={offset_um}"
    assert {label.text for label in geometry.labels} >= {"A", "B", "Lso: A (питание) → B (параллельный участок)"}
    for point, end in ((apex, arrow.start), (parallel, arrow.end)):
        assert any(line.start == point and line.end.x > end.x and line.end.y == end.y for line in geometry.lines)
    length = next(d for d in geometry.dimensions if d.element_id == "DC" and d.label.startswith("Lslot="))
    zoom = (length.end.y - length.start.y) / (36 * LENGTH_SCALE)
    assert arrow.end.y - arrow.start.y == pytest.approx(offset_um * LENGTH_SCALE * zoom)
    # Both overview and enlargement share these auxiliary lead records.
    assert len(dc.auxiliary_lines) == 4
    assert all(line in geometry.overview.lines for line in dc.auxiliary_lines)


def test_radial_lines_have_exact_lengths_widths_and_connected_ports() -> None:
    config = S21Config(zrad1_len_m=100e-6, zrad1_width_m=20e-6, zrad3_len_m=1e-6, zrad4_len_m=80e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    elements = _elements(geometry)
    for index in (4, 3, 1):
        element = elements[f"Ww{index}"]
        assert element.bounds.width == pytest.approx(getattr(config, f"zrad{index}_len_m") * 1e6 * 2)
        assert element.bounds.height == pytest.approx((getattr(config, f"zrad{index}_width_m") + config.dw_m) * 1e6 * 2)
    chain = [e for e in geometry.elements if e.input_port is not None]
    for a, b in zip(chain, chain[1:]):
        assert a.output_port.center.x == pytest.approx(b.input_port.center.x, abs=1e-9)
        assert a.output_port.center.y == b.input_port.center.y == 0


def test_default_width_mismatches_remain_steps_not_gaps_or_input_changes() -> None:
    config = S21Config()
    geometry = IntegratedStructureCalculator().calculate(config)
    elements = _elements(geometry)
    assert elements["T7"].output_port.center == elements["MSL8"].input_port.center
    assert elements["MSL8"].output_port.center == elements["T6"].input_port.center
    assert elements["T7"].output_port.width == 99
    assert elements["MSL8"].input_port.width == 101
    assert elements["T6"].input_port.width == 97
    # One thin seam at the overlap, not two thick polygon outlines.
    joint_x = elements["T7"].output_port.center.x
    seams = [
        line for line in geometry.overview.lines if line.start.x == joint_x == line.end.x and line.stroke_width == 0.45
    ]
    assert len(seams) == 1
    assert config == S21Config()


def test_dimensioned_views_use_one_zoom_for_both_axes() -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    elements = _elements(geometry)
    for element in elements.values():
        if element.input_port is None or element.element_id in {"DC", "Radial"}:
            continue
        dims = [d for d in geometry.dimensions if d.element_id == element.element_id]
        length = next(d for d in dims if d.label.startswith("L="))
        width = next(d for d in dims if d.label.startswith(("Wэфф=", "W1эфф=")))
        x_zoom = hypot(length.end.x - length.start.x, length.end.y - length.start.y) / element.bounds.width
        y_zoom = hypot(width.end.x - width.start.x, width.end.y - width.start.y) / element.input_port.width
        assert x_zoom == pytest.approx(y_zoom)


@pytest.mark.parametrize(
    "field,value",
    [
        ("msl_8_len_m", 0),
        ("w_slot_m", 0.1e-6),
        ("radial_r_max_m", 0),
        ("radial_angle_deg", 360),
        ("radial_angle_deg", float("nan")),
    ],
)
def test_invalid_geometry_is_reported_instead_of_producing_broken_svg(field, value) -> None:
    with pytest.raises(ValueError):
        IntegratedStructureCalculator().calculate(replace(S21Config(), **{field: value}))
