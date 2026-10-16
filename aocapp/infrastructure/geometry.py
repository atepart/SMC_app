"""Inspectable protocol: config -> sections -> ports -> contours -> dimensions.

SI lengths are converted to µm once. Both SVG axes have the same scale.
Different endpoint widths form an explicit step at a shared join plane;
they never change a calculation input or introduce a longitudinal gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import cos, isfinite, radians, sin

from aocapp.domain.models import (
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
from aocapp.domain.ports import StructureCalculator
from aocapp.domain.s21_models import S21Config
from aocapp.domain.transformers import ELEMENT_NUMBERS, SCHEMATIC_SECTIONS, transformer_length_m

LENGTH_SCALE = WIDTH_SCALE = 2.0
CONDUCTOR_FILL = "#e8f1f5"
TRANSFORMER_FILL = "#dbeafe"
RADIAL_FILL = "#e8f1f5"
DC_FILL = "#d7edf5"


def _um(value_m: float) -> float:
    return value_m * 1e6


def _path(points: list[Point], close: bool = False) -> str:
    return "M" + " L".join(f"{p.x:.12g},{p.y:.12g}" for p in points) + (" Z" if close else "")


@dataclass
class _Canvas:
    polygons: list[PolygonShape] = field(default_factory=list)
    paths: list[PathShape] = field(default_factory=list)
    rects: list[RectShape] = field(default_factory=list)
    circles: list[CircleShape] = field(default_factory=list)
    lines: list[LineShape] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    dimensions: list[DimensionLine] = field(default_factory=list)
    elements: list[SchematicElement] = field(default_factory=list)
    bounds_points: list[Point] = field(default_factory=list)
    excluded_edges: list[tuple[Point, Point]] = field(default_factory=list)

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
            bounds=Rect(bounds.x - 20, bounds.y - 20, bounds.width + 40, bounds.height + 40),
        )


@dataclass
class IntegratedStructureCalculator(StructureCalculator):
    """Place each section at its predecessor's output X, on one centre line."""

    def calculate(self, config: S21Config) -> StructureGeometry:
        for name in ("w_slot_m", "l_slot_m", "w_ms_m", "l_ms_m", "lso_m", "radial_r_min_m", "radial_r_max_m"):
            value = getattr(config, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name}: размер должен быть положительным конечным числом")
        if not isfinite(config.dw_m) or config.dw_m < 0 or config.w_slot_m <= config.dw_m:
            raise ValueError("Щель Wslot − DW должна быть положительной; DW — неотрицательным")
        if not isfinite(config.radial_angle_deg) or not 0 < config.radial_angle_deg < 360:
            raise ValueError("Угол радиального шлейфа должен лежать между 0 и 360°")
        canvas = _Canvas()
        dw, y, x = _um(config.dw_m), 0.0, 28.0
        for matrix, sections in SCHEMATIC_SECTIONS.items():
            for number, name in sections:
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
        self._number_labels(canvas)
        metal = bounds_from_points(canvas.bounds_points)
        canvas.labels.extend(
            (
                TextLabel(
                    Point(28, metal.y - 24),
                    "Структура HD35 · от ФФО к SIS · геометрические размеры в µm",
                    12,
                    font_weight="bold",
                ),
                TextLabel(Point(28, metal.bottom + 24), "ФФО", 11),
                TextLabel(Point(x - 34, -24), "50 Ω", 11, anchor="middle"),
            )
        )
        canvas.include(Rect(28, metal.y - 40, x - 28, metal.height + 75))
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
        gap = (_um(config.w_slot_m) - dw) * WIDTH_SCALE
        width = (_um(config.w_ms_m) + dw) * WIDTH_SCALE
        lead, depth = _um(config.l_ms_m) * LENGTH_SCALE, _um(config.l_slot_m) * LENGTH_SCALE
        left_port = SectionPort(Point(x, y), width)
        inner = x + lead + width
        right_x = inner + gap + width + lead
        right_port = SectionPort(Point(right_x, y), width)
        top, bottom = left_port.top.y, left_port.bottom.y
        left = [
            left_port.top,
            Point(inner - width / 2, top),
            Point(inner, bottom),
            Point(inner, bottom + depth),
            Point(inner - width, bottom + depth),
            Point(inner - width, bottom),
            left_port.bottom,
        ]
        right = [
            right_port.top,
            Point(inner + gap + width / 2, top),
            Point(inner + gap, bottom),
            Point(inner + gap, bottom + depth),
            Point(inner + gap + width, bottom + depth),
            Point(inner + gap + width, bottom),
            right_port.bottom,
        ]
        canvas.polygon(left, DC_FILL)
        canvas.polygon(right, DC_FILL)
        leads = []
        for contact, outside in ((inner - width, x - 8), (inner + gap + width, right_x + 8)):
            offset_y = bottom + _um(config.lso_m) * LENGTH_SCALE
            leads.extend(
                (
                    LineShape(Point(contact, offset_y), Point(outside, offset_y), stroke_width=2),
                    LineShape(Point(outside, offset_y), Point(outside, bottom + depth + 10), stroke_width=2),
                )
            )
        canvas.lines.extend(leads)
        canvas.bounds_points.extend(point for line in leads for point in (line.start, line.end))
        params = tuple(
            ElementParameter(label, _um(getattr(config, field_name)))
            for label, field_name in (
                ("Wslot", "w_slot_m"),
                ("Lslot", "l_slot_m"),
                ("Lso", "lso_m"),
                ("Wms", "w_ms_m"),
                ("Lms", "l_ms_m"),
            )
        )
        canvas.elements.append(
            SchematicElement(
                "DC",
                "DC block",
                bounds_from_points(left + right),
                params,
                left_port,
                right_port,
                polygon=tuple(left + right),
                auxiliary_lines=tuple(leads),
            )
        )
        return right_x

    def _radial_and_sis(self, canvas: _Canvas, config: S21Config, x: float, y: float, dw: float) -> float:
        feed_start = x
        x = self._strip(
            canvas,
            "SIS-line",
            "Линия у SIS",
            x,
            y,
            _um(config.mex4_len_m),
            _um(config.mex4_width_m),
            _um(config.mex4_width_m),
            dw,
        )
        feed = canvas.elements[-1]
        # W SIS is an inductive-model width, not a specified mask width.
        # S/W therefore cannot supply a new length for this conductor.
        symbol = Point((feed_start + x) / 2, y)
        symbol_radius = min(feed.bounds.width, feed.bounds.height) / 3
        canvas.circles.append(CircleShape(symbol, symbol_radius, fill="#fff"))
        canvas.elements.append(
            SchematicElement(
                "SIS",
                "SIS · условный символ",
                Rect(symbol.x - symbol_radius, y - symbol_radius, symbol_radius * 2, symbol_radius * 2),
                (
                    ElementParameter("S", config.sis_area_um2, "µm²"),
                    ElementParameter("W SIS (расч.)", config.sis_width_um),
                ),
            )
        )
        canvas.labels.append(TextLabel(Point(feed_start - 12, feed.bounds.bottom + 24), "SIS", 11, anchor="end"))
        canvas.lines.append(LineShape(Point(feed_start - 10, feed.bounds.bottom + 18), symbol, stroke="#64748b"))
        for index in (4, 3):
            w = _um(getattr(config, f"zrad{index}_width_m"))
            x = self._strip(
                canvas, f"Ww{index}", f"Линия Ww{index}", x, y, _um(getattr(config, f"zrad{index}_len_m")), w, w, dw
            )
        # Shared ports supply all fan/neck/output endpoints. Rmin is the base
        # strip width in RadialStubCalculator; the sector remains a schematic.
        radius, base = _um(config.radial_r_max_m) * WIDTH_SCALE, _um(config.radial_r_min_m) * WIDTH_SCALE
        left = canvas.elements[-1].output_port
        assert left is not None
        right = SectionPort(Point(x + base, y), (_um(config.zrad1_width_m) + dw) * WIDTH_SCALE)
        canvas.polygon([left.top, right.top, right.bottom, left.bottom], CONDUCTOR_FILL)
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
        x = self._strip(canvas, "Ww1", "Выходная линия Ww1", right.center.x, y, _um(config.zrad1_len_m), w, w, dw)
        out = canvas.elements[-1].output_port
        assert out is not None
        canvas.polygon([out.top, Point(x + 26, y - 16), Point(x + 26, y + 16), out.bottom], "#f8fafc")
        canvas.rectangle(Rect(x + 26, y - 16, 44, 32), "#f8fafc")
        return x + 70

    @staticmethod
    def _metal_outline(canvas: _Canvas) -> None:
        """Cancel shared faces and expose width steps once, without miter spikes.

        Sections have vertical join faces. Split those faces at all endpoints,
        cancel opposite orientations and assemble the remaining external edges.
        Shared intervals receive one thin separator instead of doubled outlines.
        """
        vertical: dict[float, list[tuple[float, float, int]]] = {}
        edges: list[tuple[Point, Point]] = []
        # These are consecutive parts of one SIS/radial conductor, not
        # numbered section boundaries. Keep only its exterior width steps.
        unmarked_joins = {
            round(e.input_port.center.x, 9)
            for e in canvas.elements
            if e.input_port is not None and e.element_id in {"Ww4", "Ww3", "Radial", "Ww1"}
        }
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
                    vertical.setdefault(round(a.x, 9), []).append(
                        (min(a.y, b.y), max(a.y, b.y), 1 if b.y > a.y else -1)
                    )
                else:
                    edges.append((a, b))
        for x, spans in vertical.items():
            cuts = sorted({v for lo, hi, _ in spans for v in (lo, hi)})
            for lo, hi in zip(cuts, cuts[1:]):
                covering = [sign for start, stop, sign in spans if start <= (lo + hi) / 2 <= stop]
                if sum(covering):
                    edges.append((Point(x, lo), Point(x, hi)))
                elif covering and x not in unmarked_joins:
                    canvas.lines.append(LineShape(Point(x, lo), Point(x, hi), stroke="#64748b", stroke_width=0.45))

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
    def _number_labels(canvas: _Canvas) -> None:
        top, last_x = min(p.y for p in canvas.bounds_points) - 12, -1e9
        for element in canvas.elements:
            if element.number is None:
                continue
            center_x = element.bounds.x + element.bounds.width / 2
            label_x = max(center_x, last_x + 24)
            label_y = top - (16 if element.number % 2 == 0 else 0)
            canvas.labels.append(
                TextLabel(Point(label_x, label_y), str(element.number), 10, anchor="middle", font_weight="bold")
            )
            canvas.lines.append(
                LineShape(
                    Point(label_x, label_y + 4),
                    Point(center_x, element.bounds.y - 3),
                    stroke="#64748b",
                    stroke_width=0.5,
                )
            )
            canvas.bounds_points.append(Point(label_x + 7, label_y - 12))
            last_x = label_x

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
                f"Размеры элементов · µm · DW={dw:g} µm",
                12,
                font_weight="bold",
            )
        )
        canvas.labels.append(
            TextLabel(
                Point(28, top + 18),
                "Текст W — ввод; стрелки Wэфф — металл с DW. Для щели DW вычитается. Выноски сохраняют пропорции.",
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
                    TextLabel(Point(x, y + 162), "W SIS — ширина для индуктивной поправки", 10),
                    TextLabel(Point(x, y + 180), "Геометрия площади S в модели не задана", 10),
                )
            )
            return
        if element.element_id == "Radial":
            self._radial_dimensions(canvas, element, x, y)
            return
        canvas.labels.append(TextLabel(Point(x, y + 60), f"Металл: Wэфф = W + DW; DW={dw:g} µm", 9, fill="#64748b"))
        if element.element_id == "DC":
            self._dc_dimensions(canvas, element, dw, x, y)
            return
        assert element.input_port is not None and element.output_port is not None
        length = element.output_port.center.x - element.input_port.center.x
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
                    f"L={length / LENGTH_SCALE:g}",
                    Point((start.center.x + end.center.x) / 2, dim_y + 16),
                ),
                DimensionLine(
                    Point(start.center.x - 12, start.top.y),
                    Point(start.center.x - 12, start.bottom.y),
                    f"{'W1' if element.element_id.startswith('T') else 'W'}эфф={element.input_port.width / WIDTH_SCALE:g}",
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
    def _dc_dimensions(canvas: _Canvas, element: SchematicElement, dw: float, x: float, y: float) -> None:
        values = {p.label: p.value for p in element.parameters}
        height = max(element.bounds.height, (values["Wms"] + dw + values["Lso"]) * WIDTH_SCALE)
        zoom = min(160 / element.bounds.width, 90 / height)
        origin = Point(x + 65, y + 100)

        def mapped_point(p: Point) -> Point:
            return Point(origin.x + (p.x - element.bounds.x) * zoom, origin.y + (p.y - element.bounds.y) * zoom)

        mapped = [mapped_point(p) for p in element.polygon]
        canvas.polygons.extend((PolygonShape(mapped[:7], fill=DC_FILL), PolygonShape(mapped[7:], fill=DC_FILL)))
        canvas.lines.extend(
            replace(line, start=mapped_point(line.start), end=mapped_point(line.end), stroke_width=1)
            for line in element.auxiliary_lines
        )
        width, lead = (values["Wms"] + dw) * WIDTH_SCALE * zoom, values["Lms"] * LENGTH_SCALE * zoom
        inner, gap = origin.x + lead + width, (values["Wslot"] - dw) * WIDTH_SCALE * zoom
        bottom, depth = origin.y + width, values["Lslot"] * LENGTH_SCALE * zoom
        canvas.dimensions.extend(
            (
                DimensionLine(
                    Point(inner, bottom + depth + 12),
                    Point(inner + gap, bottom + depth + 12),
                    f"Wslotэфф={values['Wslot'] - dw:g}",
                    Point(inner + gap / 2, bottom + depth + 28),
                ),
                DimensionLine(
                    Point(origin.x - 14, bottom),
                    Point(origin.x - 14, bottom + depth),
                    f"Lslot={values['Lslot']:g}",
                    Point(origin.x - 22, bottom + depth / 2),
                    -90,
                ),
                DimensionLine(
                    Point(origin.x, origin.y - 12),
                    Point(origin.x + lead, origin.y - 12),
                    f"Lms={values['Lms']:g}",
                    Point(origin.x + lead / 2, origin.y - 20),
                ),
                DimensionLine(
                    Point(origin.x + lead / 2, origin.y),
                    Point(origin.x + lead / 2, bottom),
                    f"Wmsэфф={values['Wms'] + dw:g}",
                    Point(x + 165, origin.y - 20),
                ),
            )
        )
        canvas.lines.append(
            LineShape(
                Point(x + 122, origin.y - 18),
                Point(origin.x + lead / 2, origin.y + width / 2),
                stroke="#64748b",
                stroke_width=0.4,
            )
        )
        canvas.labels.append(
            TextLabel(Point(x, y + 245), f"Масштаб выноски ×{zoom:.3g} · щель остаётся раздельной", 9, fill="#64748b")
        )
        canvas.labels.append(
            TextLabel(Point(x, y + 230), "Чёрные отводы условные; их размеры не заданы", 9, fill="#64748b")
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
