"""Application entry point."""

from __future__ import annotations

from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import OctagonArmCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import run_app


def main() -> None:
    calculator = OctagonArmCalculator()
    renderer = SvgRendererImpl()
    use_case = GenerateStructureUseCase(calculator=calculator, renderer=renderer)
    run_app(use_case)


if __name__ == "__main__":
    main()
