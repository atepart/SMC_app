"""Domain models for structure geometry and input parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True)
class DimensionLine:
    start: Point
    end: Point
    label: str
    label_pos: Point


@dataclass(frozen=True)
class StructureParams:
    left_taper_um: float
    center_length_um: float
    right_taper_um: float
    body_height_um: float
    neck_height_um: float
    arm_length_um: float

    def validate(self) -> None:
        errors: List[str] = []
        for name, value in (
            ("left_taper_um", self.left_taper_um),
            ("center_length_um", self.center_length_um),
            ("right_taper_um", self.right_taper_um),
            ("body_height_um", self.body_height_um),
            ("neck_height_um", self.neck_height_um),
            ("arm_length_um", self.arm_length_um),
        ):
            if value <= 0:
                errors.append(f"{name} must be > 0")

        if self.neck_height_um > self.body_height_um:
            errors.append("neck_height_um must be <= body_height_um")

        if errors:
            raise ValueError("; ".join(errors))

    @property
    def body_width_um(self) -> float:
        return self.left_taper_um + self.center_length_um + self.right_taper_um


@dataclass(frozen=True)
class StructureGeometry:
    body_points: List[Point]
    arm_rect: Rect
    dimensions: List[DimensionLine]
    bounds: Rect


def bounds_from_points(points: Iterable[Point]) -> Rect:
    points_list = list(points)
    if not points_list:
        return Rect(0.0, 0.0, 0.0, 0.0)
    min_x = min(p.x for p in points_list)
    max_x = max(p.x for p in points_list)
    min_y = min(p.y for p in points_list)
    max_y = max(p.y for p in points_list)
    return Rect(min_x, min_y, max_x - min_x, max_y - min_y)
