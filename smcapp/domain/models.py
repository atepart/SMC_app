"""Domain models for structure geometry primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Mapping


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
    label_rotation_deg: float = 0.0
    element_id: str = ""


@dataclass(frozen=True)
class PolygonShape:
    points: List[Point]
    fill: str = "#cfeef5"
    stroke: str = "#111111"
    stroke_width: float = 0.8
    fill_pattern: str | None = None


@dataclass(frozen=True)
class PathShape:
    """Native vector contour with explicit bounds (including Bézier controls)."""

    data: str
    bounds: Rect
    element_id: str
    fill: str = "none"
    stroke: str = "#111111"
    stroke_width: float = 0.8


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
    # A neat arrowhead at ``end`` (number callouts point at their element).
    arrow_end: bool = False


@dataclass(frozen=True)
class TextLabel:
    position: Point
    text: str
    font_size: float = 8.0
    anchor: str = "start"
    fill: str = "#111111"
    font_weight: str = "normal"


@dataclass(frozen=True)
class Callout:
    """A label next to an element and the arrow from it to the element's edge."""

    element_id: str
    label: TextLabel
    arrow: LineShape


@dataclass(frozen=True)
class SectionPort:
    """A section's join plane in SVG coordinates; unequal widths form a step."""

    center: Point
    width: float

    @property
    def top(self) -> Point:
        return Point(self.center.x, self.center.y - self.width / 2)

    @property
    def bottom(self) -> Point:
        return Point(self.center.x, self.center.y + self.width / 2)


@dataclass(frozen=True)
class ElementParameter:
    label: str
    value: float
    unit: str = "µm"


@dataclass(frozen=True)
class SchematicElement:
    """Inspectable layout result shared by metal, labels and dimensions."""

    element_id: str
    title: str
    bounds: Rect
    parameters: tuple[ElementParameter, ...]
    input_port: SectionPort | None = None
    output_port: SectionPort | None = None
    number: int | None = None
    # Local copies of the actual contour support dimensioned enlarged views.
    polygon: tuple[Point, ...] = ()
    auxiliary_lines: tuple[LineShape, ...] = ()
    # Non-metal areas of the element (e.g. the DC-block slot in the ground
    # plane).  They are drawn, but never take part in the metal outline.
    auxiliary_rects: tuple[Rect, ...] = ()


@dataclass(frozen=True)
class StructureGeometry:
    polygons: List[PolygonShape]
    rects: List[RectShape]
    circles: List[CircleShape]
    lines: List[LineShape]
    labels: List[TextLabel]
    dimensions: List[DimensionLine]
    bounds: Rect
    overview: StructureGeometry | None = None
    paths: List[PathShape] = field(default_factory=list)
    elements: List[SchematicElement] = field(default_factory=list)
    # Bottom-electrode features (the DC-block slot) lie beneath the top-film
    # metal in plan view, so they are rendered before every metal shape.
    underlay_paths: List[PathShape] = field(default_factory=list)
    # Element numbers (and "SIS") with their arrows; the label and the arrow
    # are also in ``labels``/``lines`` for rendering.
    callouts: List[Callout] = field(default_factory=list)
    # Contours that belong to each element (the fans of the radial stub, the
    # DC-block slot): what the cursor is over when the viewer highlights a number.
    hit_areas: List[tuple[str, tuple[Point, ...]]] = field(default_factory=list)
    # One thin line on every face shared by two elements (or the two parts of
    # 14). Rendered above the metal fill but below its outline and the SIS
    # circle, so the circle sits on top of the L1|L2 seam (GitHub #11).
    seams: List[LineShape] = field(default_factory=list)


@dataclass(frozen=True)
class SvgColorScheme:
    """Colour remapping applied when a drawing is rendered.

    Geometry carries the colours of the light sheet; a scheme maps each of them
    to its counterpart (e.g. for a dark sheet), so one layout serves both.
    Keys are lower-case ``#rgb``/``#rrggbb`` strings; unmapped colours pass through.
    """

    colors: Mapping[str, str] = field(default_factory=dict)

    def color(self, value: str) -> str:
        return self.colors.get(value.lower(), value)


def bounds_from_points(points: Iterable[Point]) -> Rect:
    points_list = list(points)
    if not points_list:
        return Rect(0.0, 0.0, 0.0, 0.0)
    min_x = min(p.x for p in points_list)
    max_x = max(p.x for p in points_list)
    min_y = min(p.y for p in points_list)
    max_y = max(p.y for p in points_list)
    return Rect(min_x, min_y, max_x - min_x, max_y - min_y)
