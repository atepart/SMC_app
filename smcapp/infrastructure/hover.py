"""Which element is under the cursor, and where its number is (GitHub #10).

The viewer highlights the number of the element under the cursor.  Both the
element contours and the number positions come from the same
:class:`StructureGeometry` as the drawing, so the highlight always matches
what is on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from smcapp.domain.models import LineShape, Point, StructureGeometry
from smcapp.infrastructure.callouts import Box, point_in_polygon, text_box


@dataclass(frozen=True)
class NumberMark:
    """An element number on the drawing: its text box and its arrow."""

    element_id: str
    text: str
    box: Box
    arrow: LineShape


@dataclass(frozen=True)
class _Area:
    element_id: str
    points: tuple[Point, ...]
    box: Box
    size: float


def _distance_to_segment(p: Point, a: Point, b: Point) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 < 1e-18 else max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length2))
    return hypot(p.x - a.x - t * dx, p.y - a.y - t * dy)


def _grown(box: Box, margin: float) -> Box:
    return Box(box.x0 - margin, box.y0 - margin, box.x1 + margin, box.y1 + margin)


@dataclass(frozen=True)
class ElementHitMap:
    """Hit test of the drawing in SVG user units."""

    areas: tuple[_Area, ...] = ()
    # Number labels by element; every callout label (also "SIS") is hoverable.
    marks: tuple[NumberMark, ...] = ()
    labels: tuple[tuple[str, Box], ...] = ()

    @classmethod
    def from_geometry(cls, geometry: StructureGeometry) -> ElementHitMap:
        areas = []
        for element_id, points in geometry.hit_areas:
            if len(points) < 3:
                continue
            xs, ys = [p.x for p in points], [p.y for p in points]
            size = abs(sum(a.x * b.y - b.x * a.y for a, b in zip(points, points[1:] + points[:1]))) / 2
            areas.append(_Area(element_id, tuple(points), Box(min(xs), min(ys), max(xs), max(ys)), size))
        marks = tuple(
            NumberMark(c.element_id, c.label.text, text_box(c.label), c.arrow)
            for c in geometry.callouts
            if c.label.text.isdigit()
        )
        labels = tuple((c.element_id, text_box(c.label)) for c in geometry.callouts)
        return cls(tuple(areas), marks, labels)

    def mark(self, element_id: str) -> NumberMark | None:
        return next((mark for mark in self.marks if mark.element_id == element_id), None)

    def element_at(self, point: Point, tolerance: float = 0.0) -> str | None:
        """The element under *point*, or within *tolerance* of it.

        A number label counts as its element.  Where contours overlap (the
        SIS symbol on line 14) the smallest one wins; outside every contour
        the nearest one within *tolerance* is taken, so thin lines are easy
        to hit at a small scale.
        """
        for element_id, box in self.labels:
            if _grown(box, tolerance).contains(point):
                return element_id
        inside = [a for a in self.areas if a.box.contains(point) and point_in_polygon(point, list(a.points))]
        if inside:
            return min(inside, key=lambda a: a.size).element_id
        if tolerance <= 0:
            return None
        best: tuple[float, str] | None = None
        for area in self.areas:
            if not _grown(area.box, tolerance).contains(point):
                continue
            distance = min(
                _distance_to_segment(point, a, b) for a, b in zip(area.points, area.points[1:] + area.points[:1])
            )
            if distance <= tolerance and (best is None or distance < best[0]):
                best = (distance, area.element_id)
        return None if best is None else best[1]

    def mark_at(self, point: Point, tolerance: float = 0.0) -> NumberMark | None:
        element_id = self.element_at(point, tolerance)
        return None if element_id is None else self.mark(element_id)
