"""PySide6 UI for grouped parameter input and SVG preview."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Dict

from PySide6.QtCore import QByteArray, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QPainter, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QStyle,
)

import pyqtgraph as pg

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.application.version import __version__
from aocapp.domain.s21_models import S21Config


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def _default_s21_output_path() -> Path:
    return Path.home() / "Documents" / "SMC_app" / "S21_dB.tab"


class S21Worker(QObject):
    log_message = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, use_case: CalculateS21UseCase, config: S21Config, output_path: str | None) -> None:
        super().__init__()
        self._use_case = use_case
        self._config = config
        self._output_path = output_path

    @Slot()
    def run(self) -> None:
        try:
            result = self._use_case.execute(
                self._config,
                self._output_path,
                progress_callback=self.log_message.emit,
            )
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.finished.emit(result)


class SvgGraphicsView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._svg_item: QGraphicsSvgItem | None = None
        self._renderer: QSvgRenderer | None = None
        self._zoom_level = 0

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
        self.resetTransform()
        self._zoom_level = 0
        self.fitInView(self._svg_item.boundingRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() == 0:
            return
        zoom_in = 1.08
        zoom_out = 1 / zoom_in
        direction = 1 if event.angleDelta().y() > 0 else -1
        if direction > 0 and self._zoom_level >= 24:
            event.accept()
            return
        if direction < 0 and self._zoom_level <= -12:
            event.accept()
            return
        factor = zoom_in if direction > 0 else zoom_out
        self.scale(factor, factor)
        self._zoom_level += direction
        event.accept()


class MainWindow(QMainWindow):
    _material_sync_map = {
        "sigma0_top": "sigma0_bot",
        "tc_top_k": "tc_bot_k",
        "alpha_top": "alpha_bot",
    }

    def __init__(self, use_case: GenerateStructureUseCase, s21_use_case: CalculateS21UseCase) -> None:
        super().__init__()
        self._use_case = use_case
        self._s21_use_case = s21_use_case
        self.setWindowTitle(f"AOC Structure Calculator {__version__}")
        self.setWindowIcon(QIcon(str(_resource_path("assets", "aocapp-icon.png"))))

        self._view = SvgGraphicsView()
        self._plot = pg.PlotWidget()
        self._config_inputs: Dict[str, QDoubleSpinBox] = {}
        self._s21_output: QLineEdit | None = None
        self._s21_status: QLabel | None = None
        self._log_view: QPlainTextEdit | None = None
        self._run_s21_button: QPushButton | None = None
        self._same_materials_checkbox: QCheckBox | None = None
        self._s21_thread: QThread | None = None
        self._s21_worker: S21Worker | None = None
        self._defaults = S21Config()

        self._configure_plot()
        self._build_ui()
        self._apply_material_sync()
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
        outer = QVBoxLayout(panel)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        vbox = QVBoxLayout(inner)

        title = QLabel("Grouped Parameters")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        vbox.addWidget(title)

        subtitle = QLabel(
            "Preview and S21 now use the same grouped configuration. Tooltips describe each backend parameter."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #555;")
        vbox.addWidget(subtitle)

        fields_by_group = {group: [] for group in S21Config.GROUP_ORDER}
        for field_info in S21Config.ui_fields():
            fields_by_group.setdefault(field_info.group, []).append(field_info)

        for group_name in S21Config.GROUP_ORDER:
            group_fields = fields_by_group.get(group_name, [])
            if not group_fields:
                continue
            box = QGroupBox(group_name)
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignLeft)

            if group_name == "EL2 Material":
                checkbox = QCheckBox("Use the same material as EL1")
                checkbox.setChecked(True)
                checkbox.toggled.connect(self._on_same_materials_toggled)
                self._same_materials_checkbox = checkbox
                form.addRow("", checkbox)

            for field_info in group_fields:
                spin = self._create_spinbox(field_info.name, field_info)
                label = QLabel(field_info.label)
                label.setToolTip(field_info.description)
                spin.setToolTip(field_info.description)
                self._config_inputs[field_info.name] = spin
                form.addRow(label, spin)

            vbox.addWidget(box)

        controls_box = QGroupBox("Actions")
        controls_layout = QVBoxLayout(controls_box)

        self._s21_output = QLineEdit(str(_default_s21_output_path()))
        self._s21_output.setToolTip("Optional output file for the computed S21 tabulation.")
        output_form = QFormLayout()
        output_form.addRow("Output file", self._s21_output)
        controls_layout.addLayout(output_form)

        button_row = QHBoxLayout()
        preview_button = QPushButton("Update Preview")
        preview_button.clicked.connect(self._update_svg)
        button_row.addWidget(preview_button)
        controls_layout.addLayout(button_row)

        run_button = QPushButton("Run S21")
        run_button.clicked.connect(self._run_s21)
        self._run_s21_button = run_button
        controls_layout.addWidget(run_button)

        self._s21_status = QLabel("The grouped preview mirrors the new backend parameter model.")
        self._s21_status.setWordWrap(True)
        self._s21_status.setStyleSheet("color: #555;")
        controls_layout.addWidget(self._s21_status)

        hint = QLabel("Wheel to zoom, drag to pan, Home returns to the initial fitted view.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")
        controls_layout.addWidget(hint)

        vbox.addWidget(controls_box)
        vbox.addStretch(1)

        inner.setLayout(vbox)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return panel

    def _build_preview(self) -> QWidget:
        panel = QWidget(self)
        vbox = QVBoxLayout(panel)
        toolbar = QHBoxLayout()
        preview_title = QLabel("SVG Preview")
        preview_title.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(preview_title)
        toolbar.addStretch(1)
        home_button = QPushButton("Home")
        home_button.setToolTip("Return the SVG viewer to the initial fitted view.")
        home_button.setIcon(self.style().standardIcon(QStyle.SP_DirHomeIcon))
        home_button.clicked.connect(self._view.reset_view)
        toolbar.addWidget(home_button)
        vbox.addLayout(toolbar)
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
        self._log_view.setPlaceholderText("Run S21 to inspect intermediate backend messages.")
        self._log_view.setMinimumHeight(150)
        vbox.addWidget(self._log_view, stretch=1)
        return panel

    def _create_spinbox(self, name: str, field_info) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        scale = S21Config.field_scale(name)
        default_value = getattr(self._defaults, name)
        if default_value is None:
            default_value = 0.0
        spin.setDecimals(field_info.decimals)
        spin.setRange(field_info.minimum, field_info.maximum)
        spin.setSingleStep(field_info.step)
        spin.setValue(default_value * scale)
        spin.setSuffix(field_info.suffix)
        if name in self._material_sync_map:
            spin.valueChanged.connect(self._apply_material_sync)
        return spin

    def _configure_plot(self) -> None:
        pg.setConfigOption("background", "#ffffff")
        pg.setConfigOption("foreground", "#7f7f7f")
        self._plot.setBackground("#ffffff")
        self._plot.setTitle("S21 vs Frequency")
        self._plot.setLabel("left", "S21", units="dB")
        self._plot.setLabel("bottom", "Frequency", units="GHz")
        self._plot.showGrid(x=True, y=True, alpha=0.10)
        self._plot.setMenuEnabled(False)
        self._plot.getPlotItem().setContentsMargins(12, 12, 12, 12)
        axis_pen = pg.mkPen("#7f7f7f", width=1)
        for axis_name in ("left", "bottom"):
            axis = self._plot.getPlotItem().getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)

    def _build_config(self) -> S21Config:
        values = dict(self._defaults.__dict__)
        for name, spin in self._config_inputs.items():
            scale = S21Config.field_scale(name)
            values[name] = spin.value() / scale

        if self._same_materials_checkbox is not None and self._same_materials_checkbox.isChecked():
            for top_name, bot_name in self._material_sync_map.items():
                values[bot_name] = values[top_name]

        return S21Config(**values)

    def _apply_material_sync(self) -> None:
        if self._same_materials_checkbox is None or not self._same_materials_checkbox.isChecked():
            return
        for top_name, bot_name in self._material_sync_map.items():
            top_spin = self._config_inputs[top_name]
            bot_spin = self._config_inputs[bot_name]
            blocked = bot_spin.blockSignals(True)
            bot_spin.setValue(top_spin.value())
            bot_spin.blockSignals(blocked)
            bot_spin.setEnabled(False)

    def _on_same_materials_toggled(self, checked: bool) -> None:
        for bot_name in self._material_sync_map.values():
            self._config_inputs[bot_name].setEnabled(not checked)
        if checked:
            self._apply_material_sync()

    def _update_svg(self) -> None:
        try:
            config = self._build_config()
            svg = self._use_case.execute(config)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        self._view.set_svg(svg)

    def _run_s21(self) -> None:
        if self._s21_output is None or self._s21_status is None:
            return
        if self._s21_thread is not None:
            self._append_log_message("S21 calculation is already running.")
            return
        try:
            config = self._build_config()
        except ValueError as exc:
            self._append_log_message(f"ERROR: {exc}")
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        output_path = self._s21_output.text().strip()
        self._plot.clear()
        self._s21_status.setText("Computing S21...")
        self._set_log_messages(
            [
                "Starting grouped S21 calculation.",
                "Using the same parameter set as the SVG preview.",
                "EL1/EL2 material sync is applied before the backend call when enabled.",
            ]
        )
        if self._run_s21_button is not None:
            self._run_s21_button.setEnabled(False)

        self._s21_thread = QThread(self)
        self._s21_worker = S21Worker(self._s21_use_case, config, output_path if output_path else None)
        self._s21_worker.moveToThread(self._s21_thread)
        self._s21_thread.started.connect(self._s21_worker.run)
        self._s21_worker.log_message.connect(self._on_s21_progress)
        self._s21_worker.finished.connect(self._on_s21_finished)
        self._s21_worker.failed.connect(self._on_s21_failed)
        self._s21_worker.finished.connect(self._s21_thread.quit)
        self._s21_worker.failed.connect(self._s21_thread.quit)
        self._s21_worker.finished.connect(self._s21_worker.deleteLater)
        self._s21_worker.failed.connect(self._s21_worker.deleteLater)
        self._s21_thread.finished.connect(self._on_s21_thread_finished)
        self._s21_thread.finished.connect(self._s21_thread.deleteLater)
        self._s21_thread.start()

    @Slot(object)
    def _on_s21_finished(self, result) -> None:
        self._update_s21_plot(result.frequencies_ghz, result.s21_db)
        self._set_log_messages(result.log_messages)

        output_path = self._s21_output.text().strip() if self._s21_output is not None else ""
        if output_path:
            self._s21_status.setText(f"Computed {result.count} points, saved to {output_path}")
        else:
            self._s21_status.setText(f"Computed {result.count} points")

    @Slot(str)
    def _on_s21_progress(self, message: str) -> None:
        self._append_log_message(message)
        if self._s21_status is not None:
            self._s21_status.setText(message)

    @Slot(str)
    def _on_s21_failed(self, error: str) -> None:
        self._append_log_message("ERROR: S21 calculation failed.")
        self._append_log_message(error)
        if self._s21_status is not None:
            self._s21_status.setText("S21 calculation failed")
        QMessageBox.critical(self, "S21 calculation failed", error)

    @Slot()
    def _on_s21_thread_finished(self) -> None:
        self._s21_thread = None
        self._s21_worker = None
        if self._run_s21_button is not None:
            self._run_s21_button.setEnabled(True)

    def _update_s21_plot(self, frequencies, s21_db) -> None:
        self._plot.clear()
        pen = pg.mkPen(color="#1f77b4", width=2)
        self._plot.plot(frequencies, s21_db, pen=pen, symbol="o", symbolSize=4, symbolBrush="#ff7f0e", symbolPen="#1f77b4")

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
    window.resize(1440, 920)
    window.show()
    app.exec()
