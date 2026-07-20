"""SVG renderer for the calculated structure geometry."""

from __future__ import annotations

from dataclasses import dataclass

from aocapp.domain.models import Point, PolygonShape, StructureGeometry, TextLabel
from aocapp.domain.ports import SvgRenderer


@dataclass
class SvgRendererImpl(SvgRenderer):
    stroke: str = "#000000"
    dimension_color: str = "#000000"
    background: str = "#fdfdfd"

    def render(self, geometry: StructureGeometry) -> str:
        bounds = geometry.bounds
        view_box = f"{bounds.x:g} {bounds.y:g} {bounds.width:g} {bounds.height:g}"

        font_size = max(4.0, min(8.2, bounds.height * 0.036))
        dim_lines = "\n".join(self._render_dimension(dim, font_size) for dim in geometry.dimensions)
        polygons = "\n".join(self._render_polygon(polygon) for polygon in geometry.polygons)
        rects = "\n".join(self._render_rect(rect_shape) for rect_shape in geometry.rects)
        circles = "\n".join(self._render_circle(circle) for circle in geometry.circles)
        lines = "\n".join(self._render_line(line) for line in geometry.lines)
        labels = "\n".join(self._render_label(label) for label in geometry.labels)

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" width="100%" height="100%">
  <defs>
    <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M 0 0 L 6 3 L 0 6 Z" fill="{self.dimension_color}" />
    </marker>
    <pattern id="hatch" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(135)">
      <line x1="0" y1="0" x2="0" y2="8" stroke="#6b7280" stroke-width="1" />
    </pattern>
  </defs>
  <rect x="{bounds.x:g}" y="{bounds.y:g}" width="{bounds.width:g}" height="{bounds.height:g}" fill="{self.background}" />
  <g>
    {polygons}
    {rects}
    {circles}
    {lines}
  </g>
  <g stroke="{self.dimension_color}" stroke-width="0.5" fill="none">
    {dim_lines}
  </g>
  <g>
    {labels}
  </g>
</svg>"""
        return svg

    def _render_polygon(self, polygon: PolygonShape) -> str:
        points = " ".join(f"{point.x:g},{point.y:g}" for point in polygon.points)
        fill = f"url(#{polygon.fill_pattern})" if polygon.fill_pattern else polygon.fill
        return (
            f'<polygon points="{points}" fill="{fill}" stroke="{polygon.stroke}" '
            f'stroke-width="{polygon.stroke_width:g}" />'
        )

    def _render_rect(self, rect_shape) -> str:
        rect = rect_shape.rect
        fill = f"url(#{rect_shape.fill_pattern})" if rect_shape.fill_pattern else rect_shape.fill
        return (
            f'<rect x="{rect.x:g}" y="{rect.y:g}" width="{rect.width:g}" height="{rect.height:g}" '
            f'fill="{fill}" stroke="{rect_shape.stroke}" stroke-width="{rect_shape.stroke_width:g}" />'
        )

    def _render_circle(self, circle) -> str:
        return (
            f'<circle cx="{circle.center.x:g}" cy="{circle.center.y:g}" r="{circle.radius:g}" '
            f'fill="{circle.fill}" stroke="{circle.stroke}" stroke-width="{circle.stroke_width:g}" />'
        )

    def _render_line(self, line) -> str:
        return (
            f'<line x1="{line.start.x:g}" y1="{line.start.y:g}" x2="{line.end.x:g}" y2="{line.end.y:g}" '
            f'stroke="{line.stroke}" stroke-width="{line.stroke_width:g}" />'
        )

    def _render_dimension(self, dim, font_size: float) -> str:
        label = dim.label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<line x1="{dim.start.x:g}" y1="{dim.start.y:g}" x2="{dim.end.x:g}" y2="{dim.end.y:g}" '
            f'marker-start="url(#arrow)" marker-end="url(#arrow)" />\n'
            f'<text x="{dim.label_pos.x:g}" y="{dim.label_pos.y:g}" font-size="{font_size:g}" '
            f'text-anchor="middle" fill="{self.dimension_color}">{label}</text>'
        )

    def _render_label(self, label: TextLabel) -> str:
        lines = label.text.splitlines() or [label.text]
        escaped_lines = [self._escape(line) for line in lines]
        tspan_items = []
        for index, line in enumerate(escaped_lines):
            dy = "0" if index == 0 else "1.2em"
            tspan_items.append(f'<tspan x="{label.position.x:g}" dy="{dy}">{line}</tspan>')
        tspan_markup = "".join(tspan_items)
        return (
            f'<text x="{label.position.x:g}" y="{label.position.y:g}" font-size="{label.font_size:g}" '
            f'text-anchor="{label.anchor}" fill="{label.fill}" font-weight="{label.font_weight}">{tspan_markup}</text>'
        )

    def _escape(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
