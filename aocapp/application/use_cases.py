"""Application use cases."""

from __future__ import annotations

from dataclasses import dataclass

from aocapp.domain.models import StructureParams
from aocapp.domain.ports import StructureCalculator, SvgRenderer


@dataclass(frozen=True)
class GenerateStructureUseCase:
    calculator: StructureCalculator
    renderer: SvgRenderer

    def execute(self, params: StructureParams) -> str:
        params.validate()
        geometry = self.calculator.calculate(params)
        return self.renderer.render(geometry)
