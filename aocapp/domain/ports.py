"""Domain ports for calculation and rendering."""

from __future__ import annotations

from typing import Protocol

from .models import StructureGeometry, StructureParams
from .s21_models import S21Config, S21Result


class StructureCalculator(Protocol):
    def calculate(self, params: StructureParams) -> StructureGeometry:
        ...


class SvgRenderer(Protocol):
    def render(self, geometry: StructureGeometry) -> str:
        ...


class S21Calculator(Protocol):
    def calculate(self, config: S21Config) -> S21Result:
        ...


class S21ResultWriter(Protocol):
    def write(self, path: str, result: S21Result) -> None:
        ...
