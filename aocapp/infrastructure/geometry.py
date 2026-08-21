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
    caption_count: int = 0

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
        frame_bottom = 335.0
        dw_um = config.dw_m * 1e6
        x = 28.0

        # A short continuation makes the load-side boundary explicit without
        # inventing another matrix element outside Mex01.
        input_width = (config.transf_7_w_end_m * 1e6 + dw_um) * WIDTH_SCALE
        input_rect = Rect(x, center_y - input_width / 2.0, 20.0, input_width)
        canvas.rects.append(RectShape(input_rect, fill=CONDUCTOR_FILL))
        canvas.include_rect(input_rect)
        canvas.labels.append(TextLabel(Point(x, center_y - input_width / 2.0 - 10.0), "ФФО", font_size=8.0))
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
        self._add_parameter_register(canvas, config, dw_um, x + 30.0, x + 650.0, frame_top)

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
        """Place a physical element name without the article's bare numbers.

        Figure 3 in Khan et al. (2025) uses digits only together with a caption
        below the micrograph.  The preview has no such external caption, so it
        names the actual configured element and alternates labels above/below
        neighbouring sections to keep them readable.
        """
        if not text:
            return
        above = canvas.caption_count % 2 == 0
        edge_y = center_y - height / 2.0 if above else center_y + height / 2.0
        position = Point((start_x + end_x) / 2.0, edge_y - 16.0 if above else edge_y + 22.0)
        leader_start = Point(position.x, position.y + 3.0 if above else position.y - 10.0)
        leader_end = Point(position.x, edge_y - 3.0 if above else edge_y + 3.0)
        canvas.labels.append(TextLabel(position, text, font_size=8.0, anchor="middle", font_weight="bold"))
        canvas.lines.append(LineShape(leader_start, leader_end, stroke="#374151", stroke_width=0.6))
        canvas.bounds_points.append(position)
        canvas.bounds_points.append(leader_end)
        canvas.caption_count += 1

    def _add_dc_block(self, canvas: _Canvas, config: S21Config, x: float, center_y: float, dw_um: float) -> float:
        """Draw the two galvanically isolated folded conductors of the DC block.

        ``Wslot`` is corrected as ``Wslot - DW`` and ``Wms`` as ``Wms + DW``,
        exactly as in ``S21CalculatorImpl``.  Each side is one folded-U
        conductor attached to its feed; the facing inner arms form the folded
        slot antenna.  The central gap is deliberately left open, because this
        element transfers RF power while blocking the FFO-to-detector DC path.
        """
        slot_width_um = max(0.1, config.w_slot_m * 1e6 - dw_um)
        slot_length_um = config.l_slot_m * 1e6
        microstrip_width_um = config.w_ms_m * 1e6 + dw_um
        microstrip_length_um = config.l_ms_m * 1e6
        slot_offset_um = config.lso_m * 1e6

        feed_length = max(22.0, microstrip_length_um * LENGTH_SCALE)
        feed_height = max(4.0, microstrip_width_um)
        gap = max(7.0, slot_width_um * WIDTH_SCALE)
        arm_span = max(22.0, slot_offset_um * LENGTH_SCALE)
        arm_length = max(62.0, slot_length_um * WIDTH_SCALE)

        left_feed = Rect(x, center_y - feed_height / 2.0, feed_length, feed_height)
        left_outer_x = left_feed.right - feed_height
        left_inner_x = left_outer_x + arm_span
        right_inner_x = left_inner_x + feed_height + gap
        right_outer_x = right_inner_x + arm_span
        # The user sketch shows the two folded conductors rising from their
        # feeds.  This is the same two-port as the earlier downward drawing,
        # but it now matches the fabrication-view orientation.
        arm_bottom = center_y + feed_height / 2.0
        arm_top = arm_bottom - arm_length

        left_bridge = Rect(left_outer_x, arm_top, arm_span + feed_height, feed_height)
        left_outer_arm = Rect(left_outer_x, arm_top, feed_height, arm_length)
        left_inner_arm = Rect(left_inner_x, arm_top, feed_height, arm_length)
        right_bridge = Rect(right_inner_x, arm_top, arm_span + feed_height, feed_height)
        right_inner_arm = Rect(right_inner_x, arm_top, feed_height, arm_length)
        right_outer_arm = Rect(right_outer_x, arm_top, feed_height, arm_length)
        right_feed = Rect(right_outer_x, center_y - feed_height / 2.0, feed_length, feed_height)

        for rect in (
            left_feed,
            left_bridge,
            left_outer_arm,
            left_inner_arm,
            right_bridge,
            right_inner_arm,
            right_outer_arm,
            right_feed,
        ):
            canvas.rects.append(RectShape(rect, fill=DC_FILL))
            canvas.include_rect(rect)

        left_slot_edge = left_inner_arm.right
        right_slot_edge = right_inner_arm.x
        slot_center_x = (left_slot_edge + right_slot_edge) / 2.0
        canvas.labels.append(
            TextLabel(
                Point(slot_center_x, center_y + 34.0),
                "DC-break",
                font_size=8.0,
                anchor="middle",
                font_weight="bold",
            )
        )
        canvas.dimensions.extend(
            (
                self._dim(
                    Point(left_slot_edge, arm_top - 13.0),
                    Point(right_slot_edge, arm_top - 13.0),
                    f"Wslot={config.w_slot_m * 1e6:g} µm; Wэфф={slot_width_um:g} µm",
                    Point(slot_center_x, arm_top - 19.0),
                ),
                self._dim(
                    Point(right_outer_arm.right + 10.0, arm_top),
                    Point(right_outer_arm.right + 10.0, arm_bottom),
                    f"Lslot={slot_length_um:g} µm",
                    Point(right_outer_arm.right + 17.0, (arm_top + arm_bottom) / 2.0),
                    label_rotation_deg=-90.0,
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
        canvas.labels.extend(
            (
                TextLabel(
                    Point(stub_center.x, center_y - r_max - 12.0),
                    "Radial shunt ×2",
                    font_size=8.0,
                    anchor="middle",
                    font_weight="bold",
                ),
                TextLabel(
                    Point(stub_center.x + 13.0, center_y - 8.0),
                    "SIS",
                    font_size=7.0,
                    font_weight="bold",
                ),
            )
        )
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

    def _add_parameter_register(
        self,
        canvas: _Canvas,
        config: S21Config,
        dw_um: float,
        left: float,
        right: float,
        top: float,
    ) -> None:
        """Add a non-overlapping register of every configured physical size.

        The drawing itself stays legible at overview scale.  This register is
        part of the same SVG and reports the raw input values; where the
        backend applies the lithographic correction it also reports ``Wэфф``.
        Transformer ``L`` is derived from the exact slice formula used by the
        calculator, not from the schematic's visual scale.
        """
        height = 300.0
        panel = Rect(left, top, max(1.0, right - left), height)
        canvas.rects.append(RectShape(panel, fill="#ffffff", stroke="#94a3b8", stroke_width=0.7))
        canvas.include_rect(panel)
        canvas.labels.append(
            TextLabel(
                Point(left + 12.0, top + 17.0),
                f"Размеры из параметров, µm (Wэфф учитывает DW={dw_um:g} µm)",
                font_size=9.0,
                font_weight="bold",
            )
        )

        def transformer_line(index: int) -> str:
            start = getattr(config, f"transf_{index}_w_start_m") * 1e6
            end = getattr(config, f"transf_{index}_w_end_m") * 1e6
            step = getattr(config, f"transf_{index}_dwdl_um")
            dl_m = getattr(config, f"transf_{index}_dl_m")
            length = self._transformer_physical_length_um(start * 1e-6, end * 1e-6, step, dl_m)
            return f"T{index}: Wstart={start:g}; Wend={end:g}; dW={step:g}; dL={dl_m * 1e6:g}; L={length:g}"

        def msl_line(index: int) -> str:
            length = getattr(config, f"msl_{index}_len_m") * 1e6
            width = getattr(config, f"msl_{index}_width_m") * 1e6
            return f"MSL{index}: W={width:g} (Wэфф={width + dw_um:g}); L={length:g}"

        columns = (
            ("Mex01", (transformer_line(7), msl_line(8), transformer_line(6))),
            ("Mex02", (msl_line(7), transformer_line(5), msl_line(6), transformer_line(4))),
            (
                "Mdcb / DC-break",
                (
                    f"slot: W={config.w_slot_m * 1e6:g} (Wэфф={config.w_slot_m * 1e6 - dw_um:g}); L={config.l_slot_m * 1e6:g}",
                    f"offset Lso={config.lso_m * 1e6:g}",
                    f"MS: W={config.w_ms_m * 1e6:g} (Wэфф={config.w_ms_m * 1e6 + dw_um:g}); L={config.l_ms_m * 1e6:g}",
                ),
            ),
            ("Mex03", (transformer_line(3), msl_line(5), transformer_line(2), msl_line(4), transformer_line(1))),
            (
                "Mrad / MLsis / SIS",
                (
                    f"Zrad1: W={config.zrad1_width_m * 1e6:g}; L={config.zrad1_len_m * 1e6:g}",
                    f"radial: R={config.radial_r_min_m * 1e6:g}…{config.radial_r_max_m * 1e6:g}; α={config.radial_angle_deg:g}°",
                    f"Zrad3: W={config.zrad3_width_m * 1e6:g}; L={config.zrad3_len_m * 1e6:g}",
                    f"Zrad4: W={config.zrad4_width_m * 1e6:g}; L={config.zrad4_len_m * 1e6:g}",
                    f"MLsis: W={config.mex4_width_m * 1e6:g}; L={config.mex4_len_m * 1e6:g}; SIS W={config.sis_width_um:g}; S={config.sis_area_um2:g} µm²",
                ),
            ),
        )
        column_width = panel.width / 2.0
        divider_x = panel.x + column_width
        canvas.lines.append(
            LineShape(
                Point(divider_x, top + 27.0),
                Point(divider_x, panel.bottom - 9.0),
                stroke="#cbd5e1",
                stroke_width=0.5,
            )
        )
        cursors = [top + 40.0, top + 40.0]
        for index, (title, lines) in enumerate(columns):
            column = 0 if index < 3 else 1
            x = panel.x + column * column_width + 12.0
            y = cursors[column]
            canvas.labels.append(TextLabel(Point(x, y), title, font_size=8.2, font_weight="bold"))
            for line_index, line in enumerate(lines):
                canvas.labels.append(
                    TextLabel(Point(x, y + 13.0 + line_index * 10.0), line, font_size=7.0, fill="#334155")
                )
            cursors[column] += 28.0 + len(lines) * 9.0

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
