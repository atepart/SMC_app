"""Physical scale, topology and dimension contracts for the SVG pipeline."""

from __future__ import annotations

import re
from dataclasses import replace
from math import hypot
from xml.etree import ElementTree

import pytest
from numpy import arange

from smcapp.domain.models import Point, Rect, StructureGeometry, SvgColorScheme, TextLabel
from smcapp.domain.s21_models import S21Config
from smcapp.domain.transformers import ELEMENT_NUMBERS
from smcapp.infrastructure.callouts import point_in_polygon, segment_hits_box, segments_intersect, text_box
from smcapp.infrastructure.geometry import DC_FILL, LENGTH_SCALE, SLOT_FILL, WIDTH_SCALE, IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import DARK_SVG_SCHEME, SvgRendererImpl


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
    assert [e.number for e in geometry.elements] == list(range(1, 19))
    assert len([e for e in geometry.elements if e.element_id.startswith("T")]) == 7
    assert len(geometry.elements) == 18
    assert set(_elements(geometry)) >= {"DC", "SIS", "SIS-line", "Ww1", "Ww3", "Radial"}
    assert "Ww4" not in _elements(geometry)  # part of 14 «Линия SIS» (GitHub #10)
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
    # No sheet title and no ФФО caption: the drawing speaks for itself.
    assert "Структура HD35" not in svg
    assert ">ФФО<" not in svg
    for label in (
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
    # GitHub #10: on the joint of the parts L1/W1 and L2/W2 of 14, on the axis.
    first, second = feed.auxiliary_rects
    assert symbol.center.x == pytest.approx(first.right) == pytest.approx(second.x)
    assert symbol.center.y == pytest.approx(feed.input_port.center.y)
    assert elements["SIS"].bounds.x < first.right < elements["SIS"].bounds.right
    # The size follows the joined widths, not the length of 14.
    short = _elements(IntegratedStructureCalculator().calculate(S21Config(mex4_len_m=0.5e-6)))
    assert short["SIS"].bounds.width == pytest.approx(elements["SIS"].bounds.width)
    assert 0 < symbol.radius < feed.bounds.height / 2  # inside the conductor width
    assert feed.bounds.right < elements["Radial"].input_port.center.x
    assert _parameters(elements["SIS"]) == pytest.approx({"S": 0.8, "Wb (расч.)": 4})
    changed = IntegratedStructureCalculator().calculate(S21Config(sis_area_um2=20, sis_width_um=8))
    # Area/model-width edits must not invent a different lead length or metal.
    assert changed.overview.polygons == geometry.overview.polygons
    assert changed.overview.rects == geometry.overview.rects
    assert changed.overview.paths == geometry.overview.paths
    assert changed.overview.circles == geometry.overview.circles
    assert _parameters(_elements(changed)["SIS"]) == pytest.approx({"S": 20, "Wb (расч.)": 8})


def _outline_vertical_spans(overview, x: float) -> list[tuple[float, float]]:
    outline = next(p for p in overview.paths if p.element_id == "metal-outline").data
    spans = []
    for chain in re.findall(r"M[^M]+", outline):
        points = [Point(float(a), float(b)) for a, b in re.findall(r"([-\d.e]+),([-\d.e]+)", chain)]
        if chain.rstrip().endswith("Z"):
            points.append(points[0])
        spans += [
            (min(a.y, b.y), max(a.y, b.y))
            for a, b in zip(points, points[1:])
            if a.x == pytest.approx(x) and b.x == pytest.approx(x)
        ]
    return spans


@pytest.mark.parametrize(
    "config",
    [
        S21Config(),
        # Different widths on each side: the seam spans only the shared face.
        S21Config(mex4_width_m=9e-6, zrad4_width_m=5e-6, zrad3_width_m=7e-6, zrad1_width_m=3e-6),
        S21Config(mex4_width_m=3e-6, zrad4_width_m=8e-6, transf_1_w_start_m=4e-6),
    ],
)
def test_every_boundary_near_sis_has_exactly_one_seam_across_the_shared_face(config) -> None:
    """GitHub #11 reverses the seamless SIS/radial conductor of earlier versions."""
    geometry = IntegratedStructureCalculator().calculate(config)
    overview = geometry.overview
    elements = _elements(geometry)
    first, second = elements["SIS-line"].auxiliary_rects
    joins = {
        "13|14": (
            elements["T1"].output_port.center.x,
            elements["T1"].output_port.width,
            elements["SIS-line"].input_port.width,
        ),
        "14 L1|L2": (first.right, first.height, second.height),
        "14|16": (
            elements["Ww3"].input_port.center.x,
            elements["SIS-line"].output_port.width,
            elements["Ww3"].input_port.width,
        ),
        "16|17": (
            elements["Radial"].input_port.center.x,
            elements["Ww3"].output_port.width,
            elements["Radial"].input_port.width,
        ),
        "17|18": (
            elements["Ww1"].input_port.center.x,
            elements["Radial"].output_port.width,
            elements["Ww1"].input_port.width,
        ),
    }
    assert len({round(x, 9) for x, _, _ in joins.values()}) == len(joins)
    for name, (x, left, right) in joins.items():
        seams = [line for line in overview.seams if line.start.x == pytest.approx(x) == line.end.x]
        assert len(seams) == 1, name
        seam = seams[0]
        assert (min(seam.start.y, seam.end.y), max(seam.start.y, seam.end.y)) == pytest.approx(
            (-min(left, right) / 2, min(left, right) / 2)
        ), name
        assert seam.stroke == "#2563eb" and seam.stroke_width == pytest.approx(0.6) and not seam.arrow_end
        # No double line: the outline keeps only the exposed width step there.
        seam_lo, seam_hi = sorted((seam.start.y, seam.end.y))
        for lo, hi in _outline_vertical_spans(overview, x):
            assert hi <= seam_lo + 1e-9 or lo >= seam_hi - 1e-9, name
        assert not any(line.start.x == pytest.approx(x) == line.end.x for line in overview.lines), name
    # The SIS circle sits on the L1|L2 seam and is drawn above it and the outline.
    symbol = overview.circles[0]
    assert symbol.center.x == pytest.approx(first.right)
    svg = SvgRendererImpl().render(overview)
    assert svg.index('stroke="#2563eb"') < svg.index('id="metal-outline"') < svg.index("<circle")


def test_sis_line_dimensions_use_its_editable_fields_not_sis_model_width() -> None:
    config = S21Config(mex4_len_m=12e-6, mex4_width_m=9e-6, sis_width_um=25, sis_area_um2=1.2)
    geometry = IntegratedStructureCalculator().calculate(config)
    line = _elements(geometry)["SIS-line"]
    assert _parameters(line) == pytest.approx({"L1": 12, "W1": 9, "L2": 3, "W2": 6})
    first, second = line.auxiliary_rects
    assert (first.width, first.height) == pytest.approx((24, 19))
    assert (second.width, second.height) == pytest.approx((6, 13))
    assert line.bounds.width == pytest.approx(30)
    labels = {dim.label for dim in geometry.dimensions if dim.element_id == "SIS-line"}
    assert labels == {"L1=12", "W1эфф=9.5", "L2=3", "W2эфф=6.5"}


EXTREME_CONFIGS = [
    S21Config(),
    # GitHub #10: a vanishing line 2 and huge radial fans must not pile numbers up.
    S21Config(msl_8_len_m=1e-9, radial_r_max_m=90e-6, l_slot_m=80e-6),
    S21Config(msl_8_len_m=1e-9, radial_r_max_m=90e-6, radial_angle_deg=300),
]


def _outline_segments(geometry, element):
    """Metal edges of an element (the slot of 8 is not its metal)."""
    segments = []
    points = list(element.polygon)
    chunks = [points[i : i + 4] for i in range(0, len(points), 4)] if len(points) == 8 else [points]
    if element.element_id == "Radial":
        left, right = element.input_port, element.output_port
        chunks = [[left.top, right.top, right.bottom, left.bottom]]
        for path in geometry.paths:
            if path.element_id in {"radial-upper", "radial-lower"}:
                start, outer_left = _endpoints(path.data.split(" A")[0])
                arc_end = re.search(r" A[^ ]+ \S+ \S+ \S+ ([^,]+),([^ ]+) L([^,]+),(\S+)", path.data)
                outer_right = Point(float(arc_end.group(1)), float(arc_end.group(2)))
                end = Point(float(arc_end.group(3)), float(arc_end.group(4)))
                segments += [(start, outer_left), (outer_right, end)]
    for chunk in chunks:
        segments += list(zip(chunk, chunk[1:] + chunk[:1]))
    return segments


def _distance_to_segment(p, a, b) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)))
    return hypot(p.x - a.x - t * dx, p.y - a.y - t * dy)


def _distance_to_outline(geometry, element, p) -> float:
    if element.element_id == "SIS":
        centre = Point(element.bounds.x + element.bounds.width / 2, element.bounds.y + element.bounds.height / 2)
        return abs(hypot(p.x - centre.x, p.y - centre.y) - element.bounds.width / 2)
    best = min(_distance_to_segment(p, a, b) for a, b in _outline_segments(geometry, element))
    if element.element_id == "Radial":
        for path in geometry.paths:
            if path.element_id in {"radial-upper", "radial-lower"}:
                radius = float(re.search(r" A([^,]+),", path.data).group(1))
                start, outer_left = _endpoints(path.data.split(" A")[0])
                end = _endpoints(path.data)[1]
                middle_x = (element.input_port.center.x + element.output_port.center.x) / 2
                centre = Point(middle_x, (start.y + end.y) / 2)
                best = min(best, abs(hypot(p.x - centre.x, p.y - centre.y) - radius))
    return best


@pytest.mark.parametrize("config", EXTREME_CONFIGS)
def test_numbers_sit_next_to_their_elements_with_arrows_to_the_edge(config) -> None:
    """GitHub #10: numbers always shown, close to the element, neat arrows, no overlaps."""
    geometry = IntegratedStructureCalculator().calculate(config)
    overview = geometry.overview
    elements = _elements(overview)
    numbers = [c for c in overview.callouts if c.label.text.isdigit()]
    assert sorted(int(c.label.text) for c in numbers) == list(range(1, 19))
    assert {c.label.text: c.element_id for c in numbers} == {
        str(ELEMENT_NUMBERS[element_id]): element_id for element_id in elements
    }
    sis = [c for c in overview.callouts if c.label.text == "SIS"]
    assert len(sis) == 1 and sis[0].element_id == "SIS"
    port = next(label for label in overview.labels if label.text == "50 Ω")
    boxes = [text_box(c.label) for c in overview.callouts] + [text_box(port)]
    for i, a in enumerate(boxes):
        # Every label, including "SIS" and "50 Ω", lies inside the sheet frame.
        assert overview.bounds.x < a.x0 and a.x1 < overview.bounds.right
        assert overview.bounds.y < a.y0 and a.y1 < overview.bounds.bottom
        for b in boxes[i + 1 :]:
            assert not a.overlaps(b)
    metal = [
        chunk
        for element in overview.elements
        if element.polygon
        for chunk in (
            [list(element.polygon)[i : i + 4] for i in (0, 4)] if len(element.polygon) == 8 else [list(element.polygon)]
        )
    ]
    for callout in overview.callouts:
        arrow, box = callout.arrow, text_box(callout.label)
        assert arrow.arrow_end and arrow.stroke == "#64748b"
        # No label covers metal: neither an edge through it nor metal under it.
        for points in metal:
            assert not any(segment_hits_box(a, b, box) for a, b in zip(points, points[1:] + points[:1]))
            assert not point_in_polygon(Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2), points)
        # The tip lies on the element's own edge (the fan arc within its
        # 48-chord tolerance), the tail next to the label.
        element = elements[callout.element_id]
        assert _distance_to_outline(overview, element, arrow.end) < 0.05
        assert box.x0 - 3 <= arrow.start.x <= box.x1 + 3 and box.y0 - 3 <= arrow.start.y <= box.y1 + 3
        length = hypot(arrow.end.x - arrow.start.x, arrow.end.y - arrow.start.y)
        # Previously numbers stood 12–28 units above the top of the whole
        # drawing, up to ~90 units from a thin line; now the arrows are short.
        # A fan wider than 180° covers the line near the SIS: a little longer.
        crowded = callout.label.text == "SIS" or config.radial_angle_deg > 180
        assert 7 <= length <= (30 if crowded else 22)
    arrows = [(c.arrow.start, c.arrow.end) for c in overview.callouts]
    for i, (a, b) in enumerate(arrows):
        assert not any(segments_intersect(a, b, c, d) for c, d in arrows[i + 1 :])
    # The dimension sheet keeps the same callouts; its cards start below them.
    assert geometry.callouts == overview.callouts
    main_bottom = max(box.y1 for box in boxes)
    assert all(min(d.start.y, d.end.y) > main_bottom for d in geometry.dimensions)


def test_numbers_sis_and_port_label_are_on_the_overview() -> None:
    """GitHub #10 reverses WP-026: «Пояснения» adds only the dimension cards."""
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    callouts = {str(number) for number in range(1, 19)} | {"SIS", "50 Ω"}
    overview_texts = {label.text for label in geometry.overview.labels}
    assert callouts <= overview_texts
    assert not any(text.startswith("Размеры элементов") for text in overview_texts)
    assert any(label.text.startswith("Размеры элементов") for label in geometry.labels)
    assert geometry.overview.dimensions == []
    leaders = [line for line in geometry.overview.lines if line.arrow_end]
    assert len(leaders) == 19
    assert all(line.stroke_width == pytest.approx(0.6) for line in leaders)
    # Seams are a separate layer of plain lines; only the callouts carry arrowheads.
    assert geometry.overview.seams and not any(seam.arrow_end for seam in geometry.overview.seams)
    assert all(line.arrow_end for line in geometry.overview.lines)
    svg = SvgRendererImpl().render(geometry.overview)
    ElementTree.fromstring(svg)
    assert '<marker id="leader-arrow"' in svg
    assert svg.count('marker-end="url(#leader-arrow)"') == 19
    for number in range(1, 19):
        assert f'font-weight="bold">{number}</text>' in svg


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
    # Wide stubs keep the 19.5 µm contact of T3 clear of T4 across the gap.
    config = S21Config(w_ms_m=20e-6, **values)
    geometry = IntegratedStructureCalculator().calculate(config)
    elements = _elements(geometry)
    for i in range(1, 8):
        element = elements[f"T{i}"]
        w1, w2 = getattr(config, f"transf_{i}_w_end_m"), getattr(config, f"transf_{i}_w_start_m")
        dl = getattr(config, f"transf_{i}_dl_m")
        length = len(arange(min(w1, w2), max(w1, w2) + 0.01e-6, 2e-6)) * dl * 1e6
        assert element.number == ELEMENT_NUMBERS[f"T{i}"]
        parameters = _parameters(element)
        assert {k: parameters[k] for k in ("W1", "W2", "L")} == pytest.approx(
            {"W1": w1 * 1e6, "W2": w2 * 1e6, "L": length}
        )
        if i in (3, 4):
            continue  # corner transformers: see the dedicated tests below
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


def _dc_parts(geometry):
    elements = _elements(geometry)
    dc = elements["DC"]
    return elements, dc, dc.polygon[:4], dc.polygon[4:]


def test_dc_slot_and_feed_dimensions_follow_calculation_inputs() -> None:
    config = S21Config(w_slot_m=2e-6, l_slot_m=120e-6, l_ms_m=30e-6, mex4_len_m=20e-6, dc_gap_m=6e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    _elements_by_id, dc, left, right = _dc_parts(geometry)
    dw = config.dw_m * 1e6
    # The stub gap is its own field; Wslot − dW is the black slot thickness.
    assert right[0].x - left[1].x == pytest.approx(6 * 2)
    _h_left, gap_piece, _h_right, arm_left, arm_right = dc.auxiliary_rects
    for rect in (_h_left, gap_piece, _h_right):
        assert rect.height == pytest.approx((2 - dw) * 2)
    assert arm_left.width == arm_right.width == pytest.approx((2 - dw) * 2)
    # Wms/Lms: the two vertical open stubs, nothing else belongs to DC block.
    assert left[1].x - left[0].x == pytest.approx((config.w_ms_m * 1e6 + dw) * 2)
    assert left[2].y - left[1].y == pytest.approx(30 * 2)
    assert right[2].y - right[1].y == pytest.approx(30 * 2)
    assert dc.input_port is None and dc.output_port is None
    # Lslot is the arm length from the slot top: it changes the black arms only.
    assert arm_right.bottom - _h_left.y == pytest.approx(120 * 2)
    assert arm_left.y == arm_right.y == _h_left.y
    longer = _elements(IntegratedStructureCalculator().calculate(replace(config, l_slot_m=200e-6)))["DC"]
    assert longer.polygon == dc.polygon
    feed = _elements(geometry)["SIS-line"]
    assert feed.auxiliary_rects[0].width == pytest.approx(20 * 2)
    assert feed.bounds.height == pytest.approx((config.mex4_width_m + config.dw_m) * 1e6 * 2)
    labels = {d.label.split("=")[0] for d in geometry.dimensions if d.element_id == "DC"}
    assert labels == {"Wmsэфф", "Зазор", "Wslotэфф", "Lms", "Lso", "Lslot", "Pibase"}


@pytest.mark.parametrize(("offset_um", "gap_um"), [(2, 4), (8, 4), (16, 4), (8, 7.5)])
def test_dc_slot_arms_follow_mathcad_lso_and_pibase(offset_um, gap_um) -> None:
    config = S21Config(lso_m=offset_um * 1e-6, dc_gap_m=gap_um * 1e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    _elements_by_id, dc, left, right = _dc_parts(geometry)
    _h_left, _gap, _h_right, arm_left, arm_right = dc.auxiliary_rects
    w_ms = config.w_ms_m * 1e6 + config.dw_m * 1e6
    w_slot = config.w_slot_m * 1e6 - config.dw_m * 1e6
    pibase = 2 * w_ms + 2 * offset_um + gap_um
    # Pibase = 2·Wms + 2·Lso + gap is the distance between the inner arm edges.
    assert arm_right.x - arm_left.right == pytest.approx(pibase * 2)
    assert _parameters(dc)["Pibase (расч.)"] == pytest.approx(pibase)
    # Lso: from the inner edge of each arm to the outer edge of its stub.
    assert arm_right.x - right[1].x == pytest.approx(offset_um * 2)
    assert left[0].x - arm_left.right == pytest.approx(offset_um * 2)
    assert all(rect.width == pytest.approx(w_slot * 2) for rect in (arm_left, arm_right))
    assert any(d.element_id == "DC" and d.label == f"Lso={offset_um:g}" for d in geometry.dimensions)
    # Slot pieces are a bottom-electrode underlay, outside the metal outline.
    assert all(p.fill != SLOT_FILL for p in geometry.overview.polygons)
    assert not any(p.element_id.startswith("dc-slot-") for p in geometry.overview.paths)
    assert len([p for p in geometry.overview.underlay_paths if p.element_id.startswith("dc-slot-")]) == 5


def test_dc_slot_is_rendered_beneath_the_metal() -> None:
    svg = SvgRendererImpl().render(IntegratedStructureCalculator().calculate(S21Config()))
    first_slot = svg.index('id="dc-slot-0"')
    assert first_slot < svg.index("<polygon")
    assert first_slot < svg.index('id="metal-outline"')


@pytest.mark.parametrize(("lso_um", "w_slot_um"), [(8, 4), (0.1, 4), (8, 30)])
def test_dc_slot_arms_stay_outside_the_stubs(lso_um, w_slot_um) -> None:
    config = S21Config(lso_m=lso_um * 1e-6, w_slot_m=w_slot_um * 1e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    _elements_by_id, dc, left, right = _dc_parts(geometry)
    arm_left, arm_right = dc.auxiliary_rects[3:]
    assert arm_left.right < left[0].x
    assert arm_right.x > right[1].x
    assert not any("Плечо щели под шлейфом" in label.text for label in geometry.labels)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"lso_m": 0.1e-6},
        {"w_slot_m": 30e-6},
        {"l_slot_m": 40e-6, "lso_m": 4e-6, "w_ms_m": 12e-6, "l_ms_m": 24e-6},
        {"l_slot_m": 12e-6, "lso_m": 4e-6, "w_ms_m": 14e-6, "l_ms_m": 20e-6},
        {"l_slot_m": 200e-6, "dc_gap_m": 20e-6},
    ],
)
def test_dc_dimension_view_stays_inside_its_card(changes) -> None:
    geometry = IntegratedStructureCalculator().calculate(replace(S21Config(), **changes))
    dims = {d.label.split("=")[0]: d for d in geometry.dimensions if d.element_id == "DC"}
    footnote = next(label for label in geometry.labels if label.text.startswith("Чёрное — щель"))
    # Every DC label ends above the footnotes, Pibase below the gap row.
    assert all(d.label_pos.y < footnote.position.y - 8 for d in dims.values())
    assert dims["Pibase"].start.y > dims["Зазор"].label_pos.y
    assert dims["Pibase"].start.y > dims["Wslotэфф"].label_pos.y
    # Lslot is dimensioned outside the left arm, clear of the right-side Lso label.
    assert dims["Lslot"].start.x < dims["Pibase"].start.x
    assert dims["Lso"].label_pos.x > dims["Lso"].start.x


def _corner_config(**changes):
    # L = 12 µm for both corners: long enough for a horizontal arm.
    values = {
        "transf_4_w_end_m": 6e-6,
        "transf_4_w_start_m": 8e-6,
        "transf_4_dwdl_um": 1,
        "transf_4_dl_m": 4e-6,
        "transf_3_w_end_m": 8e-6,
        "transf_3_w_start_m": 6e-6,
        "transf_3_dwdl_um": 1,
        "transf_3_dl_m": 4e-6,
    }
    values.update(changes)
    return S21Config(**values)


def test_corner_transformers_bend_from_the_lines_onto_the_stubs() -> None:
    config = _corner_config()
    geometry = IntegratedStructureCalculator().calculate(config)
    elements, dc, left, right = _dc_parts(geometry)
    t4, t3 = elements["T4"], elements["T3"]
    dw = config.dw_m * 1e6
    # Ends meet the neighbouring lines 6 and 10 (old trapezoids are gone).
    assert t4.input_port.center == elements["MSL6"].output_port.center
    assert t4.input_port.width == pytest.approx((6 + dw) * 2)
    assert t3.output_port.center == elements["MSL5"].input_port.center
    assert t3.output_port.width == pytest.approx((6 + dw) * 2)
    assert t4.output_port is None and t3.input_port is None
    # Stubs start 1 µm below the lowest adjacent line edge (the HFSS foot).
    contact_y = left[0].y
    assert contact_y == pytest.approx(((6 + dw) / 2 + 1) * 2)
    assert right[0].y == pytest.approx(contact_y)
    half_foot = 8 + dw  # W2 = 8 µm with dW, in SVG units / 2
    for corner, stub in ((t4, left), (t3, right)):
        # The foot of width W2 is centred on its stub and ends on its top.
        middle = (stub[0].x + stub[1].x) / 2
        assert corner.auxiliary_lines[-1].end == Point(pytest.approx(middle), pytest.approx(contact_y))
        assert max(p.y for p in corner.polygon) == pytest.approx(contact_y)
        for x in (middle - half_foot, middle + half_foot):
            assert any(p.x == pytest.approx(x) and p.y == pytest.approx(contact_y) for p in corner.polygon)
    # L = L1 + L2 + L3: L2 = ½·√(W1²+W2²) to the foot axis, L3 down the foot.
    for corner in (t4, t3):
        values = _parameters(corner)
        assert values["L"] == pytest.approx(12)
        assert values["L1"] + values["L2"] + values["L3"] == pytest.approx(12, abs=1e-3)
        assert values["L2"] == pytest.approx(hypot(6 + dw, 8 + dw) / 2, abs=1e-4)
        assert values["L3"] == pytest.approx(1)
        assert values["L1"] > 0
        segments = corner.auxiliary_lines
        assert len(segments) == 3
        drawn = [hypot(s.end.x - s.start.x, s.end.y - s.start.y) / LENGTH_SCALE for s in segments]
        assert drawn == pytest.approx([values["L1"], values["L2"], values["L3"]], abs=1e-3)
        assert segments[0].start.y == segments[0].end.y == 0
        assert segments[2].start.x == pytest.approx(segments[2].end.x)
    assert not any("Lmin" in label.text for label in geometry.overview.labels)


@pytest.mark.parametrize("contact_um,stub_um", [(8, 8), (6, 9), (11, 9)])
def test_corner_contact_and_stub_share_a_seam_with_a_visible_step(contact_um, stub_um) -> None:
    config = _corner_config(transf_4_w_start_m=contact_um * 1e-6, w_ms_m=stub_um * 1e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    elements, dc, left, _right = _dc_parts(geometry)
    dw = config.dw_m * 1e6
    contact_y = left[0].y
    middle = (left[0].x + left[1].x) / 2
    seams = [
        line
        for line in geometry.overview.seams
        if line.start.y == line.end.y == pytest.approx(contact_y)
        and left[0].x - 30 <= min(line.start.x, line.end.x) <= left[1].x + 1e-9
    ]
    # One thin separator (the red line of the sketch) over the shared width.
    assert len(seams) == 1
    seam = seams[0]
    assert abs(seam.end.x - seam.start.x) == pytest.approx((min(contact_um, stub_um) + dw) * 2)
    assert (seam.start.x + seam.end.x) / 2 == pytest.approx(middle)
    outline = next(p for p in geometry.overview.paths if p.element_id == "metal-outline").data
    points = [Point(float(x), float(y)) for x, y in re.findall(r"([-\d.e]+),([-\d.e]+)", outline)]
    # Different widths leave a step of the wider face exposed on both sides.
    for sign in (-1, 1):
        step = {round(middle + sign * (contact_um + dw), 6), round(middle + sign * (stub_um + dw), 6)}
        exposed = any(
            a.y == pytest.approx(contact_y) == b.y and {round(a.x, 6), round(b.x, 6)} == step
            for a, b in zip(points, points[1:])
        )
        assert exposed is (contact_um != stub_um)


def test_short_corner_length_is_drawn_at_its_minimum_with_a_warning() -> None:
    config = S21Config()  # T4: L = 6 µm, W1 = 6 µm, W2 = 10 µm
    geometry = IntegratedStructureCalculator().calculate(config)
    elements, _dc, left, _right = _dc_parts(geometry)
    t4 = elements["T4"]
    values = _parameters(t4)
    dw = config.dw_m * 1e6
    minimum = hypot(6 + dw, 10 + dw) / 2 + 1
    assert values["L1"] == 0
    assert values["L1"] + values["L2"] + values["L3"] == pytest.approx(minimum, abs=1e-3)
    # No horizontal part: the foot starts the drop L3 (1 µm) after the line
    # end, so the line-end face keeps the line width.
    assert t4.auxiliary_lines[-1].end.x == pytest.approx(t4.input_port.center.x + 1 * 2 + (10 + dw))
    # No "7/9: L < Lmin" lines under the DC block in either mode; only the
    # corner card next to the element warns.
    assert not any("Lmin" in label.text for label in geometry.labels)
    warnings = [label.text for label in geometry.labels if "меньше минимума" in label.text]
    assert warnings == [f"L=6 меньше минимума {minimum:.3g}: ступня у торца, снизу скос"] * 2
    assert not any("меньше минимума" in label.text for label in geometry.overview.labels)


@pytest.mark.parametrize(
    "line_um,w1_um,length_um",
    [(7, 8, 4.5), (4, 6, 6), (4, 40, 12), (4, 6, 12)],
)
def test_corner_line_end_face_is_centred_on_its_line(line_um, w1_um, length_um) -> None:
    """GitHub #10: the face of 7 (and 9) protrudes equally above and below line 6 (10)."""
    from smcapp.domain.transformers import derive_transformer_steps

    steps = derive_transformer_steps(w1_um * 1e-6, 10e-6, length_um * 1e-6, max_dl_um=3.0)
    config = _corner_config(
        msl_6_width_m=line_um * 1e-6,
        msl_5_width_m=line_um * 1e-6,
        transf_4_w_end_m=w1_um * 1e-6,
        transf_4_w_start_m=10e-6,
        transf_4_dwdl_um=steps.n_um,
        transf_4_dl_m=steps.dl_m,
        transf_3_w_end_m=10e-6,
        transf_3_w_start_m=w1_um * 1e-6,
        transf_3_dwdl_um=steps.n_um,
        transf_3_dl_m=steps.dl_m,
    )
    elements = _elements(IntegratedStructureCalculator().calculate(config))
    dw = config.dw_m * 1e6
    for corner, line in (("T4", "MSL6"), ("T3", "MSL5")):
        port = elements[corner].input_port or elements[corner].output_port
        face = sorted(p.y for p in elements[corner].polygon if p.x == pytest.approx(port.center.x))
        # Exactly two vertices on the face: W1 tall, centred on the line axis.
        assert face == pytest.approx([-(w1_um + dw), w1_um + dw])
        line_bounds = elements[line].bounds
        assert -face[0] - (-line_bounds.y) == pytest.approx(face[1] - line_bounds.bottom)
        # Leaving the face's top vertex: a horizontal part of length L1 or,
        # when L1 = 0, the chamfer itself (a sharp top corner).
        polygon = elements[corner].polygon
        top = next(i for i, p in enumerate(polygon) if p.y == pytest.approx(face[0]))
        away = next(p for p in (polygon[top - 1], polygon[(top + 1) % len(polygon)]) if abs(p.x - port.center.x) > 1e-9)
        l1 = _parameters(elements[corner])["L1"]
        assert (abs(away.y - face[0]) < 1e-9) is (l1 > 0)
        if l1 > 0:
            assert abs(away.x - port.center.x) == pytest.approx(l1 * 2, abs=1e-3)


def test_corner_contacts_must_not_close_the_stub_gap() -> None:
    with pytest.raises(ValueError, match="смыкаются"):
        IntegratedStructureCalculator().calculate(_corner_config(transf_4_w_start_m=14e-6, transf_3_w_end_m=14e-6))


def test_wider_neighbouring_line_never_touches_a_stub() -> None:
    config = _corner_config(msl_5_width_m=14e-6)
    elements, _dc, left, right = _dc_parts(IntegratedStructureCalculator().calculate(config))
    assert elements["MSL5"].bounds.bottom + 1 * 2 == pytest.approx(right[0].y)
    assert elements["MSL6"].bounds.bottom < left[0].y


def test_radial_lines_have_exact_lengths_widths_and_connected_ports() -> None:
    config = S21Config(zrad1_len_m=100e-6, zrad1_width_m=20e-6, zrad3_len_m=1e-6, zrad4_len_m=80e-6)
    geometry = IntegratedStructureCalculator().calculate(config)
    elements = _elements(geometry)
    parts = {4: elements["SIS-line"].auxiliary_rects[1], 3: elements["Ww3"].bounds, 1: elements["Ww1"].bounds}
    for index, bounds in parts.items():
        assert bounds.width == pytest.approx(getattr(config, f"zrad{index}_len_m") * 1e6 * 2)
        assert bounds.height == pytest.approx((getattr(config, f"zrad{index}_width_m") + config.dw_m) * 1e6 * 2)
    # Straight joins chain along one axis; the DC block turns down between 7 and 9.
    chain = [e for e in geometry.elements if e.input_port is not None or e.output_port is not None]
    pairs = [(a, b) for a, b in zip(chain, chain[1:]) if a.output_port is not None and b.input_port is not None]
    assert len(pairs) == len(chain) - 2
    for a, b in pairs:
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
    seams = [line for line in geometry.overview.seams if line.start.x == joint_x == line.end.x]
    assert len(seams) == 1
    assert config == S21Config()


def test_dimensioned_views_use_one_zoom_for_both_axes() -> None:
    geometry = IntegratedStructureCalculator().calculate(_corner_config())
    elements = _elements(geometry)
    for element in elements.values():
        if element.input_port is None or element.element_id in {"DC", "Radial", "T4", "SIS-line"}:
            continue
        dims = [d for d in geometry.dimensions if d.element_id == element.element_id]
        length = next(d for d in dims if d.label.split("=")[0] in ("L", "L1", "L3"))
        width = next(d for d in dims if d.label.split("=")[0] in ("Wэфф", "W1эфф", "W3эфф"))
        x_zoom = hypot(length.end.x - length.start.x, length.end.y - length.start.y) / element.bounds.width
        y_zoom = hypot(width.end.x - width.start.x, width.end.y - width.start.y) / element.input_port.width
        assert x_zoom == pytest.approx(y_zoom)
    # Lines 16 and 18 are dimensioned with the names of their fields.
    for name, expected in (("Ww3", {"L3", "W3эфф"}), ("Ww1", {"L1", "W1эфф"})):
        assert {d.label.split("=")[0] for d in geometry.dimensions if d.element_id == name} == expected
    # 14 · Линия SIS: both parts and both widths share the card zoom.
    line = elements["SIS-line"]
    dims = {d.label.split("=")[0]: d for d in geometry.dimensions if d.element_id == "SIS-line"}
    first, second = line.auxiliary_rects
    zooms = [
        abs(dims["L1"].end.x - dims["L1"].start.x) / first.width,
        abs(dims["L2"].end.x - dims["L2"].start.x) / second.width,
        abs(dims["W1эфф"].end.y - dims["W1эфф"].start.y) / first.height,
        abs(dims["W2эфф"].end.y - dims["W2эфф"].start.y) / second.height,
    ]
    assert zooms == pytest.approx([zooms[0]] * 4)
    # Corner cards: the line-end and contact widths use the same zoom.
    for name, line_label, contact_label in (("T4", "W1эфф", "W2эфф"), ("T3", "W2эфф", "W1эфф")):
        corner = elements[name]
        dims = {d.label.split("=")[0]: d for d in geometry.dimensions if d.element_id == name}
        port = corner.input_port or corner.output_port
        contact_width = (_parameters(corner)[contact_label[:2]] + 0.5) * WIDTH_SCALE
        line_zoom = abs(dims[line_label].end.y - dims[line_label].start.y) / port.width
        contact_zoom = abs(dims[contact_label].end.x - dims[contact_label].start.x) / contact_width
        assert line_zoom == pytest.approx(contact_zoom)
        footer = next(
            label for label in geometry.labels if label.text.startswith("Масштаб ×") and "осевая" in label.text
        )
        assert all(d.label_pos.y < footer.position.y - 8 for d in dims.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("msl_8_len_m", 0),
        ("w_slot_m", 0.1e-6),
        ("radial_r_max_m", 0),
        ("radial_angle_deg", 360),
        ("radial_angle_deg", float("nan")),
        ("l_slot_m", 8e-6),
    ],
)
def test_invalid_geometry_is_reported_instead_of_producing_broken_svg(field, value) -> None:
    with pytest.raises(ValueError):
        IntegratedStructureCalculator().calculate(replace(S21Config(), **{field: value}))


@pytest.mark.parametrize("details", [False, True])
def test_dark_scheme_recolours_every_colour_of_the_sheet(details) -> None:
    geometry = IntegratedStructureCalculator().calculate(S21Config())
    if not details:
        geometry = geometry.overview
    light_svg = SvgRendererImpl().render(geometry)
    dark_svg = SvgRendererImpl().render(geometry, DARK_SVG_SCHEME)
    ElementTree.fromstring(dark_svg)

    def colours(svg: str) -> set[str]:
        return {value.lower() for value in re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{3,6})"', svg)}

    light = colours(light_svg)
    # Every colour the light sheet uses has a dark counterpart, and none survives.
    assert light <= set(DARK_SVG_SCHEME.colors)
    assert colours(dark_svg) <= set(DARK_SVG_SCHEME.colors.values())
    assert 'fill="#1f2329"' in dark_svg  # dark sheet background
    # The light rendering stays unchanged by default.
    assert SvgRendererImpl().render(geometry, SvgColorScheme()) == light_svg
