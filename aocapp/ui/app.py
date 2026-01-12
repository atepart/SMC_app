"""PySide6 UI for parameter input and SVG preview."""

from __future__ import annotations

from dataclasses import dataclass
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
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.domain.models import StructureParams


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
    def __init__(self, use_case: GenerateStructureUseCase) -> None:
        super().__init__()
        self._use_case = use_case
        self.setWindowTitle("Structure Calculator")

        self._view = SvgGraphicsView()
        self._inputs: Dict[str, QDoubleSpinBox] = {}

        self._build_ui()
        self._update_svg()

    def _build_ui(self) -> None:
        container = QWidget(self)
        layout = QHBoxLayout(container)

        splitter = QSplitter(Qt.Horizontal, container)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._view)
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
        vbox.addStretch(1)

        hint = QLabel("Wheel to zoom, drag to pan")
        hint.setStyleSheet("color: #555;")
        vbox.addWidget(hint)

        return panel

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
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        self._view.set_svg(svg)


def run_app(use_case: GenerateStructureUseCase) -> None:
    app = QApplication(sys.argv)
    window = MainWindow(use_case)
    window.resize(1100, 700)
    window.show()
    app.exec()
