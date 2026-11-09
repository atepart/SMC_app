"""Import a comparison table: separators, X/Y columns, frequency unit and Y quantity (BUG-024, WP-055)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smcapp.infrastructure.trace_files import (
    DECIMAL_MARKS,
    FREQUENCY_UNITS,
    SEPARATORS,
    Y_QUANTITIES,
    ComparisonTrace,
    DataTable,
    TraceTable,
    convert_trace,
    detect_unit_in_column,
    detect_y_quantity,
    read_data_table,
    select_trace,
)

UNIT_LABELS = {"Hz": "Гц (Hz)", "kHz": "кГц (kHz)", "MHz": "МГц (MHz)", "GHz": "ГГц (GHz)", "THz": "ТГц (THz)"}
PREVIEW_ROWS = 8


def _number(value: float) -> str:
    return f"{value:.6g}"


def _cell(value: float | None) -> str:
    return "" if value is None else _number(value)


class TraceImportDialog(QDialog):
    """Shown on every HFSS/Experiment import (owner's choice, 09.11.2026).

    The column separator and decimal mark are found from the file and can be
    changed; the table is then read again.  X is the frequency column: the unit
    named in its header is preselected; without one nothing is selected and OK
    stays disabled until the user chooses — the program never guesses from the
    numbers, the file extension or the kind.  Y is S21 in dB (left axis) or a
    current (right axis: plain values on a log scale, "Log" values linearly).
    """

    def __init__(self, kind: str, table: DataTable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trace_import_dialog")
        self.setWindowTitle(f"Импорт — {kind}")
        self._kind = kind
        self._table: DataTable | None = table
        self._selection: TraceTable | None = None
        self._source = table.source
        self._auto = (table.separator, table.decimal)
        layout = QVBoxLayout(self)

        self.details_label = QLabel()
        self.details_label.setObjectName("frequency_unit_details")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)

        format_row = QHBoxLayout()
        format_row.addWidget(QLabel("Разделитель столбцов:"))
        self.separator_combo = QComboBox()
        self.separator_combo.setObjectName("trace_import_separator")
        self.separator_combo.addItem(f"Авто ({SEPARATORS[table.separator]})", None)
        for key, title in SEPARATORS.items():
            self.separator_combo.addItem(title, key)
        format_row.addWidget(self.separator_combo)
        format_row.addSpacing(12)
        format_row.addWidget(QLabel("Десятичный разделитель:"))
        self.decimal_combo = QComboBox()
        self.decimal_combo.setObjectName("trace_import_decimal")
        self.decimal_combo.addItem(f"Авто ({DECIMAL_MARKS[table.decimal]})", None)
        for key, title in DECIMAL_MARKS.items():
            self.decimal_combo.addItem(title, key)
        format_row.addWidget(self.decimal_combo)
        format_row.addStretch(1)
        layout.addLayout(format_row)

        self.preview = QTableWidget()
        self.preview.setObjectName("trace_import_preview")
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setMinimumHeight(190)
        layout.addWidget(self.preview, 1)

        self.error_label = QLabel()
        self.error_label.setObjectName("trace_import_error")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #d13438;")
        layout.addWidget(self.error_label)

        x_group = QGroupBox("Горизонтальная ось X — частота")
        x_layout = QVBoxLayout(x_group)
        x_form = QFormLayout()
        self.x_column_combo = QComboBox()
        self.x_column_combo.setObjectName("trace_import_x_column")
        x_form.addRow("Столбец:", self.x_column_combo)
        x_layout.addLayout(x_form)
        self.question_label = QLabel()
        self.question_label.setObjectName("frequency_unit_question")
        self.question_label.setWordWrap(True)
        x_layout.addWidget(self.question_label)
        unit_row = QHBoxLayout()
        self._unit_group = QButtonGroup(self)
        self.unit_buttons: dict[str, QRadioButton] = {}
        for unit in FREQUENCY_UNITS:
            button = QRadioButton(UNIT_LABELS[unit])
            button.setObjectName(f"frequency_unit_{unit}")
            self._unit_group.addButton(button)
            self.unit_buttons[unit] = button
            unit_row.addWidget(button)
            button.toggled.connect(self._refresh)
        unit_row.addStretch(1)
        x_layout.addLayout(unit_row)
        self.result_label = QLabel()
        self.result_label.setObjectName("frequency_unit_result")
        x_layout.addWidget(self.result_label)
        layout.addWidget(x_group)

        y_group = QGroupBox("Вертикальная ось Y")
        y_form = QFormLayout(y_group)
        self.y_column_combo = QComboBox()
        self.y_column_combo.setObjectName("trace_import_y_column")
        y_form.addRow("Столбец:", self.y_column_combo)
        self.quantity_combo = QComboBox()
        self.quantity_combo.setObjectName("trace_import_quantity")
        for key, quantity in Y_QUANTITIES.items():
            self.quantity_combo.addItem(quantity.title, key)
        y_form.addRow("Величина:", self.quantity_combo)
        self.y_result_label = QLabel()
        self.y_result_label.setObjectName("trace_import_y_result")
        self.y_result_label.setWordWrap(True)
        y_form.addRow(self.y_result_label)
        layout.addWidget(y_group)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.separator_combo.currentIndexChanged.connect(self._reread)
        self.decimal_combo.currentIndexChanged.connect(self._reread)
        self.x_column_combo.currentIndexChanged.connect(self._x_column_changed)
        self.y_column_combo.currentIndexChanged.connect(self._y_column_changed)
        self.quantity_combo.currentIndexChanged.connect(self._refresh)

        self._show_table(table)
        self.resize(760, 680)

    # --- public API -------------------------------------------------------

    def selected_unit(self) -> str | None:
        return next((unit for unit, button in self.unit_buttons.items() if button.isChecked()), None)

    def selected_quantity(self) -> str:
        return self.quantity_combo.currentData()

    def selected_columns(self) -> tuple[int, int]:
        return self.x_column_combo.currentIndex(), self.y_column_combo.currentIndex()

    def select_columns(self, x_column: int, y_column: int) -> None:
        self.x_column_combo.setCurrentIndex(x_column)
        self.y_column_combo.setCurrentIndex(y_column)

    def select_quantity(self, key: str) -> None:
        self.quantity_combo.setCurrentIndex(self.quantity_combo.findData(key))

    def select_format(self, separator: str | None, decimal: str | None) -> None:
        self.separator_combo.setCurrentIndex(self.separator_combo.findData(separator))
        self.decimal_combo.setCurrentIndex(self.decimal_combo.findData(decimal))

    def table(self) -> DataTable | None:
        return self._table

    def unit_source(self) -> str:
        unit = self.selected_unit()
        if unit is not None and self._selection is not None and unit == self._selection.header_unit:
            return f"{self._selection.unit_note}, подтверждено"
        return "выбрано при импорте"

    def comparison_trace(self) -> ComparisonTrace:
        """The trace as chosen; only valid while OK is enabled."""
        unit = self.selected_unit()
        if self._selection is None or unit is None:
            raise ValueError("Импорт не готов: выберите столбцы и единицу частоты.")
        return convert_trace(self._selection, unit, self.unit_source(), self.selected_quantity())

    # --- table ------------------------------------------------------------

    def _reread(self) -> None:
        separator = self.separator_combo.currentData()
        decimal = self.decimal_combo.currentData()
        try:
            table = read_data_table(self._source, separator, decimal)
        except (OSError, ValueError) as exc:
            self._table = None
            self._selection = None
            self.preview.clear()
            self.preview.setRowCount(0)
            self.preview.setColumnCount(0)
            self.error_label.setText(str(exc))
            self.details_label.setText(f"Файл: {self._source.name}\nТаблица не прочитана с выбранными разделителями.")
            self._refresh()
            return
        self._show_table(table)

    def _show_table(self, table: DataTable) -> None:
        previous = self.selected_columns() if self._table is not None and self.x_column_combo.count() else None
        self._table = table
        self.error_label.setText("")
        header = table.header if table.header is not None else "нет"
        auto = "" if (table.separator, table.decimal) == self._auto else " (задано вручную)"
        self.details_label.setText(
            f"Файл: {table.source.name}\n"
            f"Заголовок: {header}\n"
            f"Строк с числами: {len(table.rows)}, столбцов: {len(table.columns)}; "
            f"разделитель: {SEPARATORS[table.separator]}, десятичный: {DECIMAL_MARKS[table.decimal]}{auto}"
        )

        names = [f"{index + 1}: {name}" for index, name in enumerate(table.columns)]
        self.preview.clear()
        self.preview.setColumnCount(len(names))
        self.preview.setHorizontalHeaderLabels(names)
        rows = table.rows[:PREVIEW_ROWS]
        self.preview.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                self.preview.setItem(row_index, column, QTableWidgetItem(_cell(value)))
        self.preview.resizeColumnsToContents()

        for combo in (self.x_column_combo, self.y_column_combo):
            blocked = combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.blockSignals(blocked)
        x_column, y_column = previous if previous and max(previous) < len(names) else self._default_columns(table)
        for combo, index in ((self.x_column_combo, x_column), (self.y_column_combo, y_column)):
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(blocked)
        self._x_column_changed()
        if previous is None:
            self._y_column_changed()

    @staticmethod
    def _default_columns(table: DataTable) -> tuple[int, int]:
        width = len(table.columns)
        x_column = next(
            (index for index in range(width) if detect_unit_in_column(table.column_header(index) or "")[0]), 0
        )
        others = [index for index in range(width) if index != x_column]
        y_column = next((index for index in others if detect_y_quantity(table.column_header(index))), others[0])
        return x_column, y_column

    def _x_column_changed(self) -> None:
        self._select()
        unit = self._selection.header_unit if self._selection is not None else None
        self._unit_group.setExclusive(False)
        for name, button in self.unit_buttons.items():
            blocked = button.blockSignals(True)
            button.setChecked(name == unit)
            button.blockSignals(blocked)
        self._unit_group.setExclusive(True)
        self._refresh()

    def _y_column_changed(self) -> None:
        self._select()
        if self._table is not None:
            guessed = detect_y_quantity(self._table.column_header(self.y_column_combo.currentIndex()))
            if guessed is not None:
                blocked = self.quantity_combo.blockSignals(True)
                self.select_quantity(guessed)
                self.quantity_combo.blockSignals(blocked)
        self._refresh()

    def _select(self) -> None:
        self._selection = None
        if self._table is None:
            return
        x_column, y_column = self.selected_columns()
        try:
            self._selection = select_trace(self._table, x_column, y_column)
        except ValueError as exc:
            self.error_label.setText(str(exc))
        else:
            self.error_label.setText("")

    # --- summary ----------------------------------------------------------

    def _refresh(self) -> None:
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        selection = self._selection
        if selection is None:
            self.question_label.setText("Таблица не прочитана или выбраны одинаковые столбцы.")
            self.result_label.setText("")
            self.y_result_label.setText("")
            ok_button.setEnabled(False)
            return

        if selection.header_unit is None:
            self.question_label.setText(
                "Не удалось однозначно определить единицу частоты "
                f"({selection.unit_note}). В каких единицах записан столбец «{selection.x_name}»?"
            )
        else:
            self.question_label.setText(
                f"В каких единицах записан столбец «{selection.x_name}»? "
                f"Единица {selection.header_unit} — {selection.unit_note}."
            )
        unit = self.selected_unit()
        first, last = selection.frequencies[0], selection.frequencies[-1]
        if unit is None:
            self.result_label.setText("Выберите единицу, чтобы продолжить.")
        else:
            factor = FREQUENCY_UNITS[unit]
            self.result_label.setText(
                f"{_number(first)} … {_number(last)} {unit} → {_number(first * factor)} … {_number(last * factor)} GHz"
            )

        quantity = Y_QUANTITIES[self.selected_quantity()]
        values = selection.coefficients
        lines = [
            f"{_number(min(values))} … {_number(max(values))} ({len(values)} точек) — {quantity.placement}.",
        ]
        if selection.skipped_rows:
            lines.append(f"Строк с пустой ячейкой в X или Y пропущено: {selection.skipped_rows}.")
        usable = True
        if quantity.axis == "right" and not quantity.logarithmic:
            non_positive = sum(value <= 0 for value in values)
            if non_positive == len(values):
                lines.append("Все значения ≤ 0: на логарифмической шкале показать нечего. Выберите «Log» или dB.")
                usable = False
            elif non_positive:
                lines.append(f"Значений ≤ 0 не будет на логарифмической шкале: {non_positive}.")
        self.y_result_label.setText("\n".join(lines))
        ok_button.setEnabled(unit is not None and usable)
