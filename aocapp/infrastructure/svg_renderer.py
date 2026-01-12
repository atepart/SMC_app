"""SVG renderer for the calculated structure geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aocapp.domain.models import Point, StructureGeometry
from aocapp.domain.ports import SvgRenderer


@dataclass
class SvgRendererImpl(SvgRenderer):
    body_fill: str = "#9ad7e9"
    stroke: str = "#000000"
    dimension_color: str = "#000000"

    def render(self, geometry: StructureGeometry) -> str:
        bounds = geometry.bounds
        view_box = f"{bounds.x:g} {bounds.y:g} {bounds.width:g} {bounds.height:g}"

        path_d = self._path_from_points(geometry.body_points)
        arm = geometry.arm_rect

        font_size = max(4.0, min(10.0, bounds.height * 0.06))
        dim_lines = "\n".join(self._render_dimension(dim, font_size) for dim in geometry.dimensions)

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" width="100%" height="100%">
  <defs>
    <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M 0 0 L 6 3 L 0 6 Z" fill="{self.dimension_color}" />
    </marker>
  </defs>
  <rect x="{bounds.x:g}" y="{bounds.y:g}" width="{bounds.width:g}" height="{bounds.height:g}" fill="white" />
  <path d="{path_d}" fill="{self.body_fill}" stroke="{self.stroke}" stroke-width="0.8" />
  <rect x="{arm.x:g}" y="{arm.y:g}" width="{arm.width:g}" height="{arm.height:g}" fill="{self.body_fill}" stroke="{self.stroke}" stroke-width="0.8" />
  <g stroke="{self.dimension_color}" stroke-width="0.5" fill="none">
    {dim_lines}
  </g>
</svg>"""
        return svg

    def _path_from_points(self, points: Iterable[Point]) -> str:
        pts = list(points)
        if not pts:
            return ""
        parts = [f"M {pts[0].x:g} {pts[0].y:g}"]
        for pt in pts[1:]:
            parts.append(f"L {pt.x:g} {pt.y:g}")
        parts.append("Z")
        return " ".join(parts)

    def _render_dimension(self, dim, font_size: float) -> str:
        label = dim.label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f"<line x1=\"{dim.start.x:g}\" y1=\"{dim.start.y:g}\" x2=\"{dim.end.x:g}\" y2=\"{dim.end.y:g}\" "
            f"marker-start=\"url(#arrow)\" marker-end=\"url(#arrow)\" />\n"
            f"<text x=\"{dim.label_pos.x:g}\" y=\"{dim.label_pos.y:g}\" font-size=\"{font_size:g}\" "
            f"text-anchor=\"middle\" fill=\"{self.dimension_color}\">{label}</text>"
        )
