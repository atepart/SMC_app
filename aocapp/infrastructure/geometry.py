"""Geometry calculator for the concept structure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from aocapp.domain.models import DimensionLine, Point, Rect, StructureGeometry, StructureParams, bounds_from_points
from aocapp.domain.ports import StructureCalculator


@dataclass
class OctagonArmCalculator(StructureCalculator):
    """Calculates an octagon-like body with a right-side arm."""

    def calculate(self, params: StructureParams) -> StructureGeometry:
        height = params.body_height_um
        neck_height = params.neck_height_um
        left_taper = params.left_taper_um
        center_length = params.center_length_um
        right_taper = params.right_taper_um
        arm_length = params.arm_length_um

        body_width = params.body_width_um
        neck_top = (height - neck_height) / 2.0
        neck_bottom = (height + neck_height) / 2.0

        body_points = [
            Point(left_taper, 0.0),
            Point(left_taper + center_length, 0.0),
            Point(body_width, neck_top),
            Point(body_width, neck_bottom),
            Point(left_taper + center_length, height),
            Point(left_taper, height),
            Point(0.0, neck_bottom),
            Point(0.0, neck_top),
        ]

        arm_rect = Rect(body_width, neck_top, arm_length, neck_height)

        dimensions = self._dimension_lines(
            left_taper,
            center_length,
            right_taper,
            height,
            neck_top,
            body_width,
            arm_length,
        )

        bounds = self._compute_bounds(body_points, arm_rect, dimensions)
        margin = max(2.0, height * 0.1)
        bounds = Rect(
            bounds.x - margin,
            bounds.y - margin,
            bounds.width + margin * 2.0,
            bounds.height + margin * 2.0,
        )

        return StructureGeometry(
            body_points=body_points,
            arm_rect=arm_rect,
            dimensions=dimensions,
            bounds=bounds,
        )

    def _dimension_lines(
        self,
        left_taper: float,
        center_length: float,
        right_taper: float,
        height: float,
        neck_top: float,
        body_width: float,
        arm_length: float,
    ) -> List[DimensionLine]:
        dim_offset = max(6.0, height * 0.12)
        text_offset = max(3.0, height * 0.06)

        top_y = -dim_offset
        dim_lines: List[DimensionLine] = []

        dim_lines.append(
            DimensionLine(
                start=Point(0.0, top_y),
                end=Point(left_taper, top_y),
                label=f"{left_taper:g} um",
                label_pos=Point(left_taper / 2.0, top_y - text_offset),
            )
        )
        dim_lines.append(
            DimensionLine(
                start=Point(left_taper, top_y),
                end=Point(left_taper + center_length, top_y),
                label=f"{center_length:g} um",
                label_pos=Point(left_taper + center_length / 2.0, top_y - text_offset),
            )
        )
        dim_lines.append(
            DimensionLine(
                start=Point(left_taper + center_length, top_y),
                end=Point(body_width, top_y),
                label=f"{right_taper:g} um",
                label_pos=Point(left_taper + center_length + right_taper / 2.0, top_y - text_offset),
            )
        )

        height_x = -dim_offset
        dim_lines.append(
            DimensionLine(
                start=Point(height_x, 0.0),
                end=Point(height_x, height),
                label=f"{height:g} um",
                label_pos=Point(height_x - text_offset, height / 2.0),
            )
        )

        arm_y = neck_top - dim_offset * 0.6
        dim_lines.append(
            DimensionLine(
                start=Point(body_width, arm_y),
                end=Point(body_width + arm_length, arm_y),
                label=f"{arm_length:g} um",
                label_pos=Point(body_width + arm_length / 2.0, arm_y - text_offset),
            )
        )

        return dim_lines

    def _compute_bounds(
        self,
        body_points: List[Point],
        arm_rect: Rect,
        dimensions: List[DimensionLine],
    ) -> Rect:
        points = list(body_points)
        points.extend(
            [
                Point(arm_rect.x, arm_rect.y),
                Point(arm_rect.right, arm_rect.y),
                Point(arm_rect.right, arm_rect.bottom),
                Point(arm_rect.x, arm_rect.bottom),
            ]
        )
        for dim in dimensions:
            points.append(dim.start)
            points.append(dim.end)
            points.append(dim.label_pos)
        return bounds_from_points(points)
