"""Ask in which unit the frequencies of an imported comparison table are written (BUG-024)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from smcapp.infrastructure.trace_files import FREQUENCY_UNITS, TraceTable

UNIT_LABELS = {"Hz": "Гц (Hz)", "kHz": "кГц (kHz)", "MHz": "МГц (MHz)", "GHz": "ГГц (GHz)", "THz": "ТГц (THz)"}


def _number(value: float) -> str:
    return f"{value:.6g}"


class FrequencyUnitDialog(QDialog):
    """Shown on every HFSS/Experiment import (owner's choice, 09.11.2026).

    The unit named in the header of the frequency column is preselected; without
    one nothing is selected and OK stays disabled until the user chooses — the
    program never guesses from the numbers, the file extension or the kind.
    """

    def __init__(self, kind: str, table: TraceTable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("frequency_unit_dialog")
        self.setWindowTitle(f"Единицы частоты — {kind}")
        self._table = table
        layout = QVBoxLayout(self)

        if table.header_unit is None:
            question = (
                "Не удалось однозначно определить единицу частоты "
                f"({table.unit_note}). В каких единицах записаны значения первого столбца?"
            )
        else:
            question = (
                f"В каких единицах записаны значения первого столбца? Единица {table.header_unit} — {table.unit_note}."
            )
        intro = QLabel(question)
        intro.setWordWrap(True)
        intro.setObjectName("frequency_unit_question")
        layout.addWidget(intro)

        values = table.frequencies
        sample = ", ".join(_number(value) for value in values[:4]) + (", …" if len(values) > 4 else "")
        details = QLabel(
            f"Файл: {table.source.name}\n"
            f"Заголовок: {table.header if table.header is not None else 'нет'}\n"
            f"Первые значения: {sample}\n"
            f"Диапазон: {_number(values[0])} … {_number(values[-1])} ({len(values)} точек)"
        )
        details.setObjectName("frequency_unit_details")
        details.setWordWrap(True)
        layout.addWidget(details)

        row = QHBoxLayout()
        self._buttons = QButtonGroup(self)
        self.unit_buttons: dict[str, QRadioButton] = {}
        for unit in FREQUENCY_UNITS:
            button = QRadioButton(UNIT_LABELS[unit])
            button.setObjectName(f"frequency_unit_{unit}")
            self._buttons.addButton(button)
            self.unit_buttons[unit] = button
            row.addWidget(button)
            button.toggled.connect(self._refresh)
        row.addStretch(1)
        layout.addLayout(row)

        self.result_label = QLabel()
        self.result_label.setObjectName("frequency_unit_result")
        layout.addWidget(self.result_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        if table.header_unit is not None:
            self.unit_buttons[table.header_unit].setChecked(True)
        self._refresh()

    def selected_unit(self) -> str | None:
        return next((unit for unit, button in self.unit_buttons.items() if button.isChecked()), None)

    def unit_source(self) -> str:
        unit = self.selected_unit()
        if unit is not None and unit == self._table.header_unit:
            return f"{self._table.unit_note}, подтверждено"
        return "выбрано при импорте"

    def _refresh(self) -> None:
        unit = self.selected_unit()
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(unit is not None)
        if unit is None:
            self.result_label.setText("Выберите единицу, чтобы продолжить.")
            return
        factor = FREQUENCY_UNITS[unit]
        first, last = self._table.frequencies[0], self._table.frequencies[-1]
        self.result_label.setText(
            f"{_number(first)} … {_number(last)} {unit} → {_number(first * factor)} … {_number(last * factor)} GHz"
        )
