"""Application use cases."""

from __future__ import annotations

from dataclasses import dataclass

from aocapp.domain.ports import StructureCalculator, SvgRenderer
from aocapp.domain.s21_models import S21Config


@dataclass(frozen=True)
class GenerateStructureUseCase:
    calculator: StructureCalculator
    renderer: SvgRenderer

    def execute(self, config: S21Config, *, show_details: bool = True) -> str:
        config.validate()
        geometry = self.calculator.calculate(config)
        if not show_details and geometry.overview is not None:
            geometry = geometry.overview
        return self.renderer.render(geometry)
