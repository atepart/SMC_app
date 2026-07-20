"""Geometry calculator for the full integrated structure preview."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin
from typing import Iterable

from aocapp.domain.models import (
    CircleShape,
    DimensionLine,
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


@dataclass
class IntegratedStructureCalculator(StructureCalculator):
    """Build a schematic SVG preview for the full chain from the sketches."""

    def calculate(self, config: S21Config) -> StructureGeometry:
        polygons: list[PolygonShape] = []
        rects: list[RectShape] = []
        circles: list[CircleShape] = []
        lines: list[LineShape] = []
        labels: list[TextLabel] = []
        dimensions: list[DimensionLine] = []
        bounds_points: list[Point] = []

        center_y = 138.0
        x = 28.0
        module_gap = 52.0

        block1 = self._build_block(config, x, center_y, "Block1")
        self._merge(block1, polygons, rects, circles, lines, labels, dimensions, bounds_points)
        x = block1["right"] + module_gap

        dc_break = self._build_dc_break(config, x, center_y)
        self._merge(dc_break, polygons, rects, circles, lines, labels, dimensions, bounds_points)
        x = dc_break["right"] + module_gap

        block2 = self._build_block(config, x, center_y, "Block2")
        self._merge(block2, polygons, rects, circles, lines, labels, dimensions, bounds_points)
        x = block2["right"] + module_gap

        right_side = self._build_radial_output(config, x, center_y)
        self._merge(right_side, polygons, rects, circles, lines, labels, dimensions, bounds_points)

        bounds = bounds_from_points(bounds_points)
        margin = 32.0
        padded_bounds = Rect(
            bounds.x - margin,
            bounds.y - margin,
            bounds.width + margin * 2.0,
            bounds.height + margin * 2.0,
        )

        return StructureGeometry(
            polygons=polygons,
            rects=rects,
            circles=circles,
            lines=lines,
            labels=labels,
            dimensions=dimensions,
            bounds=padded_bounds,
        )

    def _build_block(self, config: S21Config, x: float, center_y: float, title: str) -> dict:
        left = config.block_left_taper_um
        center = config.block_center_length_um
        right = config.block_right_taper_um
        height = config.block_body_height_um
        neck_height = config.block_neck_height_um
        arm_length = config.block_arm_length_um

        body_width = left + center + right
        top = center_y - height / 2.0
        bottom = center_y + height / 2.0
        neck_top = center_y - neck_height / 2.0
        neck_bottom = center_y + neck_height / 2.0

        body_points = [
            Point(x + left, top),
            Point(x + left + center, top),
            Point(x + body_width, neck_top),
            Point(x + body_width, neck_bottom),
            Point(x + left + center, bottom),
            Point(x + left, bottom),
            Point(x, neck_bottom),
            Point(x, neck_top),
        ]

        arm_rect = Rect(x + body_width, neck_top, arm_length, neck_height)
        dim_y = top - 22.0

        dimensions = [
            self._dim(Point(x, dim_y), Point(x + left, dim_y), f"{left:g} um"),
            self._dim(Point(x + left, dim_y), Point(x + left + center, dim_y), f"{center:g} um"),
            self._dim(Point(x + left + center, dim_y), Point(x + body_width, dim_y), f"{right:g} um"),
            self._dim(
                Point(x - 12.0, top),
                Point(x - 12.0, bottom),
                f"{height:g} um",
                label_pos=Point(x - 18.0, center_y + 2.0),
            ),
            self._dim(
                Point(x + body_width, neck_top - 12.0),
                Point(x + body_width + arm_length, neck_top - 12.0),
                f"{arm_length:g} um",
                label_pos=Point(x + body_width + arm_length / 2.0, neck_top - 18.0),
            ),
        ]

        label = TextLabel(
            Point(x + body_width / 2.0, top - 42.0), title, font_size=10.0, anchor="middle", font_weight="bold"
        )
        return {
            "polygons": [PolygonShape(body_points, fill="#b7dff0")],
            "rects": [RectShape(arm_rect, fill="#b7dff0")],
            "circles": [],
            "lines": [],
            "labels": [label],
            "dimensions": dimensions,
            "right": arm_rect.right,
            "bounds_points": [*body_points, *self._rect_points(arm_rect), label.position],
        }

    def _build_dc_break(self, config: S21Config, x: float, center_y: float) -> dict:
        w_ms = config.w_ms_m * 1e6
        l_ms = config.l_ms_m * 1e6
        w_slot = config.w_slot_m * 1e6
        l_slot = config.l_slot_m * 1e6
        lso = config.lso_m * 1e6

        line_height = max(4.0, w_ms * 0.65)
        feed_len = max(12.0, l_ms)
        slot_span = max(36.0, l_slot)
        center_x = x + feed_len + slot_span / 2.0
        top = center_y - 68.0

        plate_gap = max(4.0, w_slot)
        plate_width = max(5.0, w_ms * 0.6)
        plate_height = 38.0
        arm_top_y = center_y + 12.0
        arm_bottom_y = arm_top_y + line_height
        plate_bottom_y = arm_bottom_y
        plate_top_y = plate_bottom_y - plate_height
        chamfer_dx = max(6.0, lso * 0.75)
        total_right = x + feed_len + slot_span + feed_len

        left_outer_x = center_x - plate_gap / 2.0 - plate_width
        left_inner_x = center_x - plate_gap / 2.0
        right_inner_x = center_x + plate_gap / 2.0
        right_outer_x = center_x + plate_gap / 2.0 + plate_width
        left_chamfer_start_x = left_inner_x - chamfer_dx
        right_chamfer_end_x = right_inner_x + chamfer_dx

        left_polygon = [
            Point(x, arm_top_y),
            Point(left_chamfer_start_x, arm_top_y),
            Point(left_inner_x, plate_bottom_y),
            Point(left_inner_x, plate_top_y),
            Point(left_outer_x, plate_top_y),
            Point(left_outer_x, arm_bottom_y),
            Point(x, arm_bottom_y),
        ]
        right_polygon = [
            Point(right_outer_x, plate_top_y),
            Point(right_inner_x, plate_top_y),
            Point(right_inner_x, plate_bottom_y),
            Point(right_chamfer_end_x, arm_top_y),
            Point(total_right, arm_top_y),
            Point(total_right, arm_bottom_y),
            Point(right_outer_x, arm_bottom_y),
        ]

        label = TextLabel(Point(center_x, top - 18.0), "DC-break", font_size=10.0, anchor="middle", font_weight="bold")
        dimensions = [
            self._dim(
                Point(left_inner_x, plate_top_y - 10.0),
                Point(right_inner_x, plate_top_y - 10.0),
                f"{plate_gap:g} um",
                label_pos=Point(center_x, plate_top_y - 16.0),
            ),
            self._dim(
                Point(left_outer_x - 10.0, plate_top_y),
                Point(left_outer_x - 10.0, plate_bottom_y),
                f"{plate_height:g} um",
                label_pos=Point(left_outer_x - 24.0, plate_top_y + plate_height / 2.0),
            ),
            self._dim(
                Point(x + feed_len, arm_bottom_y + 12.0),
                Point(x + feed_len + slot_span, arm_bottom_y + 12.0),
                f"{l_slot:g} um",
                label_pos=Point(x + feed_len + slot_span / 2.0, arm_bottom_y + 6.0),
            ),
        ]

        polygons = [
            PolygonShape(left_polygon, fill="#8cc6de"),
            PolygonShape(right_polygon, fill="#8cc6de"),
        ]
        bounds_points = [
            *left_polygon,
            *right_polygon,
            label.position,
        ]

        return {
            "polygons": polygons,
            "rects": [],
            "circles": [],
            "lines": [],
            "labels": [label],
            "dimensions": dimensions,
            "right": total_right,
            "bounds_points": bounds_points,
        }

    def _build_radial_output(self, config: S21Config, x: float, center_y: float) -> dict:
        line_width = max(4.0, config.zrad3_width_m * 1e6)
        pre_stub_len = config.zrad1_len_m * 1e6
        r_min = config.radial_r_min_m * 1e6
        r_max = config.radial_r_max_m * 1e6
        angle = config.radial_angle_deg
        output_width = config.msl_8_width_m * 1e6
        output_len = config.msl_8_len_m * 1e6
        taper_len = (
            self._transformer_length_um(config.transf_7_w_start_m, config.transf_7_w_end_m, config.transf_7_dwdl_um)
            + 10.0
        )

        main_line = Rect(x, center_y - line_width / 2.0, pre_stub_len + 46.0, line_width)
        stub_center = Point(x + pre_stub_len, center_y)
        top_lobe = self._fan_lobe_points(stub_center, r_min, r_max, angle, upward=True)
        bottom_lobe = self._fan_lobe_points(stub_center, r_min, r_max, angle, upward=False)
        connector = Rect(stub_center.x + 12.0, center_y - line_width / 2.0, 16.0, line_width)
        taper = self._transformer_polygon(connector.right, center_y, line_width, output_width, taper_len)
        output_line = Rect(connector.right + taper_len, center_y - output_width / 2.0, output_len, output_width)

        labels = [
            TextLabel(
                Point(stub_center.x, center_y - r_max - 18.0),
                "Radial stub",
                font_size=10.0,
                anchor="middle",
                font_weight="bold",
            ),
            TextLabel(
                Point(output_line.x + output_line.width / 2.0, center_y - output_width / 2.0 - 20.0),
                "50 um line",
                font_size=9.0,
                anchor="middle",
                font_weight="bold",
            ),
        ]

        dimensions = [
            self._dim(
                Point(x, center_y - 26.0),
                Point(stub_center.x, center_y - 26.0),
                f"{pre_stub_len:g} um",
                label_pos=Point(x + pre_stub_len / 2.0, center_y - 32.0),
            ),
            self._dim(
                Point(stub_center.x + 4.0, center_y + 14.0),
                Point(stub_center.x + r_max, center_y + 14.0),
                f"R={r_max:g} um",
                label_pos=Point(stub_center.x + (r_max + 4.0) / 2.0, center_y + 8.0),
            ),
            self._dim(
                Point(stub_center.x + r_min, center_y - 14.0),
                Point(stub_center.x + r_max, center_y - 14.0),
                f"{r_min:g}..{r_max:g} um",
                label_pos=Point(stub_center.x + (r_min + r_max) / 2.0, center_y - 20.0),
            ),
            self._dim(
                Point(output_line.x, center_y - output_width / 2.0 - 10.0),
                Point(output_line.right, center_y - output_width / 2.0 - 10.0),
                f"{output_len:g} um",
                label_pos=Point(output_line.x + output_len / 2.0, center_y - output_width / 2.0 - 16.0),
            ),
            self._dim(
                Point(output_line.right + 18.0, center_y - output_width / 2.0),
                Point(output_line.right + 18.0, center_y + output_width / 2.0),
                f"{output_width:g} um",
                label_pos=Point(output_line.right + 32.0, center_y + 2.0),
            ),
        ]

        rects = [
            RectShape(main_line, fill="#8cc6de"),
            RectShape(connector, fill="#8cc6de"),
            RectShape(output_line, fill="#f4d369"),
        ]
        bounds_points = [
            *self._rect_points(main_line),
            *top_lobe,
            *bottom_lobe,
            *self._rect_points(connector),
            *taper,
            *self._rect_points(output_line),
        ]
        for label in labels:
            bounds_points.append(label.position)

        return {
            "polygons": [
                PolygonShape(top_lobe, fill="#f5d44d"),
                PolygonShape(bottom_lobe, fill="#f5d44d"),
                PolygonShape(taper, fill="#f4d369"),
            ],
            "rects": rects,
            "circles": [CircleShape(stub_center, radius=max(3.0, r_min / 2.0), fill="white")],
            "lines": [],
            "labels": labels,
            "dimensions": dimensions,
            "right": output_line.right,
            "bounds_points": bounds_points,
        }

    def _merge(
        self,
        module: dict,
        polygons: list[PolygonShape],
        rects: list[RectShape],
        circles: list[CircleShape],
        lines: list[LineShape],
        labels: list[TextLabel],
        dimensions: list[DimensionLine],
        bounds_points: list[Point],
    ) -> None:
        polygons.extend(module["polygons"])
        rects.extend(module["rects"])
        circles.extend(module["circles"])
        lines.extend(module["lines"])
        labels.extend(module["labels"])
        dimensions.extend(module["dimensions"])
        bounds_points.extend(module["bounds_points"])
        for dimension in module["dimensions"]:
            bounds_points.extend([dimension.start, dimension.end, dimension.label_pos])

    def _fan_lobe_points(
        self, center: Point, r_min: float, r_max: float, angle_deg: float, upward: bool
    ) -> list[Point]:
        center_angle = -90.0 if upward else 90.0
        start = center_angle - angle_deg / 2.0
        stop = center_angle + angle_deg / 2.0
        step = max(8.0, angle_deg / 6.0)

        points: list[Point] = []
        angle = start
        while angle <= stop + 1e-9:
            rad = radians(angle)
            points.append(Point(center.x + r_max * cos(rad), center.y + r_max * sin(rad)))
            angle += step
        angle = stop
        inner_points: list[Point] = []
        while angle >= start - 1e-9:
            rad = radians(angle)
            inner_points.append(Point(center.x + r_min * cos(rad), center.y + r_min * sin(rad)))
            angle -= step
        return points + inner_points

    def _transformer_length_um(self, w_start_m: float, w_end_m: float, slope_um: float) -> float:
        delta_w_um = abs(w_end_m - w_start_m) * 1e6
        return max(2.0, delta_w_um / max(slope_um, 1e-6))

    def _transformer_polygon(
        self, x: float, center_y: float, w_start: float, w_end: float, length: float
    ) -> list[Point]:
        return [
            Point(x, center_y - w_start / 2.0),
            Point(x + length, center_y - w_end / 2.0),
            Point(x + length, center_y + w_end / 2.0),
            Point(x, center_y + w_start / 2.0),
        ]

    def _rect_points(self, rect: Rect) -> Iterable[Point]:
        return (
            Point(rect.x, rect.y),
            Point(rect.right, rect.y),
            Point(rect.right, rect.bottom),
            Point(rect.x, rect.bottom),
        )

    def _dim(self, start: Point, end: Point, label: str, label_pos: Point | None = None) -> DimensionLine:
        if label_pos is None:
            label_pos = Point((start.x + end.x) / 2.0, (start.y + end.y) / 2.0 - 4.0)
        return DimensionLine(start=start, end=end, label=label, label_pos=label_pos)
