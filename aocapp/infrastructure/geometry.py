"""Geometry calculator for the complete S21 network schematic.

The preview is deliberately derived from the same :class:`S21Config` fields
as ``S21CalculatorImpl``.  Its left-to-right order follows the supplied
engineering sketch (FFO toward the detector-side matching network), which is
the reverse of the matrix multiplication order used by the calculator::

    drawing:      FFO -> Mex01 -> Mex02 -> Mdcb -> Mex03 -> Mex04
    calculation:  Mex4  -> Mex3  -> Mdcb -> Mex2  -> Mex1

Reversing the visual order does not change the formulas; it only presents the
physical chain in the orientation used by the reference drawing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import floor, radians, sin
from typing import Iterable

from aocapp.domain.models import (
    CircleShape,
    DimensionLine,
    GroupBoxShape,
    LineShape,
    PathShape,
    Point,
    PolygonShape,
    Rect,
    RectShape,
    StructureGeometry,
    TextLabel,
    bounds_from_points,
)
from aocapp.domain.ports import StructureCalculator
from aocapp.domain.s21_models import S21Config

LENGTH_SCALE = 2.0
WIDTH_SCALE = 2.0
MIN_SEGMENT_LENGTH = 44.0
CONDUCTOR_FILL = "#e8f1f5"
TRANSFORMER_FILL = "#dbeafe"
RADIAL_FILL = "#fde68a"
DC_FILL = "#d7edf5"

# Local numbers on Mathcad PNG item 587, repeated within each matrix.
# Tuple order follows the physical drawing, from FFO toward the detector.
REFERENCE_SECTIONS = {
    "Mex01": ((3, "T7"), (2, "MSL8"), (1, "T6")),
    "Mex02": ((4, "MSL7"), (3, "T5"), (2, "MSL6"), (1, "T4")),
    "Mex03": ((5, "T3"), (4, "MSL5"), (3, "T2"), (2, "MSL4"), (1, "T1")),
}
REFERENCE_NUMBERS = {name: number for entries in REFERENCE_SECTIONS.values() for number, name in entries}


@dataclass
class _Canvas:
    """Mutable collector used only while assembling an immutable geometry."""

    polygons: list[PolygonShape] = field(default_factory=list)
    paths: list[PathShape] = field(default_factory=list)
    rects: list[RectShape] = field(default_factory=list)
    circles: list[CircleShape] = field(default_factory=list)
    lines: list[LineShape] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    dimensions: list[DimensionLine] = field(default_factory=list)
    groups: list[GroupBoxShape] = field(default_factory=list)
    bounds_points: list[Point] = field(default_factory=list)

    def include_rect(self, rect: Rect) -> None:
        self.bounds_points.extend(
            (
                Point(rect.x, rect.y),
                Point(rect.right, rect.y),
                Point(rect.right, rect.bottom),
                Point(rect.x, rect.bottom),
            )
        )


@dataclass
class IntegratedStructureCalculator(StructureCalculator):
    """Build the full physical chain represented by the ABCD calculation.

    Every blue trapezoid corresponds to one call to
    ``ImpedanceTransformerCalculator.transformer_matrix``.  Straight sections
    correspond to ``MicrostripLineCalculator.matrix`` calls.  Matrix group
    frames therefore explain the calculation rather than decorating an
    unrelated conceptual picture.
    """

    def calculate(self, config: S21Config) -> StructureGeometry:
        """Return schematic geometry in the orientation of the reference.

        Width correction ``DW`` is added wherever the S21 calculator adds it.
        The seven transformers are drawn in reverse physical direction because
        the reference runs from the FFO side (Mex01) toward the radial/SIS
        matching section, whereas ``m_total`` is multiplied from ``Mex4``
        toward ``Mex1``.
        """
        canvas = _Canvas()
        center_y = 185.0
        frame_top = 35.0
        frame_bottom = 325.0
        dw_um = config.dw_m * 1e6
        x = 28.0

        # Start at the first taper. The far-left flange/partial feed in the
        # supplied structure_clean.svg is explicitly outside this schematic.
        input_width = max(8.0, min(126.0, (config.transf_7_w_end_m * 1e6 + dw_um) * WIDTH_SCALE))
        canvas.labels.append(TextLabel(Point(x, center_y + 80.0), "ФФО", font_size=12.0))

        mex1_start = x
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_7_w_end_m,
            config.transf_7_w_start_m,
            config.transf_7_dwdl_um,
            config.transf_7_dl_m,
            dw_um,
            "T7",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_8_len_m, config.msl_8_width_m, dw_um, "MSL8")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_6_w_end_m,
            config.transf_6_w_start_m,
            config.transf_6_dwdl_um,
            config.transf_6_dl_m,
            dw_um,
            "T6",
        )
        self._add_group(canvas, mex1_start, x, frame_top, frame_bottom, "Mex01", title_side="left")

        mex2_start = x
        x = self._add_microstrip(canvas, x, center_y, config.msl_7_len_m, config.msl_7_width_m, dw_um, "MSL7")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_5_w_end_m,
            config.transf_5_w_start_m,
            config.transf_5_dwdl_um,
            config.transf_5_dl_m,
            dw_um,
            "T5",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_6_len_m, config.msl_6_width_m, dw_um, "MSL6")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_4_w_end_m,
            config.transf_4_w_start_m,
            config.transf_4_dwdl_um,
            config.transf_4_dl_m,
            dw_um,
            "T4",
        )
        self._add_group(canvas, mex2_start, x, frame_top + 14.0, frame_bottom - 14.0, "Mex02", title_side="left")

        dcb_start = x
        x = self._add_dc_block(canvas, config, x, center_y, dw_um)
        self._add_group(canvas, dcb_start, x, frame_top + 28.0, frame_bottom - 28.0, "Mdcb", title_side="left")

        mex3_start = x
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_3_w_end_m,
            config.transf_3_w_start_m,
            config.transf_3_dwdl_um,
            config.transf_3_dl_m,
            dw_um,
            "T3",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_5_len_m, config.msl_5_width_m, dw_um, "MSL5")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_2_w_end_m,
            config.transf_2_w_start_m,
            config.transf_2_dwdl_um,
            config.transf_2_dl_m,
            dw_um,
            "T2",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_4_len_m, config.msl_4_width_m, dw_um, "MSL4")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_1_w_end_m,
            config.transf_1_w_start_m,
            config.transf_1_dwdl_um,
            config.transf_1_dl_m,
            dw_um,
            "T1",
        )
        self._add_group(canvas, mex3_start, x, frame_top + 14.0, frame_bottom - 14.0, "Mex03", title_side="left")

        x = self._add_radial_and_source(canvas, config, x, center_y, dw_um, frame_top, frame_bottom)
        canvas.labels.append(
            TextLabel(Point(x - 34.0, center_y - 30.0), "50 Ω", font_size=11.0, anchor="middle", font_weight="bold")
        )
        canvas.labels.append(
            TextLabel(
                Point(28.0, 14.0),
                "Структура HD35 · нумерация Mathcad · схема не в масштабе",
                font_size=13.0,
                font_weight="bold",
            )
        )

        canvas.bounds_points.append(Point(28.0, -3.0))
        overview = self._snapshot(canvas)
        legend_top = max(point.y for point in canvas.bounds_points) + 32.0
        self._add_parameter_register(canvas, config, dw_um, 28.0, max(x, 1128.0), legend_top)
        return replace(self._snapshot(canvas), overview=overview)

    @staticmethod
    def _snapshot(canvas: _Canvas) -> StructureGeometry:
        """Freeze separate overview/detail lists so the legend cannot shrink the overview."""
        bounds = bounds_from_points(canvas.bounds_points)
        margin = 22.0
        return StructureGeometry(
            polygons=list(canvas.polygons),
            paths=list(canvas.paths),
            rects=list(canvas.rects),
            circles=list(canvas.circles),
            lines=list(canvas.lines),
            labels=list(canvas.labels),
            dimensions=list(canvas.dimensions),
            groups=list(canvas.groups),
            bounds=Rect(
                bounds.x - margin,
                bounds.y - margin,
                bounds.width + margin * 2.0,
                bounds.height + margin * 2.0,
            ),
        )

    def _add_transformer(
        self,
        canvas: _Canvas,
        x: float,
        center_y: float,
        start_width_m: float,
        end_width_m: float,
        width_step_um: float,
        length_step_m: float,
        dw_um: float,
        label: str,
    ) -> float:
        """Draw one stepped transformer as its continuous trapezoid envelope.

        The backend creates ``N`` microstrip slices with

        ``N = floor(abs(W_end - W_start) / dW) + 1``

        and gives every slice the configured longitudinal step ``dL``.
        Consequently the physical transformer length is ``L = N * dL``.  The
        legend uses precisely that formula. The schematic clamps visual
        lengths to keep short sections identifiable; it is not a mask layout.
        """
        start_um = start_width_m * 1e6 + dw_um
        end_um = end_width_m * 1e6 + dw_um
        physical_length_um = self._transformer_physical_length_um(
            start_width_m,
            end_width_m,
            width_step_um,
            length_step_m,
        )
        visual_length = max(MIN_SEGMENT_LENGTH, min(150.0, physical_length_um * LENGTH_SCALE))
        start_height = max(8.0, min(126.0, start_um * WIDTH_SCALE))
        end_height = max(8.0, min(126.0, end_um * WIDTH_SCALE))
        points = [
            Point(x, center_y - start_height / 2.0),
            Point(x + visual_length, center_y - end_height / 2.0),
            Point(x + visual_length, center_y + end_height / 2.0),
            Point(x, center_y + start_height / 2.0),
        ]
        canvas.polygons.append(PolygonShape(points, fill=TRANSFORMER_FILL))
        canvas.bounds_points.extend(points)
        self._add_callout(canvas, label, x + visual_length / 2.0, center_y - (start_height + end_height) / 4.0)
        return x + visual_length

    def _add_microstrip(
        self,
        canvas: _Canvas,
        x: float,
        center_y: float,
        length_m: float,
        width_m: float,
        dw_um: float,
        label: str,
    ) -> float:
        """Draw an MSL section using ``L`` and the corrected width ``W + DW``."""
        length_um = length_m * 1e6
        width_um = width_m * 1e6 + dw_um
        visual_length = max(78.0, min(180.0, length_um * LENGTH_SCALE))
        visual_width = max(8.0, min(126.0, width_um * WIDTH_SCALE))
        rect = Rect(x, center_y - visual_width / 2.0, visual_length, visual_width)
        canvas.rects.append(RectShape(rect, fill=CONDUCTOR_FILL))
        canvas.include_rect(rect)
        self._add_callout(canvas, label, x + visual_length / 2.0, rect.y)
        return rect.right

    def _add_callout(self, canvas: _Canvas, element: str, x: float, edge_y: float) -> None:
        """Connect each local number to exactly one section, clear of the metal."""
        if element not in REFERENCE_NUMBERS:
            return
        y = 98.0
        canvas.labels.append(
            TextLabel(Point(x, y), str(REFERENCE_NUMBERS[element]), font_size=14.0, anchor="middle", font_weight="bold")
        )
        canvas.lines.append(LineShape(Point(x, y + 6.0), Point(x, edge_y - 4.0), stroke="#64748b"))
        canvas.circles.append(CircleShape(Point(x, edge_y - 3.0), radius=1.5, fill="#64748b", stroke="#64748b"))

    def _add_dc_block(self, canvas: _Canvas, config: S21Config, x: float, center_y: float, dw_um: float) -> float:
        """Opposed downward electrodes as in Mathcad's embedded HD35 drawing.

        This is a topology schematic, not a fabrication mask. The two metal
        polygons remain disjoint; the slot is not a third metal component.
        Actual dimensions and the Wslot-DW correction are reported below.
        """
        gap = max(9.0, min(24.0, (config.w_slot_m * 1e6 - dw_um) * WIDTH_SCALE))
        feed_h = max(10.0, min(30.0, (config.w_ms_m * 1e6 + dw_um) * WIDTH_SCALE))
        finger = 18.0
        shoulder = 18.0
        length = max(75.0, min(104.0, config.l_slot_m * 1e6 * WIDTH_SCALE))
        top, bottom = center_y - feed_h / 2.0, center_y + feed_h / 2.0
        inner = x + shoulder + finger
        end = inner + gap + finger + shoulder
        left = [
            Point(x, top),
            Point(inner - 8.0, top),
            Point(inner, bottom),
            Point(inner, bottom + length),
            Point(inner - finger, bottom + length),
            Point(inner - finger, bottom),
            Point(x, bottom),
        ]
        right = [
            Point(end, top),
            Point(inner + gap + 8.0, top),
            Point(inner + gap, bottom),
            Point(inner + gap, bottom + length),
            Point(inner + gap + finger, bottom + length),
            Point(inner + gap + finger, bottom),
            Point(end, bottom),
        ]
        canvas.polygons.extend((PolygonShape(left, fill=DC_FILL), PolygonShape(right, fill=DC_FILL)))
        canvas.bounds_points.extend((*left, *right))
        # Separate lateral leads are visible in the reference; they do not
        # bridge the central gap and are schematic, without invented sizes.
        for start, outside in ((inner - finger, x - 8.0), (inner + gap + finger, end + 8.0)):
            y = bottom + 20.0
            canvas.lines.extend(
                (
                    LineShape(Point(start, y), Point(outside, y), stroke_width=2.5),
                    LineShape(Point(outside, y), Point(outside, bottom + length + 10), stroke_width=2.5),
                )
            )
        slot_x = inner + gap / 2.0
        canvas.dimensions.append(
            self._dim(
                Point(inner, bottom + length + 15),
                Point(inner + gap, bottom + length + 15),
                "Wslot",
                Point(slot_x, bottom + length + 30),
            )
        )
        canvas.dimensions.append(
            self._dim(
                Point(slot_x, bottom),
                Point(slot_x, bottom + length),
                "Lslot",
                Point(slot_x + 4, bottom + length / 2),
                label_rotation_deg=-90,
            )
        )
        canvas.bounds_points.append(Point(slot_x, bottom + length + 30))
        return end

    def _add_radial_and_source(
        self,
        canvas: _Canvas,
        config: S21Config,
        x: float,
        center_y: float,
        dw_um: float,
        frame_top: float,
        frame_bottom: float,
    ) -> float:
        """Place MLsis/SIS before the radial neck, as in PNG item 587.

        Mrad is the shunt equivalent of the radial/filter branch, not a series
        cascade of additional numbered transformers. Its 50-ohm termination
        is drawn beyond the two radial sectors, outside the Mex04 frame.
        """
        start = x
        # Coordinates are taken from the user's clean SVG, whose SIS circle
        # is (1037,276). Scale the footprint but retain its asymmetric curved
        # rims, inclined sides and stepped neck; do not use annular wedges.
        radius = max(72.0, min(88.0, config.radial_r_max_m * 1e6 * WIDTH_SCALE))
        sy = radius / 138.0
        sx = sy * sin(radians(config.radial_angle_deg / 2.0)) / sin(radians(113.0 / 2.0))
        sx = max(0.5, min(0.9, sx))
        h = max(10.0, min(20.0, (config.mex4_width_m * 1e6 + dw_um) * WIDTH_SCALE))

        def point(rx: float, ry: float) -> Point:
            # Keep the thin neck legible even when the fan is small.
            dy = ry - 276.0
            y = center_y + (dy * h / 18.0 if abs(dy) <= 14.0 else dy * sy)
            return Point(start + (rx - 1023.0) * sx, y)

        def path(element_id: str, commands: list[tuple[str, tuple[float, ...]]]) -> None:
            parts = []
            points = []
            for command, coordinates in commands:
                mapped = [point(*coordinates[i : i + 2]) for i in range(0, len(coordinates), 2)]
                parts.append(command + " ".join(f"{p.x:g},{p.y:g}" for p in mapped))
                points.extend(mapped)
            bounds = bounds_from_points(points)
            canvas.paths.append(PathShape(" ".join(parts), bounds, element_id))
            canvas.include_rect(bounds)

        path("radial-upper", [("M", (1067, 266)), ("L", (976, 166)), ("Q", (1059, 106, 1147, 170)), ("L", (1074, 265))])
        path("radial-lower", [("M", (1067, 284)), ("L", (975, 386)), ("Q", (1059, 465, 1148, 381)), ("L", (1074, 289))])
        path("sis-feed", [("M", (1023, 266)), ("L", (1067, 266)), ("M", (1023, 284)), ("L", (1067, 284))])
        # Upper and lower stepped contours from the reference, extended to
        # the current output-line length without adding an inner circular arc.
        neck = point(1074, 276).x
        output_start = point(1079, 276).x
        output_end = output_start + max(104.0, min(180.0, config.zrad1_len_m * 1e6 * LENGTH_SCALE))
        rx_end = 1023.0 + (output_end - start) / sx
        path(
            "radial-output",
            [
                ("M", (1074, 265)),
                ("L", (1074, 267)),
                ("L", (1079, 267)),
                ("L", (1079, 270)),
                ("L", (rx_end, 270)),
                ("M", (rx_end, 283)),
                ("L", (1074, 283)),
                ("L", (1074, 289)),
                ("M", (1079, 270)),
                ("L", (1079, 283)),
            ],
        )
        sis = point(1037, 276)
        sis_top = point(1023, 266)
        sis_bottom = point(1049, 284)
        canvas.rects.append(
            RectShape(
                Rect(sis_top.x, sis_top.y, sis_bottom.x - sis_top.x, sis_bottom.y - sis_top.y),
                fill="#ffffff",
                stroke_width=1.2,
            )
        )
        canvas.circles.append(CircleShape(sis, radius=5.0 * sy, fill="#fff"))
        canvas.labels.append(TextLabel(Point(start - 38, center_y + 49), "SIS", font_size=12.0, anchor="end"))
        canvas.lines.append(
            LineShape(Point(sis.x, sis_bottom.y + 3), Point(start - 34, center_y + 40), stroke="#64748b")
        )
        canvas.labels.append(
            TextLabel(Point(neck + 12, center_y + radius + 35), "Радиальные шлейфы ×2", font_size=12.0, anchor="middle")
        )
        self._add_group(canvas, start - 10, output_end, frame_top + 26, frame_bottom - 18, "Mrad", "left")
        self._add_group(canvas, start, sis_bottom.x + 2, center_y - 23, center_y + 15, "MLsis", "left")
        # Give MLsis its own leader/title lane instead of squeezing the title
        # into a short metal section or placing it on the output line.
        group = canvas.groups[-1]
        canvas.groups[-1] = GroupBoxShape(group.rect, "MLsis", Point(start + 18, 92.0), 0.0)
        canvas.lines.append(LineShape(Point(start + 18, 99.0), Point(sis.x, center_y - 24), stroke="#64748b"))
        self._add_group(canvas, start - 18, output_end + 8, frame_top, frame_bottom, "Mex04", "right")
        port_height = 32.0
        pts = [
            Point(output_end, point(rx_end, 270).y),
            Point(output_end + 26, center_y - port_height / 2),
            Point(output_end + 26, center_y + port_height / 2),
            Point(output_end, point(rx_end, 283).y),
        ]
        canvas.polygons.append(PolygonShape(pts, fill="#f8fafc"))
        rect = Rect(output_end + 26, center_y - port_height / 2, 44, port_height)
        canvas.rects.append(RectShape(rect, fill="#f8fafc"))
        canvas.include_rect(rect)
        return rect.right

    def _add_parameter_register(
        self,
        canvas: _Canvas,
        config: S21Config,
        dw_um: float,
        left: float,
        right: float,
        top: float,
    ) -> None:
        """Readable local-number legend below the drawing, with live sizes.

        Numbers are scoped to Mex01/Mex02/Mex03; T/MSL names are the app's
        identifiers, not names claimed to exist in the Mathcad worksheet.
        """
        panel = Rect(left, top, right - left, 270.0)
        canvas.rects.append(RectShape(panel, fill="#ffffff", stroke="#94a3b8", stroke_width=0.7))
        canvas.include_rect(panel)
        canvas.labels.append(
            TextLabel(
                Point(left + 12, top + 20),
                "Обозначения и размеры · µm · Wэфф = W + DW · направление W: от ФФО вправо",
                font_size=13.0,
                font_weight="bold",
            )
        )
        width = panel.width / 3
        for column, (matrix, sections) in enumerate(REFERENCE_SECTIONS.items()):
            lx = left + column * width + 12
            canvas.labels.append(TextLabel(Point(lx, top + 46), matrix, font_size=14.0, font_weight="bold"))
            for row, (number, element) in enumerate(sections):
                y = top + 67 + row * 21
                if element.startswith("T"):
                    i = int(element[1:])
                    w1 = getattr(config, f"transf_{i}_w_start_m")
                    w2 = getattr(config, f"transf_{i}_w_end_m")
                    step = getattr(config, f"transf_{i}_dwdl_um")
                    dl = getattr(config, f"transf_{i}_dl_m")
                    length = self._transformer_physical_length_um(w1, w2, step, dl)
                    detail = f"{element} · переход · W {w2 * 1e6:g}→{w1 * 1e6:g}; L {length:g}"
                else:
                    i = int(element[3:])
                    w = getattr(config, f"msl_{i}_width_m") * 1e6
                    length = getattr(config, f"msl_{i}_len_m") * 1e6
                    detail = f"{element} · линия · W {w:g}; L {length:g}"
                canvas.labels.append(TextLabel(Point(lx, y), f"{number}  —  {detail}", font_size=12.0))
        y = top + 173
        canvas.lines.append(LineShape(Point(left + 12, y), Point(right - 12, y), stroke="#cbd5e1"))
        explanations = (
            f"Mdcb · DC-развязка: щелевая антенна; Wslot={config.w_slot_m * 1e6:g}; Wэфф={config.w_slot_m * 1e6 - dw_um:g}; Lslot={config.l_slot_m * 1e6:g}; Lso={config.lso_m * 1e6:g}",
            f"MS-шлейф: W={config.w_ms_m * 1e6:g}; L={config.l_ms_m * 1e6:g}.  Mrad · радиальный фильтр: R={config.radial_r_min_m * 1e6:g}…{config.radial_r_max_m * 1e6:g}; угол {config.radial_angle_deg:g}°",
            f"MLsis · линия у SIS: W={config.mex4_width_m * 1e6:g}; L={config.mex4_len_m * 1e6:g}.  SIS · туннельный переход.  DW={dw_um:g}",
            "Цифры повторяются внутри каждой Mex. T — трансформатор, MSL — микрополосковая линия. Размеры — текущие параметры приложения.",
        )
        for row, text in enumerate(explanations):
            canvas.labels.append(TextLabel(Point(left + 12, y + 21 + row * 21), text, font_size=12.0, fill="#334155"))

    def _add_group(
        self,
        canvas: _Canvas,
        start_x: float,
        end_x: float,
        top: float,
        bottom: float,
        title: str,
        title_side: str,
    ) -> None:
        """Add a dotted ABCD matrix boundary like the supplied sketch."""
        padding = 5.0
        rect = Rect(start_x - padding, top, end_x - start_x + padding * 2.0, bottom - top)
        # Nested matrix frames already occupy different vertical levels.
        # A horizontal title centred on each top edge is readable without
        # crossing the physical chain or its size callouts.
        title_position = Point(rect.x + rect.width / 2.0, rect.y + 13.0)
        rotation = 0.0
        group = GroupBoxShape(rect=rect, title=title, title_position=title_position, title_rotation_deg=rotation)
        canvas.groups.append(group)
        canvas.include_rect(rect)

    def _transformer_physical_length_um(
        self,
        start_width_m: float,
        end_width_m: float,
        width_step_um: float,
        length_step_m: float,
    ) -> float:
        """Mirror the backend's inclusive ``arange`` transformer length.

        ``width_step_um`` is the change in width between adjacent slices and
        ``length_step_m`` is the longitudinal length of every slice.  The
        inclusive endpoint creates one more slice when the width difference is
        exactly divisible by the width step.
        """
        delta_width_um = abs(end_width_m - start_width_m) * 1e6
        slice_count = floor(delta_width_um / max(width_step_um, 1e-12)) + 1
        return slice_count * length_step_m * 1e6

    def _dim(
        self,
        start: Point,
        end: Point,
        label: str,
        label_pos: Point,
        label_rotation_deg: float = 0.0,
    ) -> DimensionLine:
        return DimensionLine(
            start=start,
            end=end,
            label=label,
            label_pos=label_pos,
            label_rotation_deg=label_rotation_deg,
        )

    def _rect_points(self, rect: Rect) -> Iterable[Point]:
        """Return rectangle corners for tests and future interactive overlays."""
        return (
            Point(rect.x, rect.y),
            Point(rect.right, rect.y),
            Point(rect.right, rect.bottom),
            Point(rect.x, rect.bottom),
        )
