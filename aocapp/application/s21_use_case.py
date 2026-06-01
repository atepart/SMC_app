"""Use case for computing S21 results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aocapp.domain.ports import S21Calculator, S21ResultWriter
from aocapp.domain.s21_models import S21Config, S21Result


@dataclass(frozen=True)
class CalculateS21UseCase:
    calculator: S21Calculator
    writer: S21ResultWriter

    def execute(
        self,
        config: S21Config,
        output_path: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> S21Result:
        config.validate()
        result = self.calculator.calculate(config, progress_callback=progress_callback)
        if output_path:
            self.writer.write(output_path, result)
        return result
