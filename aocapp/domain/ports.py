"""Domain ports for calculation and rendering."""

from __future__ import annotations

from typing import Protocol

from .models import StructureGeometry, StructureParams


class StructureCalculator(Protocol):
    def calculate(self, params: StructureParams) -> StructureGeometry:
        ...


class SvgRenderer(Protocol):
    def render(self, geometry: StructureGeometry) -> str:
        ...
