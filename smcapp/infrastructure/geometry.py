"""Inspectable protocol: config -> sections -> ports -> contours -> dimensions.

SI lengths are converted to µm once. Both SVG axes have the same scale.
Different endpoint widths form an explicit step at a shared join plane;
they never change a calculation input or introduce a longitudinal gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import cos, hypot, isfinite, radians, sin

from smcapp.api.dc_block import base_distance_m
from smcapp.domain.models import (
    Callout,
    CircleShape,
    DimensionLine,
    ElementParameter,
    LineShape,
    PathShape,
    Point,
    PolygonShape,
    Rect,
    RectShape,
    SchematicElement,
    SectionPort,
    StructureGeometry,
    TextLabel,
    bounds_from_points,
)
from smcapp.domain.ports import StructureCalculator
from smcapp.domain.s21_models import S21Config
from smcapp.domain.transformers import ELEMENT_NUMBERS, SCHEMATIC_SECTIONS, transformer_length_m
from smcapp.infrastructure.callouts import CalloutPlacer

LENGTH_SCALE = WIDTH_SCALE = 2.0
CONDUCTOR_FILL = "#e8f1f5"
TRANSFORMER_FILL = "#dbeafe"
RADIAL_FILL = "#e8f1f5"
DC_FILL = "#d7edf5"
# Near-black, but its own colour so a dark sheet can soften the slot separately.
SLOT_FILL = "#1a1a1a"
CENTRE_LINE_COLOR = "#f59e0b"
WARNING_COLOR = "#b91c1c"
# Element boundaries (GitHub #11): blue, so they read as joints and never as
# the near-black metal outline (0.8) or the orange hover highlight.
SEAM_COLOR = "#2563eb"
SEAM_WIDTH = 0.6
# As in the HFSS model: stub tops 1 µm below the lowest adjacent line edge
# (the foot of a corner transformer), the slot top 1 µm below the stub tops.
FOOT_UM = 1.0
SLOT_OFFSET_UM = 1.0
# Transformers 7 and 9 bend from the line axis down onto the DC-block stubs.
CORNER_TRANSFORMERS = ("T4", "T3")
# The FFO signal enters at the left face of element 1; it never moves, so the
# viewer keeps this point in place while parameters change (GitHub #10).
SIGNAL_INPUT = Point(28.0, 0.0)


def _um(value_m: float) -> float:
    return value_m * 1e6


def _path(points: list[Point], close: bool = False) -> str:
    return "M" + " L".join(f"{p.x:.12g},{p.y:.12g}" for p in points) + (" Z" if close else "")


def _dedupe(points: list[Point]) -> list[Point]:
    """Drop repeated vertices (also across the closing edge) of a polygon."""
    result: list[Point] = []
    for point in points:
        if not result or abs(point.x - result[-1].x) > 1e-9 or abs(point.y - result[-1].y) > 1e-9:
            result.append(point)
    while len(result) > 1 and abs(result[0].x - result[-1].x) < 1e-9 and abs(result[0].y - result[-1].y) < 1e-9:
        result.pop()
    return result


@dataclass(frozen=True)
class _CornerLayout:
    """Centre line of a corner transformer: ``L = L1 + L2 + L3``.

    L1 runs along the line axis from the line end to the outer edge of the
    foot, L2 is the diagonal from there to the foot axis at the bottom edge of
    the horizontal part, L3 goes down the foot to the stub.  L2 and L3 follow
    from W1, W2 and the stub plane; the rest of L is the horizontal L1.
    """

    l1: float
    l2: float
    l3: float
    minimum: float

    @classmethod
    def solve(cls, line_width: float, contact_width: float, depth: float, length: float) -> _CornerLayout:
        l2 = hypot(line_width, contact_width) / 2
        l3 = depth - line_width / 2
        minimum = l2 + l3
        return cls(max(0.0, length - minimum), l2, l3, minimum)

    @property
    def foot(self) -> float:
        """Distance from the line end to the outer edge of the foot.

        The line-end face is always the full line width, centred on the axis.
        A short L1 (below the drop L3) would make that face run down to the
        stub, so the foot then starts L3 away and a lower chamfer joins it.
        """
        return max(self.l1, self.l3)


def _corner_points(
    joint_x: float,
    direction: int,
    y: float,
    line_width: float,
    contact_width: float,
    depth: float,
    layout: _CornerLayout,
) -> tuple[list[Point], list[Point]]:
    """Contour and centre line; *direction* points from the line end to the stub.

    The horizontal part has the line-end width W1; the foot of width W2 hangs
    from its far end down to the stub.  The outer chamfer runs from the top
    edge above the foot's outer edge to the foot's inner edge at the bottom of
    the horizontal part, parallel to the L2 diagonal of the centre line.
    """

    def at(u: float, v: float) -> Point:
        return Point(joint_x + direction * u, y + v)

    outer, inner = layout.foot, layout.foot + contact_width
    contour = [
        at(0, -line_width / 2),
        at(layout.l1, -line_width / 2),
        at(inner, line_width / 2),
        at(inner, depth),
        at(outer, depth),
        at(layout.l1, line_width / 2),
        at(0, line_width / 2),
    ]
    middle = outer + contact_width / 2
    centre = [at(0, 0), at(layout.l1, 0), at(middle, line_width / 2), at(middle, depth)]
    return _dedupe(contour), centre


@dataclass
class _Canvas:
    polygons: list[PolygonShape] = field(default_factory=list)
    paths: list[PathShape] = field(default_factory=list)
    underlay_paths: list[PathShape] = field(default_factory=list)
    rects: list[RectShape] = field(default_factory=list)
    circles: list[CircleShape] = field(default_factory=list)
    lines: list[LineShape] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    # Element numbers and "SIS" with their arrows (always on the drawing).
    callouts: list[Callout] = field(default_factory=list)
    # Metal without its own polygon on an element (radial fans, the 50 Ω
    # port) that number labels must keep clear of: (owner, contour).
    shapes: list[tuple[str, list[Point]]] = field(default_factory=list)
    dimensions: list[DimensionLine] = field(default_factory=list)
    elements: list[SchematicElement] = field(default_factory=list)
    bounds_points: list[Point] = field(default_factory=list)
    excluded_edges: list[tuple[Point, Point]] = field(default_factory=list)
    seams: list[LineShape] = field(default_factory=list)
    # Contours by element for the viewer's hover highlight (GitHub #10).
    hit_areas: list[tuple[str, tuple[Point, ...]]] = field(default_factory=list)

    def include(self, rect: Rect) -> None:
        self.bounds_points.extend((Point(rect.x, rect.y), Point(rect.right, rect.bottom)))

    def polygon(self, points: list[Point], fill: str) -> None:
        self.polygons.append(PolygonShape(points, fill=fill, stroke="none"))
        self.bounds_points.extend(points)

    def rectangle(self, rect: Rect, fill: str) -> None:
        self.rects.append(RectShape(rect, fill=fill, stroke="none"))
        self.include(rect)

    def snapshot(self) -> StructureGeometry:
        bounds = bounds_from_points(self.bounds_points)
        return StructureGeometry(
            polygons=list(self.polygons),
            paths=list(self.paths),
            rects=list(self.rects),
            circles=list(self.circles),
            lines=list(self.lines),
            labels=list(self.labels),
            dimensions=list(self.dimensions),
            elements=list(self.elements),
            underlay_paths=list(self.underlay_paths),
            callouts=list(self.callouts),
            hit_areas=list(self.hit_areas),
            seams=list(self.seams),
            bounds=Rect(bounds.x - 20, bounds.y - 20, bounds.width + 40, bounds.height + 40),
        )


@dataclass
class IntegratedStructureCalculator(StructureCalculator):
    """Place each section at its predecessor's output X, on one centre line."""

    def calculate(self, config: S21Config) -> StructureGeometry:
        for name in (
            "w_slot_m",
            "l_slot_m",
            "w_ms_m",
            "l_ms_m",
            "lso_m",
            "dc_gap_m",
            "radial_r_min_m",
            "radial_r_max_m",
        ):
            value = getattr(config, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name}: размер должен быть положительным конечным числом")
        if not isfinite(config.dw_m) or config.dw_m < 0 or config.w_slot_m <= config.dw_m:
            raise ValueError("Щель Wslot − dW должна быть положительной; dW — неотрицательным")
        if config.l_slot_m <= config.lso_m:
            raise ValueError("Lslot должна быть больше Lso: в расчёте Lso — нижний предел интеграла по плечу щели")
        if not isfinite(config.radial_angle_deg) or not 0 < config.radial_angle_deg < 360:
            raise ValueError("Угол радиального шлейфа должен лежать между 0 и 360°")
        canvas = _Canvas()
        dw, y, x = _um(config.dw_m), SIGNAL_INPUT.y, SIGNAL_INPUT.x
        for matrix, sections in SCHEMATIC_SECTIONS.items():
            for number, name in sections:
                if name in CORNER_TRANSFORMERS:
                    continue
                if name.startswith("T"):
                    i = int(name[1:])
                    w1 = _um(getattr(config, f"transf_{i}_w_end_m"))
                    w2 = _um(getattr(config, f"transf_{i}_w_start_m"))
                    length = self._transformer_physical_length_um(
                        getattr(config, f"transf_{i}_w_start_m"),
                        getattr(config, f"transf_{i}_w_end_m"),
                        getattr(config, f"transf_{i}_dwdl_um"),
                        getattr(config, f"transf_{i}_dl_m"),
                    )
                    x = self._strip(canvas, name, f"{number} · Трансформатор", x, y, length, w1, w2, dw, number)
                else:
                    i = int(name[3:])
                    w = _um(getattr(config, f"msl_{i}_width_m"))
                    x = self._strip(
                        canvas,
                        name,
                        f"{number} · Линия",
                        x,
                        y,
                        _um(getattr(config, f"msl_{i}_len_m")),
                        w,
                        w,
                        dw,
                        number,
                    )
            if matrix == "Mex02":
                x = self._dc_block(canvas, config, x, y, dw)
        x = self._radial_and_sis(canvas, config, x, y, dw)
        canvas.elements = [
            replace(
                element,
                number=ELEMENT_NUMBERS[element.element_id],
                title=f"{ELEMENT_NUMBERS[element.element_id]} · {element.title}"
                if element.number is None
                else element.title,
            )
            for element in canvas.elements
        ]
        self._metal_outline(canvas)
        # Numbers with arrows, "SIS" and "50 Ω" are always on the drawing; the
        # «Пояснения» checkbox adds only the dimensioned views below it.
        port_label = TextLabel(Point(x - 34, -24), "50 Ω", 11, anchor="middle")
        canvas.labels.append(port_label)
        # Cap height of the 11 px "50 Ω" label above its baseline.
        canvas.bounds_points.append(Point(x - 34, -24 - 11))
        self._number_labels(canvas, port_label)
        overview = canvas.snapshot()
        self._dimensioned_views(canvas, dw)
        return replace(canvas.snapshot(), overview=overview)

    def _strip(
        self,
        canvas: _Canvas,
        name: str,
        title: str,
        x: float,
        y: float,
        length_um: float,
        w1_um: float,
        w2_um: float,
        dw_um: float,
        number: int | None = None,
    ) -> float:
        if not all(isfinite(v) and v > 0 for v in (length_um, w1_um, w2_um)):
            raise ValueError(f"{title}: W и L должны быть положительными конечными числами")
        start = SectionPort(Point(x, y), (w1_um + dw_um) * WIDTH_SCALE)
        end = SectionPort(Point(x + length_um * LENGTH_SCALE, y), (w2_um + dw_um) * WIDTH_SCALE)
        points = [start.top, end.top, end.bottom, start.bottom]
        bounds = bounds_from_points(points)
        if name.startswith("T"):
            canvas.polygon(points, TRANSFORMER_FILL)
            params = (ElementParameter("W1", w1_um), ElementParameter("W2", w2_um), ElementParameter("L", length_um))
        else:
            canvas.rectangle(bounds, CONDUCTOR_FILL)
            params = (ElementParameter("W", w1_um), ElementParameter("L", length_um))
        canvas.elements.append(SchematicElement(name, title, bounds, params, start, end, number, tuple(points)))
        return end.center.x

    def _dc_block(self, canvas: _Canvas, config: S21Config, x: float, y: float, dw: float) -> float:
        """Corner transformer 7, DC block 8 (two stubs over a Π-slot), corner 9.

        Each corner transformer runs along its line and ends in a foot of width
        W2 centred on its stub, so a foot narrower or wider than ``Wms`` leaves
        a step on both sides.  Sizes follow the owner's sketch and the HFSS
        model (Tr_DCB, MSL_DCB, Slot_1…3):

        * ``Wslot − dW`` — thickness of the black slot in the bottom electrode;
        * ``Wms``/``Lms`` — width/length of each open-ended microstrip stub;
        * ``gap`` — metal gap between the stubs, the 4 µm of ``Pibase``;
        * ``Lso`` — from the inner edge of a slot arm to the outer stub edge;
        * ``Ls`` — arm length from the top edge of the slot;
        * ``Pibase = 2·Wms + 2·Lso + gap`` — between the inner arm edges.
        """
        widths = {
            name: (
                (_um(getattr(config, f"transf_{name[1:]}_w_end_m")) + dw) * WIDTH_SCALE,
                (_um(getattr(config, f"transf_{name[1:]}_w_start_m")) + dw) * WIDTH_SCALE,
            )
            for name in CORNER_TRANSFORMERS
        }
        (t4_line, t4_contact), (t3_contact, t3_line) = widths["T4"], widths["T3"]
        lengths = {
            name: self._transformer_physical_length_um(
                getattr(config, f"transf_{name[1:]}_w_start_m"),
                getattr(config, f"transf_{name[1:]}_w_end_m"),
                getattr(config, f"transf_{name[1:]}_dwdl_um"),
                getattr(config, f"transf_{name[1:]}_dl_m"),
            )
            * LENGTH_SCALE
            for name in CORNER_TRANSFORMERS
        }
        stub_w = (_um(config.w_ms_m) + dw) * WIDTH_SCALE
        stub_l = _um(config.l_ms_m) * LENGTH_SCALE
        gap = _um(config.dc_gap_m) * WIDTH_SCALE
        slot_w = (_um(config.w_slot_m) - dw) * WIDTH_SCALE
        if (t4_contact + t3_contact) / 2 >= stub_w + gap:
            raise ValueError(
                "Трансформаторы 7 и 9 смыкаются над зазором DC block: "
                "(W2(7) + W1(9))/2 с dW должно быть меньше Wms + dW + зазор"
            )
        # Both stubs start on one plane below every adjacent line (6, 7, 9, 10),
        # so a wider neighbouring line never touches the side of a stub.
        neighbours = [(_um(config.msl_6_width_m) + dw) * WIDTH_SCALE, (_um(config.msl_5_width_m) + dw) * WIDTH_SCALE]
        depth = max(t4_line, t3_line, *neighbours) / 2 + FOOT_UM * WIDTH_SCALE
        contact_y = y + depth
        left_layout = _CornerLayout.solve(t4_line, t4_contact, depth, lengths["T4"])
        right_layout = _CornerLayout.solve(t3_line, t3_contact, depth, lengths["T3"])
        # Feet are centred on the stubs.
        outer_l = x + left_layout.foot + t4_contact / 2 - stub_w / 2
        inner_l = outer_l + stub_w
        inner_r = inner_l + gap
        outer_r = inner_r + stub_w
        right_joint = outer_r - stub_w / 2 + t3_contact / 2 + right_layout.foot

        corners = {}
        for name, joint, direction, line_w, contact_w, layout, number in (
            ("T4", x, 1, t4_line, t4_contact, left_layout, 7),
            ("T3", right_joint, -1, t3_line, t3_contact, right_layout, 9),
        ):
            contour, centre = _corner_points(joint, direction, y, line_w, contact_w, depth, layout)
            canvas.polygon(contour, TRANSFORMER_FILL)
            corners[name] = (contour, centre, line_w, contact_w, layout, number, joint)

        left = [
            Point(outer_l, contact_y),
            Point(inner_l, contact_y),
            Point(inner_l, contact_y + stub_l),
            Point(outer_l, contact_y + stub_l),
        ]
        right = [
            Point(inner_r, contact_y),
            Point(outer_r, contact_y),
            Point(outer_r, contact_y + stub_l),
            Point(inner_r, contact_y + stub_l),
        ]
        canvas.polygon(left, DC_FILL)
        canvas.polygon(right, DC_FILL)

        # Π-shaped slot in the ground plane, thickness Ws (= Wslot − dW); the
        # inner arm edges are Lso outside the stubs, Pibase apart.
        pibase = _um(base_distance_m(config.w_ms_m + config.dw_m, config.lso_m, config.dc_gap_m)) * WIDTH_SCALE
        center_x = (inner_l + inner_r) / 2
        arm_l, arm_r = center_x - pibase / 2 - slot_w, center_x + pibase / 2
        slot_top = contact_y + min(SLOT_OFFSET_UM * LENGTH_SCALE, max(stub_l - slot_w, 0.0))
        arm_end = slot_top + _um(config.l_slot_m) * LENGTH_SCALE
        slot = (
            Rect(arm_l, slot_top, outer_l - arm_l, slot_w),
            Rect(inner_l, slot_top, gap, slot_w),
            Rect(outer_r, slot_top, arm_r + slot_w - outer_r, slot_w),
            Rect(arm_l, slot_top, slot_w, arm_end - slot_top),
            Rect(arm_r, slot_top, slot_w, arm_end - slot_top),
        )
        # The slot is in the bottom electrode: an underlay beneath the top-film
        # metal, outside the metal outline.
        for index, rect in enumerate(slot):
            corners_of_rect = [
                Point(rect.x, rect.y),
                Point(rect.right, rect.y),
                Point(rect.right, rect.bottom),
                Point(rect.x, rect.bottom),
            ]
            canvas.underlay_paths.append(
                PathShape(_path(corners_of_rect, close=True), rect, f"dc-slot-{index}", fill=SLOT_FILL, stroke="none")
            )
            canvas.bounds_points.extend(corners_of_rect)

        for name in CORNER_TRANSFORMERS:
            contour, centre, line_w, contact_w, layout, number, joint = corners[name]
            l1, l2, l3 = (piece / LENGTH_SCALE for piece in (layout.l1, layout.l2, layout.l3))
            length = lengths[name] / LENGTH_SCALE
            line_label, contact_label = ("W1", "W2") if name == "T4" else ("W2", "W1")
            raw = {
                "W1": _um(getattr(config, f"transf_{name[1:]}_w_end_m")),
                "W2": _um(getattr(config, f"transf_{name[1:]}_w_start_m")),
            }
            params = (
                ElementParameter("W1", raw["W1"]),
                ElementParameter("W2", raw["W2"]),
                ElementParameter("L", length),
                ElementParameter("L1", round(l1, 4)),
                ElementParameter("L2", round(l2, 4)),
                ElementParameter("L3", round(l3, 4)),
            )
            port = SectionPort(Point(joint, y), line_w)
            canvas.elements.append(
                SchematicElement(
                    name,
                    "Трансформатор · угловой",
                    bounds_from_points(contour),
                    params,
                    input_port=port if name == "T4" else None,
                    output_port=port if name == "T3" else None,
                    polygon=tuple(contour),
                    auxiliary_lines=tuple(
                        LineShape(a, b, stroke=CENTRE_LINE_COLOR, stroke_width=1.0) for a, b in zip(centre, centre[1:])
                    ),
                )
            )
            if name == "T4":
                params = tuple(
                    ElementParameter(label, _um(getattr(config, field_name)))
                    for label, field_name in (
                        ("Wslot", "w_slot_m"),
                        ("Lslot", "l_slot_m"),
                        ("Lso", "lso_m"),
                        ("Wms", "w_ms_m"),
                        ("Lms", "l_ms_m"),
                        ("Зазор", "dc_gap_m"),
                    )
                )
                params += (ElementParameter("Pibase (расч.)", pibase / WIDTH_SCALE),)
                slot_points = [Point(r.x, r.y) for r in slot] + [Point(r.right, r.bottom) for r in slot]
                canvas.elements.append(
                    SchematicElement(
                        "DC",
                        "DC block",
                        bounds_from_points(left + right + slot_points),
                        params,
                        polygon=tuple(left + right),
                        auxiliary_rects=slot,
                    )
                )
        return right_joint

    def _radial_and_sis(self, canvas: _Canvas, config: S21Config, x: float, y: float, dw: float) -> float:
        # Element 14 «Линия SIS» has two parts: L1/W1 (the former line at
        # the SIS) and L2/W2 (the former Lw4/Ww4). They stay separate inputs
        # of the calculation; the SIS junction sits on their joint.
        parts = []
        for length_m, width_m in ((config.mex4_len_m, config.mex4_width_m), (config.zrad4_len_m, config.zrad4_width_m)):
            x = self._strip(canvas, "SIS-line", "Линия SIS", x, y, _um(length_m), _um(width_m), _um(width_m), dw)
            parts.append(canvas.elements.pop())
        first, second = parts
        feed = SchematicElement(
            "SIS-line",
            "Линия SIS",
            bounds_from_points(list(first.polygon) + list(second.polygon)),
            (
                ElementParameter("L1", _um(config.mex4_len_m)),
                ElementParameter("W1", _um(config.mex4_width_m)),
                ElementParameter("L2", _um(config.zrad4_len_m)),
                ElementParameter("W2", _um(config.zrad4_width_m)),
            ),
            first.input_port,
            second.output_port,
            polygon=first.polygon + second.polygon,
            auxiliary_rects=(first.bounds, second.bounds),
        )
        canvas.elements.append(feed)
        # Wb is an inductive-model width, not a specified mask width.
        # S/Wb therefore cannot supply a new length for this conductor.
        symbol = Point(first.output_port.center.x, y)
        # Sized by the narrower of the two joined parts, not by their lengths.
        symbol_radius = min(first.bounds.height, second.bounds.height) / 3
        canvas.circles.append(CircleShape(symbol, symbol_radius, fill="#fff"))
        canvas.elements.append(
            SchematicElement(
                "SIS",
                "SIS · условный символ",
                Rect(symbol.x - symbol_radius, y - symbol_radius, symbol_radius * 2, symbol_radius * 2),
                (
                    ElementParameter("S", config.sis_area_um2, "µm²"),
                    ElementParameter("Wb (расч.)", config.sis_width_um),
                ),
            )
        )
        w = _um(config.zrad3_width_m)
        x = self._strip(canvas, "Ww3", "Radial Stub line", x, y, _um(config.zrad3_len_m), w, w, dw)
        self._relabel(canvas, {"W": "W3", "L": "L3"})
        # Shared ports supply all fan/neck/output endpoints. Rmin is the base
        # strip width in RadialStubCalculator; the sector remains a schematic.
        radius, base = _um(config.radial_r_max_m) * WIDTH_SCALE, _um(config.radial_r_min_m) * WIDTH_SCALE
        left = canvas.elements[-1].output_port
        assert left is not None
        right = SectionPort(Point(x + base, y), (_um(config.zrad1_width_m) + dw) * WIDTH_SCALE)
        canvas.polygon([left.top, right.top, right.bottom, left.bottom], CONDUCTOR_FILL)
        canvas.shapes.append(("Radial", [left.top, right.top, right.bottom, left.bottom]))
        canvas.excluded_edges.extend(((left.top, right.top), (left.bottom, right.bottom)))
        angle = radians(config.radial_angle_deg / 2)
        dx, dy = radius * sin(angle), radius * cos(angle)
        middle_x = (left.center.x + right.center.x) / 2
        fan_bounds = []
        for direction, name in ((-1, "radial-upper"), (1, "radial-lower")):
            start, end = (left.top, right.top) if direction < 0 else (left.bottom, right.bottom)
            base_y = (start.y + end.y) / 2
            outer_left, outer_right = Point(middle_x - dx, base_y + direction * dy), Point(
                middle_x + dx, base_y + direction * dy
            )
            sweep = 1 if direction < 0 else 0
            large_arc = int(config.radial_angle_deg > 180)
            data = (
                _path([start, outer_left]) + f" A{radius:.12g},{radius:.12g} 0 {large_arc} {sweep} "
                f"{outer_right.x:.12g},{outer_right.y:.12g} L{end.x:.12g},{end.y:.12g}"
            )
            bounds = bounds_from_points(
                [start, end, outer_left, outer_right, Point(middle_x, base_y + direction * radius)]
            )
            if large_arc:
                bounds = Rect(middle_x - radius, bounds.y, 2 * radius, bounds.height)
            canvas.paths.append(PathShape(data + " Z", bounds, name + "-fill", fill=RADIAL_FILL, stroke="none"))
            canvas.paths.append(PathShape(data, bounds, name))
            canvas.include(bounds)
            arc = [
                Point(
                    middle_x + radius * sin(-angle + 2 * angle * k / 48),
                    base_y + direction * radius * cos(-angle + 2 * angle * k / 48),
                )
                for k in range(49)
            ]
            canvas.shapes.append(("Radial", [start, *arc, end]))
            fan_bounds.extend((Point(bounds.x, bounds.y), Point(bounds.right, bounds.bottom)))
        params = (
            ElementParameter("Rmin (вход модели)", _um(config.radial_r_min_m)),
            ElementParameter("Rmax", _um(config.radial_r_max_m)),
            ElementParameter("θ", config.radial_angle_deg, "°"),
        )
        canvas.elements.append(
            SchematicElement("Radial", "Радиальные шлейфы ×2", bounds_from_points(fan_bounds), params, left, right)
        )
        w = _um(config.zrad1_width_m)
        x = self._strip(canvas, "Ww1", "Выходная линия", right.center.x, y, _um(config.zrad1_len_m), w, w, dw)
        self._relabel(canvas, {"W": "W1", "L": "L1"})
        out = canvas.elements[-1].output_port
        assert out is not None
        canvas.polygon([out.top, Point(x + 26, y - 16), Point(x + 26, y + 16), out.bottom], "#f8fafc")
        canvas.rectangle(Rect(x + 26, y - 16, 44, 32), "#f8fafc")
        canvas.shapes.append(
            ("port", [out.top, Point(x + 26, y - 16), Point(x + 70, y - 16), Point(x + 70, y + 16), out.bottom])
        )
        return x + 70

    @staticmethod
    def _relabel(canvas: _Canvas, labels: dict[str, str]) -> None:
        """Name the last element's parameters as in its parameter group."""
        element = canvas.elements[-1]
        parameters = tuple(replace(p, label=labels.get(p.label, p.label)) for p in element.parameters)
        canvas.elements[-1] = replace(element, parameters=parameters)

    @staticmethod
    def _metal_outline(canvas: _Canvas) -> None:
        """Cancel shared faces and expose width steps once, without miter spikes.

        Sections have vertical join faces. Split those faces at all endpoints,
        cancel opposite orientations and assemble the remaining external edges.
        Shared intervals receive one thin seam instead of doubled outlines:
        every element boundary, including 13|14, the L1|L2 joint of 14 under
        the SIS circle and 14|16|17|18 around the radial stub (GitHub #11).
        """
        axis_edges: dict[tuple[str, float], list[tuple[float, float, int]]] = {}
        edges: list[tuple[Point, Point]] = []
        polygons = [p.points for p in canvas.polygons]
        polygons += [
            [
                Point(r.rect.x, r.rect.y),
                Point(r.rect.right, r.rect.y),
                Point(r.rect.right, r.rect.bottom),
                Point(r.rect.x, r.rect.bottom),
            ]
            for r in canvas.rects
        ]
        excluded = {frozenset((a, b)) for a, b in canvas.excluded_edges}
        for points in polygons:
            signed_area = sum(a.x * b.y - b.x * a.y for a, b in zip(points, points[1:] + points[:1]))
            if signed_area < 0:
                points = list(reversed(points))
            for a, b in zip(points, points[1:] + points[:1]):
                if frozenset((a, b)) in excluded:
                    continue
                if abs(a.x - b.x) < 1e-9:
                    axis_edges.setdefault(("v", round(a.x, 9)), []).append(
                        (min(a.y, b.y), max(a.y, b.y), 1 if b.y > a.y else -1)
                    )
                elif abs(a.y - b.y) < 1e-9:
                    axis_edges.setdefault(("h", round(a.y, 9)), []).append(
                        (min(a.x, b.x), max(a.x, b.x), 1 if b.x > a.x else -1)
                    )
                else:
                    edges.append((a, b))
        for (axis, position), spans in axis_edges.items():

            def at(value: float, axis: str = axis, position: float = position) -> Point:
                return Point(position, value) if axis == "v" else Point(value, position)

            cuts = sorted({v for lo, hi, _ in spans for v in (lo, hi)})
            for lo, hi in zip(cuts, cuts[1:]):
                covering = [sign for start, stop, sign in spans if start <= (lo + hi) / 2 <= stop]
                if sum(covering):
                    edges.append((at(lo), at(hi)))
                elif covering:
                    canvas.seams.append(LineShape(at(lo), at(hi), stroke=SEAM_COLOR, stroke_width=SEAM_WIDTH))

        def key(p: Point) -> tuple[float, float]:
            return round(p.x, 9), round(p.y, 9)

        chains = []
        while edges:
            a, b = edges.pop()
            points, changed = [a, b], True
            while changed:
                changed = False
                for i, (c, d) in enumerate(edges):
                    if key(c) == key(points[-1]):
                        points.append(d)
                    elif key(d) == key(points[-1]):
                        points.append(c)
                    elif key(c) == key(points[0]):
                        points.insert(0, d)
                    elif key(d) == key(points[0]):
                        points.insert(0, c)
                    else:
                        continue
                    edges.pop(i)
                    changed = True
                    break
            closed = key(points[0]) == key(points[-1])
            chains.append(_path(points[:-1] if closed else points, close=closed))
        canvas.paths.append(PathShape(" ".join(chains), bounds_from_points(canvas.bounds_points), "metal-outline"))

    @staticmethod
    def _number_labels(canvas: _Canvas, port_label: TextLabel) -> None:
        """Number every element right next to it, with an arrow to its edge.

        Labels keep clear of metal, the slot, each other and other arrows
        (``CalloutPlacer``); "SIS" gets its own arrow to the junction symbol.
        """
        shapes: list[tuple[str, list[Point]]] = []
        for element in canvas.elements:
            if element.element_id == "Radial":
                continue  # its fans and neck are in ``canvas.shapes``
            if element.element_id == "SIS":
                centre = Point(
                    element.bounds.x + element.bounds.width / 2, element.bounds.y + element.bounds.height / 2
                )
                radius = element.bounds.width / 2
                circle = [
                    Point(centre.x + radius * cos(radians(10 * k)), centre.y + radius * sin(radians(10 * k)))
                    for k in range(36)
                ]
                shapes.append(("SIS", circle))
                continue
            points = list(element.polygon)
            if element.element_id in {"DC", "SIS-line"}:
                # Two rectangles: the DC stubs, the two parts of line 14.
                shapes.extend((element.element_id, points[i : i + 4]) for i in range(0, len(points), 4))
            else:
                shapes.append((element.element_id, points))
            # The slot is drawn and kept clear, but 8 points at its stubs.
            shapes.extend(
                ("DC-slot", [Point(r.x, r.y), Point(r.right, r.y), Point(r.right, r.bottom), Point(r.x, r.bottom)])
                for r in (element.auxiliary_rects if element.element_id == "DC" else ())
            )
        # The slot belongs to the DC block; the 50 Ω port is no numbered element.
        canvas.hit_areas = [
            ("DC" if owner == "DC-slot" else owner, tuple(points))
            for owner, points in shapes + canvas.shapes
            if owner != "port"
        ]
        placer = CalloutPlacer(shapes + canvas.shapes, [port_label], soft_owners={"Radial"})
        # The SIS symbol sits on line 14: its arrows may cross that metal.
        requests = [
            (element.element_id, str(element.number), 10.0, "bold")
            for element in sorted(canvas.elements, key=lambda e: e.number or 0)
            if element.number is not None
        ] + [("SIS", "SIS", 11.0, "normal")]
        for element_id, text, size, weight in requests:
            transparent = {"SIS": {"SIS-line"}, "DC": {"DC-slot"}}.get(element_id, set())
            placed = placer.place(element_id, text, font_size=size, font_weight=weight, transparent=transparent)
            if placed is None:
                raise ValueError(f"Не удалось разместить номер {text} на схеме")
            label, arrow = placed
            canvas.labels.append(label)
            canvas.lines.append(arrow)
            canvas.callouts.append(Callout(element_id, label, arrow))
        for box in placer.boxes:
            canvas.bounds_points.extend((Point(box.x0, box.y0), Point(box.x1, box.y1)))

    def _dimensioned_views(self, canvas: _Canvas, dw: float) -> None:
        """Attach dimensioned enlargements to actual element IDs/ports.

        Tiny sections cannot fit several legible W/L labels at physical scale.
        Insets use one stated zoom on both axes; they never distort a section.
        """
        elements = list(canvas.elements)
        top, card_w, card_h, columns = max(p.y for p in canvas.bounds_points) + 36, 310.0, 265.0, 3
        canvas.labels.append(
            TextLabel(
                Point(28, top),
                f"Размеры элементов · µm · dW={dw:g} µm",
                12,
                font_weight="bold",
            )
        )
        canvas.labels.append(
            TextLabel(
                Point(28, top + 18),
                "Текст W — ввод; стрелки Wэфф — металл с dW. Для щели dW вычитается. Выноски сохраняют пропорции.",
                10,
            )
        )
        for i, element in enumerate(elements):
            first_dimension = len(canvas.dimensions)
            self._element_view(
                canvas, element, dw, 28 + (i % columns) * card_w, top + 42 + (i // columns) * card_h, card_w
            )
            for index in range(first_dimension, len(canvas.dimensions)):
                canvas.dimensions[index] = replace(canvas.dimensions[index], element_id=element.element_id)
        canvas.include(
            Rect(24, top - 14, card_w * columns + 10, 48 + ((len(elements) + columns - 1) // columns) * card_h)
        )

    def _element_view(
        self,
        canvas: _Canvas,
        element: SchematicElement,
        dw: float,
        x: float,
        y: float,
        card_w: float,
    ) -> None:
        canvas.labels.append(TextLabel(Point(x, y), element.title, 12, font_weight="bold"))
        words = [f"{p.label}={p.value:g} {p.unit}" for p in element.parameters]
        lines, current = [], ""
        for word in words:
            if len(current) + len(word) > 40 and current:
                lines.append(current)
                current = ""
            current += ("; " if current else "") + word
        lines.append(current)
        canvas.labels.append(TextLabel(Point(x, y + 18), "\n".join(lines), 10))
        if element.element_id == "SIS":
            center = Point(x + 135, y + 120)
            canvas.lines.append(LineShape(Point(center.x - 40, center.y), Point(center.x + 40, center.y)))
            canvas.circles.append(CircleShape(center, 12, fill="#fff"))
            canvas.labels.extend(
                (
                    TextLabel(Point(x, y + 162), "Wb — ширина для индуктивной поправки", 10),
                    TextLabel(Point(x, y + 180), "Геометрия площади S в модели не задана", 10),
                )
            )
            return
        if element.element_id == "Radial":
            self._radial_dimensions(canvas, element, x, y)
            return
        canvas.labels.append(TextLabel(Point(x, y + 60), f"Металл: Wэфф = W + dW; dW={dw:g} µm", 9, fill="#64748b"))
        if element.element_id == "DC":
            self._dc_dimensions(canvas, element, dw, x, y, card_w)
            return
        if element.element_id in CORNER_TRANSFORMERS:
            dc = next(e for e in canvas.elements if e.element_id == "DC")
            self._corner_dimensions(canvas, element, dc, x, y, card_w)
            return
        if element.element_id == "SIS-line":
            self._sis_line_dimensions(canvas, element, x, y, card_w)
            return
        assert element.input_port is not None and element.output_port is not None
        length = element.output_port.center.x - element.input_port.center.x
        # Lines name W/L as their parameter group does (W3/L3 of 16, W1/L1 of 18).
        names = [p.label for p in element.parameters]
        transformer = element.element_id.startswith("T")
        width_label, length_label = ("W1", "L") if transformer else (names[0], names[1])
        height = max(element.input_port.width, element.output_port.width)
        zoom = min(155 / length, 98 / height)
        px, center_y = x + (card_w - length * zoom) / 2, y + 128
        start = SectionPort(Point(px, center_y), element.input_port.width * zoom)
        end = SectionPort(Point(px + length * zoom, center_y), element.output_port.width * zoom)
        canvas.polygons.append(
            PolygonShape(
                [start.top, end.top, end.bottom, start.bottom],
                fill=TRANSFORMER_FILL if element.element_id.startswith("T") else CONDUCTOR_FILL,
            )
        )
        dim_y = center_y + height * zoom / 2 + 18
        canvas.dimensions.extend(
            (
                DimensionLine(
                    Point(start.center.x, dim_y),
                    Point(end.center.x, dim_y),
                    f"{length_label}={length / LENGTH_SCALE:g}",
                    Point((start.center.x + end.center.x) / 2, dim_y + 16),
                ),
                DimensionLine(
                    Point(start.center.x - 12, start.top.y),
                    Point(start.center.x - 12, start.bottom.y),
                    f"{width_label}эфф={element.input_port.width / WIDTH_SCALE:g}",
                    Point(start.center.x - 20, center_y),
                    -90,
                ),
            )
        )
        if element.element_id.startswith("T"):
            canvas.dimensions.append(
                DimensionLine(
                    Point(end.center.x + 12, end.top.y),
                    Point(end.center.x + 12, end.bottom.y),
                    f"W2эфф={element.output_port.width / WIDTH_SCALE:g}",
                    Point(end.center.x + 28, center_y),
                    -90,
                )
            )
        for port in (start, end):
            side = -12 if port is start else 12
            canvas.lines.extend(
                (
                    LineShape(port.top, Point(port.top.x + side, port.top.y), stroke="#64748b", stroke_width=0.4),
                    LineShape(
                        port.bottom, Point(port.bottom.x + side, port.bottom.y), stroke="#64748b", stroke_width=0.4
                    ),
                )
            )
        canvas.labels.append(
            TextLabel(Point(x, y + 245), f"Масштаб выноски ×{zoom:.3g} относительно общей схемы", 9, fill="#64748b")
        )

    @staticmethod
    def _corner_dimensions(
        canvas: _Canvas, element: SchematicElement, dc: SchematicElement, x: float, y: float, card_w: float
    ) -> None:
        """Corner transformer with the top of its stub and the L1/L2/L3 centre line."""
        values = {p.label: p.value for p in element.parameters}
        left_side = element.element_id == "T4"
        stub = dc.polygon[:4] if left_side else dc.polygon[4:]
        contour = element.polygon
        contact_y = stub[0].y
        stub_part = min(stub[2].y - contact_y, element.bounds.height * 0.6)
        stub_top = [stub[0], stub[1], Point(stub[1].x, contact_y + stub_part), Point(stub[0].x, contact_y + stub_part)]
        b = bounds_from_points(list(contour) + stub_top)
        zoom = min(170 / b.width, 96 / b.height)
        origin = Point(x + (card_w - b.width * zoom) / 2, y + 82)

        def m(p: Point) -> Point:
            return Point(origin.x + (p.x - b.x) * zoom, origin.y + (p.y - b.y) * zoom)

        canvas.polygons.append(PolygonShape([m(p) for p in stub_top], fill=DC_FILL, stroke="#64748b", stroke_width=0.5))
        canvas.polygons.append(PolygonShape([m(p) for p in contour], fill=TRANSFORMER_FILL))
        for line in element.auxiliary_lines:
            canvas.lines.append(replace(line, start=m(line.start), end=m(line.end)))
        for line in element.auxiliary_lines[:-1]:
            canvas.circles.append(CircleShape(m(line.end), 1.8, fill=CENTRE_LINE_COLOR, stroke="none"))

        port = element.input_port if left_side else element.output_port
        assert port is not None
        joint_top, joint_bottom = m(port.top), m(port.bottom)
        line_label, contact_label = ("W1", "W2") if left_side else ("W2", "W1")
        # The contact is the foot, centred on the last (vertical) centre segment.
        dw = port.width / WIDTH_SCALE - values[line_label]
        contact_w = (values[contact_label] + dw) * WIDTH_SCALE
        middle = element.auxiliary_lines[-1].end.x
        contact_l, contact_r = m(Point(middle - contact_w / 2, 0)).x, m(Point(middle + contact_w / 2, 0)).x
        bottom = m(Point(0, contact_y + stub_part)).y
        side = -1 if left_side else 1
        canvas.dimensions.extend(
            (
                DimensionLine(
                    Point(joint_top.x + side * 12, joint_top.y),
                    Point(joint_top.x + side * 12, joint_bottom.y),
                    f"{line_label}эфф={port.width / WIDTH_SCALE:g}",
                    Point(joint_top.x + side * 24, (joint_top.y + joint_bottom.y) / 2),
                    -90,
                ),
                DimensionLine(
                    Point(contact_l, bottom + 10),
                    Point(contact_r, bottom + 10),
                    f"{contact_label}эфф={values[contact_label] + dw:g}",
                    Point((contact_l + contact_r) / 2, bottom + 24),
                ),
            )
        )
        canvas.labels.append(
            TextLabel(
                Point(x, y + 224),
                f"L = L1+L2+L3 = {values['L1']:g} + {values['L2']:g} + {values['L3']:g}",
                9,
                fill="#64748b",
            )
        )
        total = values["L1"] + values["L2"] + values["L3"]
        if total > values["L"] + 1e-3:
            canvas.labels.append(
                TextLabel(
                    Point(x, y + 72),
                    f"L={values['L']:g} меньше минимума {total:.3g}: ступня у торца, снизу скос",
                    9,
                    fill=WARNING_COLOR,
                )
            )
        canvas.labels.append(
            TextLabel(
                Point(x, y + 248),
                f"Масштаб ×{zoom:.3g} · оранжевое — осевая линия · снизу — шлейф DC block",
                9,
                fill="#64748b",
            )
        )

    @staticmethod
    def _sis_line_dimensions(canvas: _Canvas, element: SchematicElement, x: float, y: float, card_w: float) -> None:
        """Element 14: parts L1/W1 and L2/W2 with the SIS junction on their joint."""
        first, second = element.auxiliary_rects
        length = first.width + second.width
        height = max(first.height, second.height)
        zoom = min(170 / length, 80 / height)
        left, center_y = x + (card_w - length * zoom) / 2, y + 124

        def part(rect: Rect, start: float) -> Rect:
            return Rect(start, center_y - rect.height * zoom / 2, rect.width * zoom, rect.height * zoom)

        a = part(first, left)
        b = part(second, a.right)
        for rect in (a, b):
            corners = [Point(rect.x, rect.y), Point(rect.right, rect.y), Point(rect.right, rect.bottom)]
            canvas.polygons.append(PolygonShape(corners + [Point(rect.x, rect.bottom)], fill=CONDUCTOR_FILL))
        canvas.circles.append(CircleShape(Point(a.right, center_y), min(a.height, b.height) / 4, fill="#fff"))
        values = {p.label: p.value for p in element.parameters}
        dim_y = max(a.bottom, b.bottom) + 18
        canvas.dimensions.extend(
            (
                DimensionLine(
                    Point(a.x, dim_y),
                    Point(a.right, dim_y),
                    f"L1={values['L1']:g}",
                    Point(a.x + a.width / 2, dim_y + 16),
                ),
                DimensionLine(
                    Point(b.x, dim_y + 26),
                    Point(b.right, dim_y + 26),
                    f"L2={values['L2']:g}",
                    Point(b.x + b.width / 2, dim_y + 42),
                ),
                DimensionLine(
                    Point(a.x - 12, a.y),
                    Point(a.x - 12, a.bottom),
                    f"W1эфф={first.height / WIDTH_SCALE:g}",
                    Point(a.x - 20, center_y),
                    -90,
                ),
                DimensionLine(
                    Point(b.right + 12, b.y),
                    Point(b.right + 12, b.bottom),
                    f"W2эфф={second.height / WIDTH_SCALE:g}",
                    Point(b.right + 28, center_y),
                    -90,
                ),
            )
        )
        canvas.labels.append(
            TextLabel(
                Point(x, y + 245),
                f"Масштаб ×{zoom:.3g} · кружок — SIS на стыке L1/L2",
                9,
                fill="#64748b",
            )
        )

    @staticmethod
    def _dc_dimensions(
        canvas: _Canvas, element: SchematicElement, dw: float, x: float, y: float, card_w: float
    ) -> None:
        values = {p.label: p.value for p in element.parameters}
        b = element.bounds
        # Two dimension rows (48) below the stubs, the Wslot row (22) below the
        # arms, then the Pibase row (26); all stay above the footnotes at y+236.
        stub_bottom = max(p.y for p in element.polygon) - b.y
        zoom = min(180 / b.width, 100 / b.height, 74 / stub_bottom)
        origin = Point(x + (card_w - b.width * zoom) / 2, y + 78)

        def m(p: Point) -> Point:
            return Point(origin.x + (p.x - b.x) * zoom, origin.y + (p.y - b.y) * zoom)

        h_left, _gap_piece, _h_right, arm_left, arm_right = element.auxiliary_rects
        for rect in element.auxiliary_rects:
            corners = [Point(rect.x, rect.y), Point(rect.right, rect.y), Point(rect.right, rect.bottom)]
            corners.append(Point(rect.x, rect.bottom))
            canvas.polygons.append(PolygonShape([m(p) for p in corners], fill=SLOT_FILL, stroke="none"))
        left, right = [m(p) for p in element.polygon[:4]], [m(p) for p in element.polygon[4:]]
        canvas.polygons.extend((PolygonShape(left, fill=DC_FILL), PolygonShape(right, fill=DC_FILL)))

        outer_l, inner_l, stub_top_l, stub_end = left[0].x, left[1].x, left[0].y, left[2].y
        inner_r, outer_r = right[0].x, right[1].x
        slot_top, slot_bottom = m(Point(0, h_left.y)).y, m(Point(0, h_left.bottom)).y
        arm_l_x, arm_r_x = m(Point(arm_left.right, 0)).x, m(Point(arm_right.x, 0)).x
        arm_left_outer, arm_left_inner = m(Point(arm_left.x, 0)).x, arm_l_x
        arm_end = m(Point(0, arm_right.bottom)).y
        lslot, lso = values["Lslot"], values["Lso"]
        # Labels avoid the black arms: W labels are centred between the arms,
        # Lso starts right of the stub, Lslot sits outside the left arm.
        # Pibase and Lso end at the inner arm edges, as in the sketch.
        center_x = (inner_l + inner_r) / 2
        lso_label = f"Lso={lso:g}"
        lso_width = len(lso_label) * 5.5
        lso_x = min(outer_r + 3 + lso_width / 2, x + card_w - 4 - lso_width / 2)
        pibase_y = max(arm_end + 22, stub_end + 48) + 12
        slot_label = f"Wslotэфф={values['Wslot'] - dw:g}"
        canvas.dimensions.extend(
            (
                DimensionLine(
                    Point(outer_l, stub_end + 12),
                    Point(inner_l, stub_end + 12),
                    f"Wmsэфф={values['Wms'] + dw:g}",
                    Point(center_x, stub_end + 26),
                ),
                DimensionLine(
                    Point(inner_l, stub_end + 34),
                    Point(inner_r, stub_end + 34),
                    f"Зазор={values['Зазор']:g}",
                    Point(center_x, stub_end + 48),
                ),
                DimensionLine(
                    Point(outer_l + (inner_l - outer_l) * 0.25, stub_top_l),
                    Point(outer_l + (inner_l - outer_l) * 0.25, stub_end),
                    f"Lms={values['Lms']:g}",
                    Point(outer_l + (inner_l - outer_l) * 0.75, (stub_top_l + stub_end) / 2),
                    -90,
                ),
                DimensionLine(
                    Point(outer_r, slot_bottom + 9),
                    Point(arm_r_x, slot_bottom + 9),
                    lso_label,
                    Point(lso_x, slot_top - 5),
                ),
                DimensionLine(
                    Point(arm_left_outer - 10, slot_top),
                    Point(arm_left_outer - 10, arm_end),
                    f"Lslot={lslot:g}",
                    Point(arm_left_outer - 18, (slot_top + arm_end) / 2),
                    -90,
                ),
                # Slot thickness across the left arm, labelled outside it.
                DimensionLine(
                    Point(arm_left_outer, arm_end + 8),
                    Point(arm_left_inner, arm_end + 8),
                    slot_label,
                    Point(max(x + len(slot_label) * 2.8, arm_left_outer - 4 - len(slot_label) * 2.8), arm_end + 20),
                ),
                DimensionLine(
                    Point(arm_l_x, pibase_y),
                    Point(arm_r_x, pibase_y),
                    f"Pibase={values['Pibase (расч.)']:g}=2·Wmsэфф+2·Lso+зазор",
                    Point((arm_l_x + arm_r_x) / 2, pibase_y + 14),
                ),
            )
        )
        canvas.labels.append(
            TextLabel(
                Point(x, y + 236),
                "Чёрное — щель в нижнем электроде, на 1 µm ниже верха шлейфов (HFSS)",
                9,
                fill="#64748b",
            )
        )
        canvas.labels.append(
            TextLabel(
                Point(x, y + 248),
                f"Масштаб ×{zoom:.3g} · сверху — ступни трансформаторов 7/9",
                9,
                fill="#64748b",
            )
        )

    @staticmethod
    def _radial_dimensions(canvas: _Canvas, element: SchematicElement, x: float, y: float) -> None:
        values = {p.label: p.value for p in element.parameters}
        radius = values["Rmax"]
        large_arc = int(values["θ"] > 180)
        view_radius = 49 if large_arc else 66
        zoom, center, angle = (
            view_radius / radius,
            Point(x + 150, y + (128 if large_arc else 155)),
            radians(values["θ"] / 2),
        )
        a, b = Point(center.x - view_radius * sin(angle), center.y - view_radius * cos(angle)), Point(
            center.x + view_radius * sin(angle), center.y - view_radius * cos(angle)
        )
        data = _path([center, a]) + f" A{view_radius},{view_radius} 0 {large_arc} 1 {b.x:g},{b.y:g} Z"
        canvas.paths.append(
            PathShape(
                data,
                Rect(
                    center.x - view_radius,
                    center.y - view_radius,
                    2 * view_radius,
                    view_radius * (2 if large_arc else 1),
                ),
                "radial-dimension-view",
                fill=RADIAL_FILL,
            )
        )
        canvas.dimensions.append(DimensionLine(center, b, f"Rmax={radius:g}", Point(b.x + 26, b.y + 20)))
        canvas.labels.extend(
            (
                TextLabel(Point(x + 105, y + 192), f"θ={values['θ']:g}°", 11),
                TextLabel(Point(x, y + 220), f"Rmin={values['Rmin (вход модели)']:g} µm — горловина модели", 9),
                TextLabel(
                    Point(x, y + 245),
                    f"Масштаб выноски ×{zoom / WIDTH_SCALE:.3g}; два одинаковых шлейфа",
                    9,
                    fill="#64748b",
                ),
            )
        )

    @staticmethod
    def _transformer_physical_length_um(
        start_width_m: float, end_width_m: float, width_step_um: float, length_step_m: float
    ) -> float:
        return _um(transformer_length_m(start_width_m, end_width_m, width_step_um, length_step_m))
