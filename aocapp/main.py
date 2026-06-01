"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from aocapp.api import IOService
from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.s21_calculator import S21FileWriter, build_default_s21_calculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import run_app


def run_s21_smoke_test() -> None:
    """Run a small S21 calculation for frozen-app diagnostics."""
    s21_calculator = build_default_s21_calculator()
    s21_writer = S21FileWriter(io_service=IOService())
    s21_use_case = CalculateS21UseCase(calculator=s21_calculator, writer=s21_writer)
    config = S21Config(s21_freq_start_ghz=100.0, s21_freq_stop_ghz=125.0, s21_freq_step_ghz=5.0)
    output_path = str(Path.home() / "Documents" / "SMC_app" / "smoke_S21_dB.tab")
    result = s21_use_case.execute(config, output_path, progress_callback=print)
    print(
        f"SMOKE_S21_OK count={result.count} first={result.s21_db[0]:.6g} "
        f"last={result.s21_db[-1]:.6g} output={output_path}"
    )


def main() -> None:
    if "--smoke-s21" in sys.argv:
        run_s21_smoke_test()
        return

    calculator = IntegratedStructureCalculator()
    renderer = SvgRendererImpl()
    use_case = GenerateStructureUseCase(calculator=calculator, renderer=renderer)
    s21_calculator = build_default_s21_calculator()
    s21_writer = S21FileWriter(io_service=IOService())
    s21_use_case = CalculateS21UseCase(calculator=s21_calculator, writer=s21_writer)
    run_app(use_case, s21_use_case)


if __name__ == "__main__":
    main()
