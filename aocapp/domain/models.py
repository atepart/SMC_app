"""Domain models for structure geometry primitives."""

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
class PolygonShape:
    points: List[Point]
    fill: str = "#cfeef5"
    stroke: str = "#111111"
    stroke_width: float = 0.8
    fill_pattern: str | None = None


@dataclass(frozen=True)
class RectShape:
    rect: Rect
    fill: str = "#cfeef5"
    stroke: str = "#111111"
    stroke_width: float = 0.8
    fill_pattern: str | None = None


@dataclass(frozen=True)
class CircleShape:
    center: Point
    radius: float
    fill: str = "none"
    stroke: str = "#111111"
    stroke_width: float = 0.8


@dataclass(frozen=True)
class LineShape:
    start: Point
    end: Point
    stroke: str = "#111111"
    stroke_width: float = 0.8


@dataclass(frozen=True)
class TextLabel:
    position: Point
    text: str
    font_size: float = 8.0
    anchor: str = "start"
    fill: str = "#111111"
    font_weight: str = "normal"


@dataclass(frozen=True)
class StructureGeometry:
    polygons: List[PolygonShape]
    rects: List[RectShape]
    circles: List[CircleShape]
    lines: List[LineShape]
    labels: List[TextLabel]
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
