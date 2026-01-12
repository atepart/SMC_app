"""Application entry point."""

from __future__ import annotations

from aocapp.api import IOService
from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import OctagonArmCalculator
from aocapp.infrastructure.s21_calculator import S21FileWriter, build_default_s21_calculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import run_app


def main() -> None:
    calculator = OctagonArmCalculator()
    renderer = SvgRendererImpl()
    use_case = GenerateStructureUseCase(calculator=calculator, renderer=renderer)
    s21_calculator = build_default_s21_calculator()
    s21_writer = S21FileWriter(io_service=IOService())
    s21_use_case = CalculateS21UseCase(calculator=s21_calculator, writer=s21_writer)
    run_app(use_case, s21_use_case)


if __name__ == "__main__":
    main()
