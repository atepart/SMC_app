"""Example usage of the S21 calculation use case."""

from __future__ import annotations

from aocapp.api import IOService
from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.s21_calculator import S21FileWriter, build_default_s21_calculator


def main() -> None:
    calculator = build_default_s21_calculator()
    writer = S21FileWriter(io_service=IOService())
    use_case = CalculateS21UseCase(calculator=calculator, writer=writer)

    config = S21Config()
    result = use_case.execute(config, output_path="S21_dB.tab")
    print(f"Computed {result.count} points")


if __name__ == "__main__":
    main()
