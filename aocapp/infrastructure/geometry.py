"""Geometry calculator for the complete S21 network schematic.

The preview is deliberately derived from the same :class:`S21Config` fields
as ``S21CalculatorImpl``.  Its left-to-right order follows the supplied
engineering sketch (load to source), which is the reverse of the matrix
multiplication order used by the calculator::

    drawing:      Mex01 -> Mex02 -> Mdcb -> Mex03 -> Mex04 -> 50 Ohm
    calculation:  Mex4  -> Mex3  -> Mdcb -> Mex2  -> Mex1

Reversing the visual order does not change the formulas; it only presents the
physical chain in the orientation used by the reference drawing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, floor, radians, sin
from typing import Iterable

from aocapp.domain.models import (
    CircleShape,
    DimensionLine,
    GroupBoxShape,
    LineShape,
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
MIN_SEGMENT_LENGTH = 9.0
CONDUCTOR_FILL = "#e8f1f5"
TRANSFORMER_FILL = "#dbeafe"
RADIAL_FILL = "#fde68a"
DC_FILL = "#d7edf5"


@dataclass
class _Canvas:
    """Mutable collector used only while assembling an immutable geometry."""

    polygons: list[PolygonShape] = field(default_factory=list)
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
        the reference runs from the SIS/load side (Mex01) to the 50 Ohm source,
        whereas ``m_total`` is multiplied from ``Mex4`` toward ``Mex1``.
        """
        canvas = _Canvas()
        center_y = 185.0
        frame_top = 35.0
        frame_bottom = 335.0
        dw_um = config.dw_m * 1e6
        x = 28.0

        # A short continuation makes the load-side boundary explicit without
        # inventing another matrix element outside Mex01.
        input_width = (config.transf_7_w_end_m * 1e6 + dw_um) * WIDTH_SCALE
        input_rect = Rect(x, center_y - input_width / 2.0, 20.0, input_width)
        canvas.rects.append(RectShape(input_rect, fill=CONDUCTOR_FILL))
        canvas.include_rect(input_rect)
        canvas.labels.append(TextLabel(Point(x, center_y - input_width / 2.0 - 10.0), "SIS/load", font_size=8.0))
        x = input_rect.right

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
            "3 · T7",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_8_len_m, config.msl_8_width_m, dw_um, "2 · MSL8")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_6_w_end_m,
            config.transf_6_w_start_m,
            config.transf_6_dwdl_um,
            config.transf_6_dl_m,
            dw_um,
            "1 · T6",
        )
        self._add_group(canvas, mex1_start, x, frame_top, frame_bottom, "Mex01", title_side="left")

        mex2_start = x
        x = self._add_microstrip(canvas, x, center_y, config.msl_7_len_m, config.msl_7_width_m, dw_um, "4 · MSL7")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_5_w_end_m,
            config.transf_5_w_start_m,
            config.transf_5_dwdl_um,
            config.transf_5_dl_m,
            dw_um,
            "3 · T5",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_6_len_m, config.msl_6_width_m, dw_um, "2 · MSL6")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_4_w_end_m,
            config.transf_4_w_start_m,
            config.transf_4_dwdl_um,
            config.transf_4_dl_m,
            dw_um,
            "1 · T4",
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
            "5 · T3",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_5_len_m, config.msl_5_width_m, dw_um, "4 · MSL5")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_2_w_end_m,
            config.transf_2_w_start_m,
            config.transf_2_dwdl_um,
            config.transf_2_dl_m,
            dw_um,
            "3 · T2",
        )
        x = self._add_microstrip(canvas, x, center_y, config.msl_4_len_m, config.msl_4_width_m, dw_um, "2 · MSL4")
        x = self._add_transformer(
            canvas,
            x,
            center_y,
            config.transf_1_w_end_m,
            config.transf_1_w_start_m,
            config.transf_1_dwdl_um,
            config.transf_1_dl_m,
            dw_um,
            "1 · T1",
        )
        self._add_group(canvas, mex3_start, x, frame_top + 14.0, frame_bottom - 14.0, "Mex03", title_side="left")

        x = self._add_radial_and_source(canvas, config, x, center_y, dw_um, frame_top, frame_bottom)
        canvas.labels.append(
            TextLabel(Point(x - 34.0, center_y - 30.0), "50 Ω", font_size=11.0, anchor="middle", font_weight="bold")
        )

        bounds = bounds_from_points(canvas.bounds_points)
        margin = 22.0
        return StructureGeometry(
            polygons=canvas.polygons,
            rects=canvas.rects,
            circles=canvas.circles,
            lines=canvas.lines,
            labels=canvas.labels,
            dimensions=canvas.dimensions,
            groups=canvas.groups,
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
        preview uses precisely that formula and only applies a constant visual
        scale afterwards.
        """
        start_um = start_width_m * 1e6 + dw_um
        end_um = end_width_m * 1e6 + dw_um
        physical_length_um = self._transformer_physical_length_um(
            start_width_m,
            end_width_m,
            width_step_um,
            length_step_m,
        )
        visual_length = max(MIN_SEGMENT_LENGTH, physical_length_um * LENGTH_SCALE)
        start_height = max(3.0, start_um * WIDTH_SCALE)
        end_height = max(3.0, end_um * WIDTH_SCALE)
        points = [
            Point(x, center_y - start_height / 2.0),
            Point(x + visual_length, center_y - end_height / 2.0),
            Point(x + visual_length, center_y + end_height / 2.0),
            Point(x, center_y + start_height / 2.0),
        ]
        canvas.polygons.append(PolygonShape(points, fill=TRANSFORMER_FILL))
        canvas.bounds_points.extend(points)
        self._add_segment_caption(canvas, x, x + visual_length, center_y, max(start_height, end_height), label)
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
        visual_length = max(MIN_SEGMENT_LENGTH, length_um * LENGTH_SCALE)
        visual_width = max(3.0, width_um * WIDTH_SCALE)
        rect = Rect(x, center_y - visual_width / 2.0, visual_length, visual_width)
        canvas.rects.append(RectShape(rect, fill=CONDUCTOR_FILL))
        canvas.include_rect(rect)
        self._add_segment_caption(canvas, x, rect.right, center_y, visual_width, label)
        return rect.right

    def _add_segment_caption(
        self,
        canvas: _Canvas,
        start_x: float,
        end_x: float,
        center_y: float,
        height: float,
        text: str,
    ) -> None:
        """Place the numbered matrix-element caption used in the sketch."""
        if not text:
            return
        # The supplied sketch numbers individual matrices and explains names
        # outside the drawing.  Keeping only that number prevents short T/MSL
        # sections from producing unreadable overlapping captions.
        display_text = text.split("·", maxsplit=1)[0].strip()
        position = Point((start_x + end_x) / 2.0, center_y - height / 2.0 - 18.0)
        leader_end = Point(position.x, center_y - height / 2.0 - 3.0)
        canvas.labels.append(TextLabel(position, display_text, font_size=9.0, anchor="middle", font_weight="bold"))
        canvas.lines.append(
            LineShape(Point(position.x, position.y + 3.0), leader_end, stroke="#374151", stroke_width=0.6)
        )
        canvas.bounds_points.append(position)
        canvas.bounds_points.append(leader_end)

    def _add_dc_block(self, canvas: _Canvas, config: S21Config, x: float, center_y: float, dw_um: float) -> float:
        """Draw the symmetric slot-coupled DC block used by ``DCBlockCalculator``.

        ``Wslot`` is corrected as ``Wslot - DW`` and ``Wms`` as ``Wms + DW``,
        exactly as in ``S21CalculatorImpl``.  The two vertical plates represent
        the symmetric series bridge terms; the open U-shaped conductors below
        represent the two coupled slot/dipole shunt branches.
        """
        slot_width_um = max(0.1, config.w_slot_m * 1e6 - dw_um)
        slot_length_um = config.l_slot_m * 1e6
        microstrip_width_um = config.w_ms_m * 1e6 + dw_um
        microstrip_length_um = config.l_ms_m * 1e6

        feed_length = max(22.0, microstrip_length_um * LENGTH_SCALE)
        feed_height = max(4.0, microstrip_width_um * WIDTH_SCALE)
        gap = max(7.0, slot_width_um * WIDTH_SCALE)
        plate_width = max(5.0, feed_height * 0.42)
        plate_height = max(62.0, slot_length_um * WIDTH_SCALE)

        left_feed = Rect(x, center_y - feed_height / 2.0, feed_length, feed_height)
        left_plate = Rect(left_feed.right, center_y - plate_height / 2.0, plate_width, plate_height)
        right_plate = Rect(left_plate.right + gap, center_y - plate_height / 2.0, plate_width, plate_height)
        right_feed = Rect(right_plate.right, center_y - feed_height / 2.0, feed_length, feed_height)
        for rect in (left_feed, left_plate, right_plate, right_feed):
            canvas.rects.append(RectShape(rect, fill=DC_FILL))
            canvas.include_rect(rect)

        # Slot/dipole coupling is drawn as two open U branches.  It is not an
        # electrical shortcut across the DC gap: the branches remain separate.
        branch_bottom = center_y + plate_height / 2.0 + 42.0
        left_outer = left_plate.x - 18.0
        right_outer = right_plate.right + 18.0
        branch_lines = (
            LineShape(Point(left_outer, center_y), Point(left_outer, branch_bottom), stroke_width=2.6),
            LineShape(Point(left_outer, branch_bottom), Point(left_plate.right, branch_bottom), stroke_width=2.6),
            LineShape(Point(right_outer, center_y), Point(right_outer, branch_bottom), stroke_width=2.6),
            LineShape(Point(right_plate.x, branch_bottom), Point(right_outer, branch_bottom), stroke_width=2.6),
        )
        canvas.lines.extend(branch_lines)
        for line in branch_lines:
            canvas.bounds_points.extend((line.start, line.end))

        slot_center_x = (left_plate.right + right_plate.x) / 2.0
        canvas.dimensions.extend(
            (
                self._dim(
                    Point(left_plate.right, center_y - plate_height / 2.0 - 13.0),
                    Point(right_plate.x, center_y - plate_height / 2.0 - 13.0),
                    f"Wslot={slot_width_um:g} µm",
                    Point(slot_center_x, center_y - plate_height / 2.0 - 19.0),
                ),
                self._dim(
                    Point(left_plate.x - 10.0, center_y - plate_height / 2.0),
                    Point(left_plate.x - 10.0, center_y + plate_height / 2.0),
                    f"Lslot={slot_length_um:g} µm",
                    Point(slot_center_x, center_y + plate_height / 2.0 + 18.0),
                ),
            )
        )
        for dimension in canvas.dimensions[-2:]:
            canvas.bounds_points.extend((dimension.start, dimension.end, dimension.label_pos))
        return right_feed.right

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
        """Draw Mex04, the radial shunt network, MLsis and the 50 Ohm port.

        The radial branch is the parallel admittance

        ``Zrad2 = 1 / (2*Yrad + 1/Zrad1)``.

        Two fan sectors are therefore drawn symmetrically around the feed line.
        The following ``Zrad3``/``Zrad4`` and ``Mex4`` microstrips mirror the
        successive impedance transforms in ``S21CalculatorImpl``.
        """
        mex4_start = x
        feed_width_um = config.zrad1_width_m * 1e6 + dw_um
        feed_height = max(3.0, feed_width_um * WIDTH_SCALE)
        feed_length = max(28.0, config.zrad1_len_m * 1e6 * LENGTH_SCALE)
        feed = Rect(x, center_y - feed_height / 2.0, feed_length, feed_height)
        canvas.rects.append(RectShape(feed, fill=CONDUCTOR_FILL))
        canvas.include_rect(feed)
        stub_center = Point(feed.right, center_y)

        r_min = config.radial_r_min_m * 1e6 * WIDTH_SCALE
        r_max = config.radial_r_max_m * 1e6 * WIDTH_SCALE
        top_lobe = self._fan_lobe_points(stub_center, r_min, r_max, config.radial_angle_deg, upward=True)
        bottom_lobe = self._fan_lobe_points(stub_center, r_min, r_max, config.radial_angle_deg, upward=False)
        canvas.polygons.extend(
            (
                PolygonShape(top_lobe, fill=RADIAL_FILL),
                PolygonShape(bottom_lobe, fill=RADIAL_FILL),
            )
        )
        canvas.bounds_points.extend((*top_lobe, *bottom_lobe))
        canvas.circles.append(CircleShape(stub_center, radius=3.0, fill="#ffffff"))
        canvas.bounds_points.extend((Point(stub_center.x - 3.0, center_y), Point(stub_center.x + 3.0, center_y)))

        x = feed.right
        radial_start = mex4_start
        x = self._add_microstrip(canvas, x, center_y, config.zrad3_len_m, config.zrad3_width_m, dw_um, "")
        x = self._add_microstrip(canvas, x, center_y, config.zrad4_len_m, config.zrad4_width_m, dw_um, "")
        mlsis_start = x
        x = self._add_microstrip(canvas, x, center_y, config.mex4_len_m, config.mex4_width_m, dw_um, "")
        mlsis_end = x

        # The 50 Ohm source is a port boundary, not an eighth calculated
        # transformer.  A neutral outline distinguishes it from blue T1..T7.
        port_height = max(18.0, feed_height * 3.2)
        port_taper_length = 28.0
        port_points = [
            Point(x, center_y - feed_height / 2.0),
            Point(x + port_taper_length, center_y - port_height / 2.0),
            Point(x + port_taper_length, center_y + port_height / 2.0),
            Point(x, center_y + feed_height / 2.0),
        ]
        canvas.polygons.append(PolygonShape(port_points, fill="#f8fafc", stroke="#374151"))
        canvas.bounds_points.extend(port_points)
        x += port_taper_length
        port_line = Rect(x, center_y - port_height / 2.0, 52.0, port_height)
        canvas.rects.append(RectShape(port_line, fill="#f8fafc", stroke="#374151"))
        canvas.include_rect(port_line)
        x = port_line.right

        self._add_group(
            canvas, radial_start, mlsis_start, frame_top + 8.0, frame_bottom - 8.0, "Mrad", title_side="left"
        )
        self._add_group(
            canvas,
            mlsis_start,
            mlsis_end,
            frame_top + 34.0,
            frame_bottom - 34.0,
            "MLsis",
            title_side="left",
        )
        self._add_group(
            canvas,
            mex4_start,
            x,
            frame_top - 8.0,
            frame_bottom + 8.0,
            "Mex04",
            title_side="right",
        )

        feed_dimension = self._dim(
            Point(feed.x, center_y - feed_height / 2.0 - 18.0),
            Point(feed.right, center_y - feed_height / 2.0 - 18.0),
            f"{config.zrad1_len_m * 1e6:g} µm",
            Point((feed.x + feed.right) / 2.0, center_y - feed_height / 2.0 - 24.0),
        )
        radius_dimension = self._dim(
            Point(stub_center.x + r_min, center_y + r_max + 10.0),
            Point(stub_center.x + r_max, center_y + r_max + 10.0),
            f"R={config.radial_r_min_m * 1e6:g}…{config.radial_r_max_m * 1e6:g} µm",
            Point(stub_center.x + (r_min + r_max) / 2.0, center_y + r_max + 5.0),
        )
        canvas.dimensions.extend((feed_dimension, radius_dimension))
        for dimension in (feed_dimension, radius_dimension):
            canvas.bounds_points.extend((dimension.start, dimension.end, dimension.label_pos))
        return x

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
        if title_side == "right":
            title_position = Point(rect.right - 8.0, rect.y + 56.0)
            rotation = -90.0
        elif title_side == "top":
            title_position = Point(rect.x + rect.width / 2.0, rect.y + 14.0)
            rotation = 0.0
        else:
            title_position = Point(rect.x + 13.0, rect.y + 56.0)
            rotation = -90.0
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

    def _fan_lobe_points(
        self,
        center: Point,
        r_min: float,
        r_max: float,
        angle_deg: float,
        upward: bool,
    ) -> list[Point]:
        """Approximate an annular sector while preserving ``Rmin/Rmax/angle``."""
        center_angle = -90.0 if upward else 90.0
        start = center_angle - angle_deg / 2.0
        stop = center_angle + angle_deg / 2.0
        segments = max(12, int(angle_deg / 5.0))
        step = angle_deg / segments
        outer = [
            Point(
                center.x + r_max * cos(radians(start + index * step)),
                center.y + r_max * sin(radians(start + index * step)),
            )
            for index in range(segments + 1)
        ]
        inner = [
            Point(
                center.x + r_min * cos(radians(stop - index * step)),
                center.y + r_min * sin(radians(stop - index * step)),
            )
            for index in range(segments + 1)
        ]
        return outer + inner

    def _dim(self, start: Point, end: Point, label: str, label_pos: Point) -> DimensionLine:
        return DimensionLine(start=start, end=end, label=label, label_pos=label_pos)

    def _rect_points(self, rect: Rect) -> Iterable[Point]:
        """Return rectangle corners for tests and future interactive overlays."""
        return (
            Point(rect.x, rect.y),
            Point(rect.right, rect.y),
            Point(rect.right, rect.bottom),
            Point(rect.x, rect.bottom),
        )
