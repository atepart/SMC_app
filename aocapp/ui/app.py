"""PySide6 UI for parameter input and SVG preview."""

from __future__ import annotations

from dataclasses import dataclass, replace
import sys
from typing import Dict

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPainter, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.domain.models import StructureParams
from aocapp.domain.s21_models import S21Config


class SvgGraphicsView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._svg_item: QGraphicsSvgItem | None = None
        self._renderer: QSvgRenderer | None = None

    def set_svg(self, svg_text: str) -> None:
        renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        item = QGraphicsSvgItem()
        item.setSharedRenderer(renderer)

        scene = self.scene()
        if scene is None:
            scene = QGraphicsScene(self)
            self.setScene(scene)
        scene.clear()
        scene.addItem(item)
        scene.setSceneRect(item.boundingRect())

        self._renderer = renderer
        self._svg_item = item
        self.reset_view()

    def reset_view(self) -> None:
        if self._svg_item is None:
            return
        self.fitInView(self._svg_item.boundingRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() == 0:
            return
        zoom_in = 1.15
        zoom_out = 1 / zoom_in
        factor = zoom_in if event.angleDelta().y() > 0 else zoom_out
        self.scale(factor, factor)
        event.accept()


@dataclass
class InputField:
    label: str
    default: float
    minimum: float = 0.01
    maximum: float = 10000.0
    step: float = 0.5
    decimals: int = 2


class MainWindow(QMainWindow):
    def __init__(self, use_case: GenerateStructureUseCase, s21_use_case: CalculateS21UseCase) -> None:
        super().__init__()
        self._use_case = use_case
        self._s21_use_case = s21_use_case
        self.setWindowTitle("Structure Calculator")

        self._view = SvgGraphicsView()
        self._plot = pg.PlotWidget()
        self._inputs: Dict[str, QDoubleSpinBox] = {}
        self._s21_inputs: Dict[str, QDoubleSpinBox] = {}
        self._s21_output: QLineEdit | None = None
        self._s21_status: QLabel | None = None
        self._log_view: QPlainTextEdit | None = None
        self._s21_defaults = S21Config()

        self._configure_plot()
        self._build_ui()
        self._update_svg()

    def _build_ui(self) -> None:
        container = QWidget(self)
        layout = QHBoxLayout(container)

        splitter = QSplitter(Qt.Horizontal, container)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)
        self.setCentralWidget(container)

    def _build_controls(self) -> QWidget:
        panel = QWidget(self)
        vbox = QVBoxLayout(panel)

        title = QLabel("Parameters (um)")
        title.setStyleSheet("font-weight: bold;")
        vbox.addWidget(title)

        form = QFormLayout()
        fields = {
            "left_taper_um": InputField("Left taper", 12.0),
            "center_length_um": InputField("Center length", 30.0),
            "right_taper_um": InputField("Right taper", 14.0),
            "body_height_um": InputField("Body height", 60.0),
            "neck_height_um": InputField("Neck height", 20.0),
            "arm_length_um": InputField("Arm length", 53.0),
        }

        for key, field in fields.items():
            spin = QDoubleSpinBox()
            spin.setDecimals(field.decimals)
            spin.setRange(field.minimum, field.maximum)
            spin.setSingleStep(field.step)
            spin.setValue(field.default)
            spin.setSuffix(" um")
            self._inputs[key] = spin
            form.addRow(field.label, spin)

        vbox.addLayout(form)

        button_row = QHBoxLayout()
        calc_button = QPushButton("Calculate")
        calc_button.clicked.connect(self._update_svg)
        button_row.addWidget(calc_button)

        reset_button = QPushButton("Reset view")
        reset_button.clicked.connect(self._view.reset_view)
        button_row.addWidget(reset_button)

        vbox.addLayout(button_row)

        vbox.addSpacing(8)

        s21_title = QLabel("S21 calculation")
        s21_title.setStyleSheet("font-weight: bold;")
        vbox.addWidget(s21_title)

        s21_form = QFormLayout()
        s21_fields = {
            "s21_freq_start_ghz": InputField("Start freq", self._s21_defaults.s21_freq_start_ghz, step=5.0),
            "s21_freq_stop_ghz": InputField("Stop freq", self._s21_defaults.s21_freq_stop_ghz, step=5.0),
            "s21_freq_step_ghz": InputField("Step", self._s21_defaults.s21_freq_step_ghz, step=5.0),
        }

        for key, field in s21_fields.items():
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(0.01, 10000.0)
            spin.setSingleStep(field.step)
            spin.setValue(field.default)
            spin.setSuffix(" GHz")
            self._s21_inputs[key] = spin
            s21_form.addRow(field.label, spin)

        self._s21_output = QLineEdit("S21_dB.tab")
        s21_form.addRow("Output file", self._s21_output)
        vbox.addLayout(s21_form)

        s21_button_row = QHBoxLayout()
        s21_button = QPushButton("Run S21")
        s21_button.clicked.connect(self._run_s21)
        s21_button_row.addWidget(s21_button)
        vbox.addLayout(s21_button_row)

        self._s21_status = QLabel("S21 mirrors backend/main.py. SVG preview is independent from S21 parameters.")
        self._s21_status.setStyleSheet("color: #555;")
        vbox.addWidget(self._s21_status)

        hint = QLabel("Wheel to zoom, drag to pan")
        hint.setStyleSheet("color: #555;")
        vbox.addWidget(hint)
        vbox.addStretch(1)

        return panel

    def _build_preview(self) -> QWidget:
        panel = QWidget(self)
        vbox = QVBoxLayout(panel)
        vbox.addWidget(self._view, stretch=3)

        plot_title = QLabel("S21 Response")
        plot_title.setStyleSheet("font-weight: bold;")
        vbox.addWidget(plot_title)
        vbox.addWidget(self._plot, stretch=2)

        log_title = QLabel("Calculation log")
        log_title.setStyleSheet("font-weight: bold;")
        vbox.addWidget(log_title)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setPlaceholderText("Run S21 to see calculation messages and warnings.")
        self._log_view.setMinimumHeight(150)
        vbox.addWidget(self._log_view, stretch=1)
        return panel

    def _configure_plot(self) -> None:
        pg.setConfigOption("background", "#f7f8fb")
        pg.setConfigOption("foreground", "#1f1f1f")
        self._plot.setTitle("S21 vs Frequency")
        self._plot.setLabel("left", "S21", units="dB")
        self._plot.setLabel("bottom", "Frequency", units="GHz")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)

    def _update_svg(self) -> None:
        try:
            params = StructureParams(
                left_taper_um=self._inputs["left_taper_um"].value(),
                center_length_um=self._inputs["center_length_um"].value(),
                right_taper_um=self._inputs["right_taper_um"].value(),
                body_height_um=self._inputs["body_height_um"].value(),
                neck_height_um=self._inputs["neck_height_um"].value(),
                arm_length_um=self._inputs["arm_length_um"].value(),
            )
            svg = self._use_case.execute(params)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        self._view.set_svg(svg)

    def _run_s21(self) -> None:
        if self._s21_output is None or self._s21_status is None:
            return
        try:
            self._s21_status.setText("Computing S21...")
            self._set_log_messages(
                [
                    "Starting S21 calculation.",
                    "Using backend/main.py defaults.",
                    "SVG preview parameters do not alter the S21 network.",
                ]
            )
            QApplication.processEvents()
            config = replace(
                self._s21_defaults,
                s21_freq_start_ghz=self._s21_inputs["s21_freq_start_ghz"].value(),
                s21_freq_stop_ghz=self._s21_inputs["s21_freq_stop_ghz"].value(),
                s21_freq_step_ghz=self._s21_inputs["s21_freq_step_ghz"].value(),
            )
            output_path = self._s21_output.text().strip()
            result = self._s21_use_case.execute(config, output_path if output_path else None)
        except ValueError as exc:
            self._append_log_message(f"ERROR: {exc}")
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        self._update_s21_plot(result.frequencies_ghz, result.s21_db)
        self._set_log_messages(result.log_messages)

        if output_path:
            self._s21_status.setText(f"Computed {result.count} points, saved to {output_path}")
        else:
            self._s21_status.setText(f"Computed {result.count} points")

    def _update_s21_plot(self, frequencies, s21_db) -> None:
        self._plot.clear()
        pen = pg.mkPen(color="#1f77b4", width=2)
        self._plot.plot(frequencies, s21_db, pen=pen, symbol="o", symbolSize=5, symbolBrush="#1f77b4")

    def _set_log_messages(self, messages: list[str]) -> None:
        if self._log_view is None:
            return
        self._log_view.setPlainText("\n".join(messages))

    def _append_log_message(self, message: str) -> None:
        if self._log_view is None:
            return
        current = self._log_view.toPlainText()
        if current:
            self._log_view.setPlainText(f"{current}\n{message}")
        else:
            self._log_view.setPlainText(message)


def run_app(use_case: GenerateStructureUseCase, s21_use_case: CalculateS21UseCase) -> None:
    app = QApplication(sys.argv)
    window = MainWindow(use_case, s21_use_case)
    window.resize(1100, 700)
    window.show()
    app.exec()
