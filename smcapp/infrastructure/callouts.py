"""Element numbers next to their elements, each with a neat arrow (GitHub #10).

Every number is placed as close to its element as the drawing allows: the
search walks outwards from points on the element's edge, in directions
around the edge's outward normal, and takes the nearest spot where the label
touches no metal, no slot, no other label and no other arrow.  The arrow runs
from the label to that edge point, so its tip lies on the element boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, hypot, radians, sin

from smcapp.domain.models import LineShape, Point, TextLabel

LEADER_COLOR = "#64748b"
LEADER_WIDTH = 0.6
# The arrowhead is ~5 units long; keep a visible stem behind it.
MIN_ARROW = 8.0
MAX_DISTANCE = 600.0
DISTANCE_STEP = 2.5
# Clearance around a label (SVG units, 2 per µm).
PADDING = 1.5
ANGLES = (0.0, 20.0, -20.0, 40.0, -40.0, 60.0, -60.0, 75.0, -75.0)
# Penalty for an arrow drawn across the metal of another element.
CROSSING_PENALTY = 30.0
# The radial fans are large schematic sectors over the lines 13–18: a number
# may stand on a fan (wholly inside it) and its arrow may cross a fan edge.
SOFT_PENALTY = 6.0
ANCHOR_SPACING = 6.0
# Approximate Arial advance widths as a fraction of the font size.
_ADVANCE = {"I": 0.28, "S": 0.67, " ": 0.28}


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, p: Point) -> bool:
        return self.x0 <= p.x <= self.x1 and self.y0 <= p.y <= self.y1

    def overlaps(self, other: Box) -> bool:
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1

    def edges(self) -> list[tuple[Point, Point]]:
        a, b = Point(self.x0, self.y0), Point(self.x1, self.y0)
        c, d = Point(self.x1, self.y1), Point(self.x0, self.y1)
        return [(a, b), (b, c), (c, d), (d, a)]


def text_box(label: TextLabel) -> Box:
    """Box of a single-line label (cap height; digits have no descenders)."""
    width = sum(_ADVANCE.get(char, 0.56) for char in label.text) * label.font_size
    if label.anchor == "middle":
        left = label.position.x - width / 2
    elif label.anchor == "end":
        left = label.position.x - width
    else:
        left = label.position.x
    return Box(left, label.position.y - 0.72 * label.font_size, left + width, label.position.y)


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True

    def on(p: Point, q: Point, r: Point, value: float) -> bool:
        return (
            abs(value) < 1e-9
            and min(p.x, q.x) - 1e-9 <= r.x <= max(p.x, q.x) + 1e-9
            and (min(p.y, q.y) - 1e-9 <= r.y <= max(p.y, q.y) + 1e-9)
        )

    return on(c, d, a, d1) or on(c, d, b, d2) or on(a, b, c, d3) or on(a, b, d, d4)


def point_in_polygon(p: Point, polygon: list[Point]) -> bool:
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a.y > p.y) != (b.y > p.y) and p.x < a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y):
            inside = not inside
    return inside


@dataclass
class _Shape:
    owner: str
    points: list[Point]
    soft: bool = False
    box: Box = field(init=False)

    def __post_init__(self) -> None:
        xs, ys = [p.x for p in self.points], [p.y for p in self.points]
        self.box = Box(min(xs), min(ys), max(xs), max(ys))
        self._edges = list(zip(self.points, self.points[1:] + self.points[:1]))

    def edges(self) -> list[tuple[Point, Point]]:
        return self._edges

    def box_cost(self, box: Box) -> float | None:
        """0 when clear of the box, a penalty when a soft shape holds it wholly, else None."""
        if not self.box.overlaps(box):
            return 0.0
        if any(segment_hits_box(a, b, box) for a, b in self._edges):
            return None
        if not point_in_polygon(Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2), self.points):
            return 0.0
        return SOFT_PENALTY if self.soft else None

    def crosses(self, a: Point, b: Point) -> bool:
        seg = Box(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
        if not (seg.x0 <= self.box.x1 and self.box.x0 <= seg.x1 and seg.y0 <= self.box.y1 and self.box.y0 <= seg.y1):
            return False
        if point_in_polygon(a, self.points) or point_in_polygon(b, self.points):
            return True
        return any(segments_intersect(a, b, c, d) for c, d in self._edges)


@dataclass(frozen=True)
class _Anchor:
    point: Point
    normal: tuple[float, float]
    # Distance along the edge from the element's middle: a mild preference.
    offset: float


def segment_hits_box(a: Point, b: Point, box: Box) -> bool:
    """Liang–Barsky clipping: does segment ab touch the closed box?"""
    dx, dy = b.x - a.x, b.y - a.y
    lo, hi = 0.0, 1.0
    for p, q in ((-dx, a.x - box.x0), (dx, box.x1 - a.x), (-dy, a.y - box.y0), (dy, box.y1 - a.y)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > hi:
                return False
            lo = max(lo, t)
        else:
            if t < lo:
                return False
            hi = min(hi, t)
    return lo <= hi


class CalloutPlacer:
    """Greedy nearest-free-spot placement; earlier callouts keep their place."""

    def __init__(
        self,
        shapes: list[tuple[str, list[Point]]],
        fixed_labels: list[TextLabel] = (),
        soft_owners: set[str] = frozenset(),
    ) -> None:
        self._shapes = [
            _Shape(owner, list(points), owner in soft_owners) for owner, points in shapes if len(points) >= 3
        ]
        self._boxes = [self._padded(text_box(label)) for label in fixed_labels]
        self._arrows: list[tuple[Point, Point]] = []

    @staticmethod
    def _padded(box: Box) -> Box:
        return Box(box.x0 - PADDING, box.y0 - PADDING, box.x1 + PADDING, box.y1 + PADDING)

    @property
    def boxes(self) -> list[Box]:
        return list(self._boxes)

    def _anchors(self, owner: str, transparent: set[str]) -> list[_Anchor]:
        own = [shape for shape in self._shapes if shape.owner == owner]
        if not own:
            return []
        xs = [p.x for shape in own for p in shape.points]
        ys = [p.y for shape in own for p in shape.points]
        middle = Point((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        blocking = [shape for shape in self._shapes if shape.owner not in transparent and not shape.soft]
        anchors = []
        for shape in own:
            for a, b in shape.edges():
                length = hypot(b.x - a.x, b.y - a.y)
                if length < 1e-9:
                    continue
                tx, ty = (b.x - a.x) / length, (b.y - a.y) / length
                normal = (ty, -tx)
                mid = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
                if point_in_polygon(Point(mid.x + normal[0] * 0.01, mid.y + normal[1] * 0.01), shape.points):
                    normal = (-ty, tx)
                count = max(1, int(length // ANCHOR_SPACING))
                for i in range(count):
                    s = length * (i + 0.5) / count
                    if length > 4 and not 1.5 <= s <= length - 1.5:
                        continue
                    p = Point(a.x + tx * s, a.y + ty * s)
                    probe = Point(p.x + normal[0] * 1.0, p.y + normal[1] * 1.0)
                    if any(point_in_polygon(probe, other.points) for other in blocking if other.box.contains(probe)):
                        continue  # a join face hidden by a neighbour
                    anchors.append(_Anchor(p, normal, hypot(p.x - middle.x, p.y - middle.y)))
        return anchors

    def place(
        self,
        owner: str,
        text: str,
        *,
        font_size: float = 10.0,
        font_weight: str = "bold",
        transparent: set[str] = frozenset(),
    ) -> tuple[TextLabel, LineShape] | None:
        """Put ``text`` next to ``owner`` and return the label and its arrow.

        If no spot keeps the arrow clear of other labels and arrows, the
        nearest spot that only keeps the label itself clear is taken.
        """
        return self._place(owner, text, font_size, font_weight, transparent, strict=True) or self._place(
            owner, text, font_size, font_weight, transparent, strict=False
        )

    def _place(
        self, owner: str, text: str, font_size: float, font_weight: str, transparent: set[str], strict: bool
    ) -> tuple[TextLabel, LineShape] | None:
        sample = text_box(TextLabel(Point(0, 0), text, font_size, anchor="middle"))
        half_w, half_h = (sample.x1 - sample.x0) / 2 + PADDING, (sample.y1 - sample.y0) / 2 + PADDING
        see_through = {owner} | set(transparent)
        anchors = self._anchors(owner, see_through)
        directions = []
        for anchor in anchors:
            for angle in ANGLES:
                r = radians(angle)
                nx, ny = anchor.normal
                u = (nx * cos(r) - ny * sin(r), nx * sin(r) + ny * cos(r))
                # Distance from the label centre to its padded box edge along u.
                reach = min(
                    half_w / abs(u[0]) if abs(u[0]) > 1e-9 else 1e9, half_h / abs(u[1]) if abs(u[1]) > 1e-9 else 1e9
                )
                directions.append((anchor, u, reach, abs(angle) * 0.1 + anchor.offset * 0.08))
        max_reach = max((reach for _anchor, _u, reach, _extra in directions), default=0.0)
        best: tuple[float, TextLabel, LineShape, Box] | None = None
        distance = DISTANCE_STEP
        while distance <= MAX_DISTANCE:
            if best is not None and distance - max_reach >= best[0]:
                break
            for anchor, u, reach, extra in directions:
                arrow_length = distance - reach
                if arrow_length < MIN_ARROW:
                    continue
                cost = arrow_length + extra
                if best is not None and cost >= best[0]:
                    continue
                centre = Point(anchor.point.x + u[0] * distance, anchor.point.y + u[1] * distance)
                box = Box(centre.x - half_w, centre.y - half_h, centre.x + half_w, centre.y + half_h)
                if any(box.overlaps(other) for other in self._boxes):
                    continue
                if any(segment_hits_box(a, b, box) for a, b in self._arrows):
                    continue
                penalties = [shape.box_cost(box) for shape in self._shapes]
                if None in penalties:
                    continue
                cost += sum(penalties)
                start = Point(centre.x - u[0] * reach, centre.y - u[1] * reach)
                if strict and any(segment_hits_box(start, anchor.point, other) for other in self._boxes):
                    continue
                if strict and any(segments_intersect(start, anchor.point, a, b) for a, b in self._arrows):
                    continue
                # Stop just short of the tip: touching the neighbour at a join is fine.
                near_tip = Point(anchor.point.x + u[0] * 0.75, anchor.point.y + u[1] * 0.75)
                cost += sum(
                    SOFT_PENALTY if shape.soft else CROSSING_PENALTY
                    for shape in self._shapes
                    if shape.owner not in see_through and shape.crosses(start, near_tip)
                )
                if best is not None and cost >= best[0]:
                    continue
                baseline = centre.y + (sample.y1 - sample.y0) / 2
                label = TextLabel(
                    Point(centre.x, baseline), text, font_size, anchor="middle", fill="#111111", font_weight=font_weight
                )
                arrow = LineShape(start, anchor.point, stroke=LEADER_COLOR, stroke_width=LEADER_WIDTH, arrow_end=True)
                best = (cost, label, arrow, box)
            distance += DISTANCE_STEP
        if best is None:
            return None
        _cost, label, arrow, box = best
        self._boxes.append(box)
        self._arrows.append((arrow.start, arrow.end))
        return label, arrow
