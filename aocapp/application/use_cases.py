"""Application use cases."""

from __future__ import annotations

from dataclasses import dataclass

from aocapp.domain.models import StructureGeometry, SvgColorScheme
from aocapp.domain.ports import StructureCalculator, SvgRenderer
from aocapp.domain.s21_models import S21Config


@dataclass(frozen=True)
class SchematicDrawing:
    """An SVG and the geometry it was rendered from (for hit tests in the viewer)."""

    svg: str
    geometry: StructureGeometry


@dataclass(frozen=True)
class GenerateStructureUseCase:
    calculator: StructureCalculator
    renderer: SvgRenderer

    def draw(
        self, config: S21Config, *, show_details: bool = True, scheme: SvgColorScheme | None = None
    ) -> SchematicDrawing:
        config.validate()
        geometry = self.calculator.calculate(config)
        if not show_details and geometry.overview is not None:
            geometry = geometry.overview
        return SchematicDrawing(self.renderer.render(geometry, scheme), geometry)

    def execute(self, config: S21Config, *, show_details: bool = True, scheme: SvgColorScheme | None = None) -> str:
        return self.draw(config, show_details=show_details, scheme=scheme).svg
