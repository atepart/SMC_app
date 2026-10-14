"""PySide6 UI for grouped parameter input and SVG preview."""

from __future__ import annotations

import contextlib
import math
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Dict

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QByteArray, QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QImage, QImageWriter, QPainter, QWheelEvent
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
    QStyle,
    QVBoxLayout,
    QWidget,
)
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.application.version import REPO_SLUG, __version__
from aocapp.domain.s21_models import S21Config
from aocapp.domain.transformers import ELEMENT_NUMBERS, derive_transformer_steps
from aocapp.infrastructure.design_files import DesignFileService
from aocapp.infrastructure.trace_files import ComparisonTrace, TraceFileReader
from aocapp.ui.update_dialogs import DownloadReleaseWorker, FetchReleasesWorker, ReleasePickerDialog

CURRENT_DOCK_LAYOUT_VERSION = 1


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def _default_s21_output_path() -> Path:
    return Path.home() / "Documents" / "SMC_app" / "S21_dB.tab"


def _default_s21_output_directory() -> Path:
    path = Path(QSettings().value("Files/s21_output_directory", str(_default_s21_output_path().parent), type=str))
    return path if path.is_absolute() else _default_s21_output_path().parent


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
        self._fit_width = False

    def set_svg(self, svg_text: str, *, fit_width: bool = False) -> None:
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
        self._fit_width = fit_width
        self.reset_view()

    def reset_view(self) -> None:
        if self._svg_item is None:
            return
        self.resetTransform()
        self._zoom_level = 0
        self._fit_default(reset_scroll=True)

    def _fit_default(self, *, reset_scroll: bool = False) -> None:
        if self._svg_item is None:
            return
        if self._fit_width:
            scroll = self.verticalScrollBar()
            fraction = scroll.value() / max(1, scroll.maximum())
            self.resetTransform()
            factor = max(1, self.viewport().width() - 24) / self._svg_item.boundingRect().width()
            self.scale(factor, factor)
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())
            scroll.setValue(scroll.minimum() if reset_scroll else round(fraction * scroll.maximum()))
        else:
            self.fitInView(self._svg_item.boundingRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:
        """Keep the initial drawing fitted while QtAds settles dock sizes.

        QtAds performs several resizes after the SVG is first loaded.  Refitting
        only while ``_zoom_level == 0`` handles those layout changes without
        destroying a scale explicitly chosen by the user with the wheel.
        """
        super().resizeEvent(event)
        if self._svg_item is not None and self._zoom_level == 0:
            self._fit_default()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._fit_width and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
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


class SafeDoubleSpinBox(QDoubleSpinBox):
    """Spin box whose wheel is armed only by an explicit mouse click.

    Merely moving the cursor over a long parameter form must keep scrolling the
    form.  A click arms wheel editing for this field until focus leaves it;
    arrow buttons and keyboard input continue to work as normal.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_armed = False
        self.setLocale(QtCore.QLocale.c())
        self.setKeyboardTracking(False)

    def validate(self, text: str, pos: int):
        state, _, _ = super().validate(text.replace(",", "."), pos)
        return state, text, pos

    def valueFromText(self, text: str) -> float:  # noqa: N802 - Qt API
        return super().valueFromText(text.replace(",", "."))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._wheel_armed = True
        super().mousePressEvent(event)

    def focusOutEvent(self, event) -> None:
        self._wheel_armed = False
        super().focusOutEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._wheel_armed and self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class FrequencyAxisItem(pg.AxisItem):
    """Frequency axis that switches from GHz to THz instead of showing kGHz."""

    def __init__(self, orientation: str = "bottom") -> None:
        super().__init__(orientation=orientation)
        self._display_factor = 1.0
        self._display_unit = "GHz"
        self.enableAutoSIPrefix(False)
        self.setLabel("Frequency", units=self._display_unit)

    def set_display_range(self, lower_ghz: float, upper_ghz: float) -> None:
        """Choose the engineering unit from the visible data range."""
        use_thz = max(abs(lower_ghz), abs(upper_ghz)) >= 1000.0
        factor = 1e-3 if use_thz else 1.0
        unit = "THz" if use_thz else "GHz"
        if factor == self._display_factor:
            return
        self._display_factor = factor
        self._display_unit = unit
        self.setLabel("Frequency", units=unit)
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - Qt/pyqtgraph API
        """Format GHz data coordinates in the selected display unit."""
        display_spacing = abs(spacing * scale * self._display_factor)
        decimals = 0 if display_spacing <= 0 else max(0, min(6, math.ceil(-math.log10(display_spacing))))
        return [f"{value * scale * self._display_factor:.{decimals}f}" for value in values]


class CollapsibleParameterGroup(QWidget):
    """Parameter section with an explicit down/right disclosure triangle."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 4)
        self.toggle_button = QtWidgets.QToolButton(self)
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.setStyleSheet("QToolButton { font-weight: bold; border: 0; padding: 2px; }")
        layout.addWidget(self.toggle_button)
        self.content = QWidget(self)
        self.form_layout = QFormLayout(self.content)
        self.form_layout.setLabelAlignment(Qt.AlignLeft)
        layout.addWidget(self.content)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self.toggle_button.toggled.connect(self._set_expanded)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - compatibility with the former QGroupBox API
        self.toggle_button.setChecked(checked)

    def isChecked(self) -> bool:  # noqa: N802 - compatibility with the former QGroupBox API
        return self.toggle_button.isChecked()

    def _set_expanded(self, expanded: bool) -> None:
        """Hide the form and release its height back to the scroll layout."""
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)
        self.setMaximumHeight(16777215 if expanded else self.toggle_button.sizeHint().height() + 8)
        self.updateGeometry()


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
        self.setWindowIcon(QIcon(str(_resource_path("assets", "smc-logo.png"))))
        # QtAds calculates initial splitter ratios while docks are inserted, so
        # establish the reference size before building the workspace.
        self.resize(1440, 920)

        self._view = SvgGraphicsView()
        self._frequency_axis = FrequencyAxisItem()
        self._plot = pg.PlotWidget(axisItems={"bottom": self._frequency_axis})
        self._config_inputs: Dict[str, QDoubleSpinBox] = {}
        self._parameter_groups: Dict[str, CollapsibleParameterGroup] = {}
        self._engineering_orders: Dict[str, QLineEdit] = {}
        self._transformer_baselines: dict[int, tuple[float, ...]] = {}
        self._transformer_status: dict[int, QLabel] = {}
        self._s21_output: QLineEdit | None = None
        self._s21_output_directory: QLineEdit | None = None
        self._active_s21_output_path: str | None = None
        self._s21_status: QLabel | None = None
        self._log_view: QPlainTextEdit | None = None
        self._run_s21_button: QPushButton | None = None
        self._same_materials_checkbox: QCheckBox | None = None
        self._s21_thread: QThread | None = None
        self._s21_worker: S21Worker | None = None

        self._update_fetch_thread: QThread | None = None
        self._update_fetch_worker: FetchReleasesWorker | None = None
        self._update_fetch_timer: QtCore.QTimer | None = None
        self._update_spinner: QtWidgets.QProgressDialog | None = None

        self._update_dl_thread: QThread | None = None
        self._update_dl_worker: DownloadReleaseWorker | None = None

        self._defaults = S21Config()
        self._design_files = DesignFileService()
        self._trace_reader = TraceFileReader()
        self._comparison_traces: dict[str, ComparisonTrace] = {}
        self._theory_trace: tuple[object, object] | None = None
        self._previous_theory_trace: tuple[object, object] | None = None

        self._build_menu()
        self._configure_plot()
        self._build_ui()
        self._remember_transformer_inputs()
        self._apply_material_sync()
        self._update_svg()

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("Справка")

        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        update_action = QAction("Проверить обновления", self)
        update_action.triggered.connect(self.check_updates)
        help_menu.addAction(update_action)

    def _build_ui(self) -> None:
        """Create the same movable dock workspace pattern used by RnSApp."""
        self._configure_dock_manager_features()
        self.dock_manager = CDockManager(self)

        self.parameters_dock = CDockWidget("Параметры")
        self.parameters_dock.setObjectName("parameters_dock")
        self.parameters_dock.setWidget(self._build_controls())

        self.schematic_dock = CDockWidget("Схема")
        self.schematic_dock.setObjectName("schematic_dock")
        self.schematic_dock.setWidget(self._build_schematic_panel())

        self.plot_dock = CDockWidget("График")
        self.plot_dock.setObjectName("plot_dock")
        self.plot_dock.setWidget(self._build_plot_panel())

        self.log_dock = CDockWidget("Лог расчёта")
        self.log_dock.setObjectName("log_dock")
        self.log_dock.setWidget(self._build_log_panel())

        left_area = self.dock_manager.addDockWidget(DockWidgetArea.LeftDockWidgetArea, self.parameters_dock)
        right_area = self.dock_manager.addDockWidget(DockWidgetArea.RightDockWidgetArea, self.schematic_dock)
        plot_area = self.dock_manager.addDockWidget(DockWidgetArea.BottomDockWidgetArea, self.plot_dock, right_area)
        self.dock_manager.addDockWidget(DockWidgetArea.BottomDockWidgetArea, self.log_dock, plot_area)

        self.dock_widgets = (
            self.parameters_dock,
            self.schematic_dock,
            self.plot_dock,
            self.log_dock,
        )
        for dock in self.dock_widgets:
            # Match RnSApp: panels are movable, resizable and closable, but do
            # not detach into hard-to-find native floating windows.
            features = dock.features()
            features |= CDockWidget.DockWidgetFeature.DockWidgetClosable
            features &= ~CDockWidget.DockWidgetFeature.DockWidgetFloatable
            features &= ~CDockWidget.DockWidgetFeature.DockWidgetPinnable
            dock.setFeatures(features)

        self._apply_default_dock_sizes()
        self.default_dock_state = self.dock_manager.saveState()
        self._build_workspace_toolbar()
        with contextlib.suppress(Exception):
            self.restore_settings()

    def _build_controls(self) -> QWidget:
        panel = QWidget(self)
        outer = QVBoxLayout(panel)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        vbox = QVBoxLayout(inner)

        title = QLabel("Параметры структуры")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        vbox.addWidget(title)

        subtitle = QLabel(
            "Номера элементов идут слева направо от ФФО. W1 — ширина слева, W2 — справа; L — общая длина."
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
            box = CollapsibleParameterGroup(group_name)
            self._parameter_groups[group_name] = box
            form = box.form_layout

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
                form.addRow(label, self._build_parameter_editor(field_info.name, spin))

            if group_fields[0].name.startswith("transf_"):
                index = int(group_fields[0].name.split("_")[1])
                status = QLabel()
                status.setWordWrap(True)
                status.setStyleSheet("color: #555;")
                self._transformer_status[index] = status
                form.addRow(status)
                for info in group_fields:
                    self._config_inputs[info.name].valueChanged.connect(self._refresh_transformer_status)

            vbox.addWidget(box)

        controls_box = QGroupBox("Actions")
        controls_box.setObjectName("actions_box")
        self.actions_box = controls_box
        controls_layout = QVBoxLayout(controls_box)

        design_row = QHBoxLayout()
        load_design_button = QPushButton("Открыть параметры…")
        load_design_button.setObjectName("load_parameters_button")
        load_design_button.setToolTip(
            "Загрузить все поля S21Config из версионного файла SMC_app и обновить preview. "
            "Форматы Mathcad .mcd/.mcdx не поддерживаются."
        )
        load_design_button.clicked.connect(self._load_design_dialog)
        design_row.addWidget(load_design_button)
        save_design_button = QPushButton("Сохранить параметры…")
        save_design_button.setObjectName("save_parameters_button")
        save_design_button.setToolTip(
            "Сохранить полный набор текущих входных параметров в версионный JSON SMC_app; "
            "кривая S21 и Mathcad-лист в файл не входят."
        )
        save_design_button.clicked.connect(self._save_design_dialog)
        design_row.addWidget(save_design_button)
        controls_layout.addLayout(design_row)

        self._s21_output = QLineEdit(_default_s21_output_path().name)
        self._s21_output.setObjectName("s21_output_filename")
        self._s21_output.setToolTip(
            "Только имя файла таблицы S21, например S21_dB.tab. Пустое поле — расчёт без сохранения."
        )
        output_form = QFormLayout()
        output_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        output_form.addRow("Имя файла", self._s21_output)
        directory_row = QWidget(self)
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        self._s21_output_directory = QLineEdit(str(_default_s21_output_directory()))
        self._s21_output_directory.setObjectName("s21_output_directory")
        self._s21_output_directory.setReadOnly(True)
        self._s21_output_directory.setToolTip(self._s21_output_directory.text())
        directory_layout.addWidget(self._s21_output_directory, stretch=1)
        select_directory = QPushButton("Выбрать…")
        select_directory.setObjectName("select_s21_directory")
        select_directory.setToolTip("Выбрать папку для таблицы S21; выбранная папка запоминается.")
        select_directory.clicked.connect(self._select_s21_output_directory)
        directory_layout.addWidget(select_directory)
        output_form.addRow("Папка", directory_row)
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

        vbox.addStretch(1)

        inner.setLayout(vbox)
        scroll.setWidget(inner)
        self.parameters_scroll = scroll
        outer.addWidget(scroll, stretch=1)
        # Actions deliberately lives outside the scroll area so preview,
        # calculation and design persistence are always reachable.
        outer.addWidget(controls_box, stretch=0)
        return panel

    def _build_schematic_panel(self) -> QWidget:
        """Build the SVG panel; its Home control sits at the lower left."""
        panel = QWidget(self)
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.addWidget(self._view, stretch=1)

        toolbar = QHBoxLayout()
        home_button = QPushButton()
        home_button.setToolTip("Return the SVG viewer to the initial fitted view.")
        home_button.setIcon(self.style().standardIcon(QStyle.SP_DirHomeIcon))
        home_button.setFixedSize(30, 28)
        home_button.clicked.connect(self._view.reset_view)
        toolbar.addWidget(home_button)
        self._schematic_details = QCheckBox("С обозначениями")
        self._schematic_details.setObjectName("schematic_details")
        self._schematic_details.setToolTip(
            "Показать размеры каждого элемента со стрелками в увеличенных выносках под схемой"
        )
        self._schematic_details.toggled.connect(self._update_svg)
        toolbar.addWidget(self._schematic_details)
        dimensions_hint = QLabel("Размеры ниже: прокрутка · Ctrl+колесо: масштаб", panel)
        dimensions_hint.setVisible(False)
        self._schematic_details.toggled.connect(dimensions_hint.setVisible)
        toolbar.addWidget(dimensions_hint)
        toolbar.addStretch(1)
        vbox.addLayout(toolbar)
        return panel

    def _build_plot_panel(self) -> QWidget:
        """Wrap the pyqtgraph widget for ownership by a QtAds dock."""
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._plot)

        controls = QtWidgets.QGridLayout()
        self._plot_scale_inputs: dict[str, QDoubleSpinBox] = {}
        for column, (name, label, value) in enumerate(
            (
                ("x_min", "X min", 100.0),
                ("x_max", "X max", 900.0),
                ("y_min", "Y min", -20.0),
                ("y_max", "Y max", 0.0),
            )
        ):
            controls.addWidget(QLabel(label), 0, column * 2)
            spin = SafeDoubleSpinBox(panel)
            spin.setRange(-1_000_000.0, 1_000_000.0)
            spin.setDecimals(2)
            spin.setValue(value)
            spin.setSingleStep(10.0 if name.startswith("x_") else 5.0)
            spin.setFixedWidth(90)
            self._plot_scale_inputs[name] = spin
            controls.addWidget(spin, 0, column * 2 + 1)
        controls.addWidget(QLabel("Y line"), 1, 0)
        self._plot_threshold_input = SafeDoubleSpinBox(panel)
        self._plot_threshold_input.setRange(-1_000_000.0, 1_000_000.0)
        self._plot_threshold_input.setDecimals(2)
        self._plot_threshold_input.setSuffix(" dB")
        self._plot_threshold_input.setValue(-5.0)
        self._plot_threshold_input.setSingleStep(1.0)
        self._plot_threshold_input.setFixedWidth(90)
        self._plot_threshold_input.valueChanged.connect(self._plot_threshold_line.setValue)
        controls.addWidget(self._plot_threshold_input, 1, 1)
        apply_scale = QPushButton("Задать Home", panel)
        apply_scale.clicked.connect(self._apply_plot_scale)
        controls.addWidget(apply_scale, 1, 2, 1, 2)
        home = QPushButton(panel)
        home.setIcon(self.style().standardIcon(QStyle.SP_DirHomeIcon))
        home.setToolTip("Вернуть заданный исходный масштаб графика")
        home.clicked.connect(self._restore_plot_scale)
        controls.addWidget(home, 1, 4)
        export = QPushButton("Экспорт PNG", panel)
        export.clicked.connect(self._export_plot_dialog)
        controls.addWidget(export, 1, 5, 1, 3)
        controls.setColumnStretch(8, 1)
        layout.addLayout(controls)
        return panel

    def _build_log_panel(self) -> QWidget:
        """Create the calculation log as an independent dock panel."""
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setPlaceholderText("Run S21 to inspect intermediate backend messages.")
        layout.addWidget(self._log_view)
        return panel

    @staticmethod
    def _configure_dock_manager_features() -> None:
        """Disable QtAds auto-hide exactly as in the RnSApp workspace."""
        with contextlib.suppress(Exception):
            CDockManager.setAutoHideConfigFlag(CDockManager.eAutoHideFlag.AutoHideFeatureEnabled, False)
            CDockManager.setAutoHideConfigFlag(CDockManager.eAutoHideFlag.DockAreaHasAutoHideButton, False)
            CDockManager.setAutoHideConfigFlag(CDockManager.eAutoHideFlag.AutoHideButtonTogglesArea, False)

    def _build_workspace_toolbar(self) -> None:
        """Add layout recovery and a live checklist of dock panels."""
        toolbar = QtWidgets.QToolBar("Вид", self)
        toolbar.setObjectName("workspace_toolbar")
        self.addToolBar(toolbar)

        self.open_files_menu = QtWidgets.QMenu("Открыть файл", self)
        design_action = self.open_files_menu.addAction("Параметры SMC_app")
        design_action.setToolTip("Открыть .aocdesign/.json с входными параметрами расчёта")
        design_action.triggered.connect(self._load_design_dialog)
        experiment_action = self.open_files_menu.addAction("Experiment")
        experiment_action.triggered.connect(lambda: self._open_trace_dialog("Experiment"))

        open_files_button = QtWidgets.QToolButton(self)
        open_files_button.setObjectName("open_files_button")
        open_files_button.setText("Открыть файл")
        open_files_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        open_files_button.setMenu(self.open_files_menu)
        toolbar.addWidget(open_files_button)
        toolbar.addSeparator()

        restore_action = QAction("Восстановить виджеты", self)
        restore_action.setToolTip("Вернуть стандартное расположение панелей")
        restore_action.triggered.connect(self.restore_default_layout)
        toolbar.addAction(restore_action)

        self.dock_widgets_menu = QtWidgets.QMenu("Виджеты", self)
        self.dock_widgets_menu.aboutToShow.connect(self._refresh_dock_widgets_menu)
        dock_widgets_button = QtWidgets.QToolButton(self)
        dock_widgets_button.setText("Виджеты")
        dock_widgets_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        dock_widgets_button.setMenu(self.dock_widgets_menu)
        toolbar.addWidget(dock_widgets_button)

    def _refresh_dock_widgets_menu(self) -> None:
        """Rebuild the panel checklist from the actual QtAds state."""
        self.dock_widgets_menu.clear()
        for dock in self.dock_widgets:
            action = self.dock_widgets_menu.addAction(dock.windowTitle())
            action.setCheckable(True)
            action.setChecked(not dock.isClosed())
            action.setToolTip("Отмечено = панель показана")
            action.triggered.connect(lambda checked, current=dock: self._set_dock_visible(current, checked))

    def _set_dock_visible(self, dock: CDockWidget, visible: bool) -> None:
        """Show or close one dock and persist the resulting workspace."""
        dock.toggleView(visible)
        self.save_settings()

    def _apply_default_dock_sizes(self) -> None:
        """Approximate the original 1440×920 composition with splitter ratios."""
        with contextlib.suppress(Exception):
            containers = self.dock_manager.dockContainers()
            if containers:
                root_splitter = containers[0].rootSplitter()
                total_width = max(sum(root_splitter.sizes()), self.width() - 4)
                parameters_width = max(280, total_width // 4)
                root_splitter.setSizes([parameters_width, total_width - parameters_width])
        with contextlib.suppress(Exception):
            right_splitter = self.schematic_dock.dockAreaWidget().parentSplitter()
            total_height = max(sum(right_splitter.sizes()), self.height() - 80)
            right_splitter.setSizes(
                [
                    total_height * 5 // 10,
                    total_height * 3 // 10,
                    total_height * 2 // 10,
                ]
            )

    def save_settings(self) -> None:
        """Persist window geometry and the versioned QtAds layout."""
        settings = QSettings()
        settings.beginGroup("MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.endGroup()

        settings.beginGroup("DockManager")
        settings.setValue("state", self.dock_manager.saveState())
        settings.setValue("layout_version", CURRENT_DOCK_LAYOUT_VERSION)
        settings.endGroup()

    def restore_settings(self) -> bool:
        """Restore compatible settings and ignore stale layout versions."""
        settings = QSettings()
        settings.beginGroup("MainWindow")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        settings.endGroup()

        settings.beginGroup("DockManager")
        state = settings.value("state")
        layout_version = settings.value("layout_version", 0, type=int)
        restored = bool(state and layout_version == CURRENT_DOCK_LAYOUT_VERSION)
        if restored:
            restored = bool(self.dock_manager.restoreState(state))
        settings.endGroup()
        return restored

    def restore_default_layout(self) -> None:
        """Restore the captured default layout and reopen every panel."""
        self.dock_manager.restoreState(self.default_dock_state)
        for dock in self.dock_widgets:
            if dock.isClosed():
                dock.toggleView(True)
        self._apply_default_dock_sizes()
        self.save_settings()

    def _last_files_directory(self) -> str:
        """Return the last successful parameter-file directory or a useful default."""
        value = QSettings().value("Files/last_directory", "", type=str)
        candidate = Path(value).expanduser() if value else Path.home() / "Documents" / "SMC_app"
        return str(candidate if candidate.exists() else Path.home())

    @staticmethod
    def _remember_file_directory(path: str | Path) -> None:
        QSettings().setValue("Files/last_directory", str(Path(path).expanduser().parent))

    def _save_design_dialog(self) -> None:
        """Ask for a friendly target and save the current backend parameters."""
        selected, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить параметры SMC_app",
            str(Path(self._last_files_directory()) / "parameters.aocdesign"),
            "Параметры SMC_app (*.aocdesign);;JSON (*.json)",
        )
        if not selected:
            return
        path = Path(selected)
        if not path.suffix:
            path = path.with_suffix(".aocdesign")
        try:
            self.save_design_to_path(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка сохранения параметров", str(exc))

    def _load_design_dialog(self) -> None:
        """Select an SMC_app parameter set and apply it to every editor."""
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Открыть параметры SMC_app",
            self._last_files_directory(),
            "Параметры SMC_app (*.aocdesign *.json)",
        )
        if not selected:
            return
        try:
            self.load_design_from_path(selected)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка открытия параметров", str(exc))

    def _open_trace_dialog(self, kind: str) -> None:
        """Select and add an experiment comparison table."""
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            f"Открыть {kind}",
            self._last_files_directory(),
            "Двухколоночный текст (*.txt *.dat *.tab);;Все файлы (*)",
        )
        if not selected:
            return
        try:
            self.load_comparison_trace(kind, selected)
        except (OSError, UnicodeError, ValueError) as exc:
            QMessageBox.critical(self, f"Ошибка импорта {kind}", str(exc))

    def load_comparison_trace(self, kind: str, path: str | Path) -> ComparisonTrace:
        """Load a plot-only trace; it never changes calculation parameters."""
        if kind != "Experiment":
            raise ValueError(f"Неизвестный тип сравнительного графика: {kind}.")
        trace = self._trace_reader.load(path)
        self._comparison_traces[kind] = trace
        self._remember_file_directory(path)
        self._redraw_plot()
        if self._s21_status is not None:
            self._s21_status.setText(f"{kind}: загружено {len(trace.frequencies)} точек из {trace.source}")
        return trace

    def save_design_to_path(self, path: str | Path) -> Path:
        """Validate and persist the current configuration for UI and tests."""
        config = self._build_config()
        config.validate()
        destination = self._design_files.save(path, config)
        self._remember_file_directory(destination)
        if self._s21_status is not None:
            self._s21_status.setText(f"Параметры сохранены: {destination}")
        return destination

    def load_design_from_path(self, path: str | Path) -> S21Config:
        """Load SI values, convert them to presentation units and refresh SVG."""
        config = self._design_files.load(path)
        config.validate()

        same_material = all(
            math.isclose(getattr(config, top), getattr(config, bottom), rel_tol=1e-12, abs_tol=0.0)
            for top, bottom in self._material_sync_map.items()
        )
        if self._same_materials_checkbox is not None:
            self._same_materials_checkbox.setChecked(same_material)

        self._defaults = config
        for name, spin in self._config_inputs.items():
            blocked = spin.blockSignals(True)
            spin.setValue(config.ui_value(name))
            spin.blockSignals(blocked)
        self._remember_transformer_inputs()
        if same_material:
            self._apply_material_sync()
        else:
            for bottom_name in self._material_sync_map.values():
                self._config_inputs[bottom_name].setEnabled(True)

        self._remember_file_directory(path)
        self._update_svg()
        if self._s21_status is not None:
            self._s21_status.setText(f"Параметры загружены: {Path(path).expanduser()}")
        return config

    def _create_spinbox(self, name: str, field_info) -> SafeDoubleSpinBox:
        spin = SafeDoubleSpinBox()
        scale = S21Config.field_scale(name)
        spin.setDecimals(field_info.decimals)
        spin.setRange(field_info.minimum, field_info.maximum)
        spin.setSingleStep(field_info.step)
        spin.setValue(self._defaults.ui_value(name))
        # Scaled metric dimensions get a separate immutable engineering-order
        # field, so the editable number remains uncluttered and unambiguous.
        if scale == 1.0 or name == "sis_cap_f_per_um2":
            spin.setSuffix(field_info.suffix)
        if name in self._material_sync_map:
            spin.valueChanged.connect(self._apply_material_sync)
        return spin

    def _build_parameter_editor(self, name: str, spin: SafeDoubleSpinBox) -> QWidget:
        """Add an immutable ``×10^n`` field for SI values shown with a scale."""
        scale = S21Config.field_scale(name)
        if scale == 1.0 or name == "sis_cap_f_per_um2":
            return spin

        exponent = -round(math.log10(scale))
        editor = QWidget(self)
        layout = QHBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(spin, stretch=1)
        unit = "1/(Ω·m)" if name.startswith("sigma0_") else "m"
        order = QLineEdit(f"×10^{exponent} {unit}", editor)
        order.setReadOnly(True)
        order.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        order.setFixedWidth(112 if name.startswith("sigma0_") else 78)
        order.setToolTip("Фиксированный инженерный порядок; показатель всегда кратен 3.")
        self._engineering_orders[name] = order
        layout.addWidget(order)
        return editor

    def _configure_plot(self) -> None:
        pg.setConfigOption("background", "#ffffff")
        pg.setConfigOption("foreground", "#7f7f7f")
        self._plot.setBackground("#ffffff")
        self._plot.setTitle("S21 vs Frequency")
        self._plot.setLabel("left", "S21", units="dB")
        self._plot.setLabel("bottom", "Frequency", units="GHz")
        self._plot.showGrid(x=True, y=True, alpha=0.10)
        self._plot.setMenuEnabled(False)
        self._plot_legend = self._plot.addLegend(offset=(10, 10))
        self._plot_threshold_line = pg.InfiniteLine(pos=-5.0, angle=0, pen=pg.mkPen("#dc2626", width=1))
        self._plot_threshold_line.setZValue(-1)
        self._plot.addItem(self._plot_threshold_line, ignoreBounds=True)
        self._plot.getPlotItem().setContentsMargins(12, 12, 12, 12)
        axis_pen = pg.mkPen("#7f7f7f", width=1)
        for axis_name in ("left", "bottom"):
            axis = self._plot.getPlotItem().getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)
        self._plot_initial_range = (100.0, 900.0, -20.0, 0.0)
        self._plot_hover_label = QLabel(self._plot)
        self._plot_hover_label.setStyleSheet(
            "QLabel { background: rgba(30, 30, 30, 150); color: white; padding: 3px 6px; border-radius: 3px; }"
        )
        self._plot_hover_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._plot_hover_label.hide()
        self._plot.scene().sigMouseMoved.connect(self._on_plot_mouse_moved)
        self._plot.getPlotItem().vb.sigXRangeChanged.connect(self._sync_frequency_axis_unit)
        self._restore_plot_scale()

    def _apply_plot_scale(self) -> None:
        """Validate editors and make their range the new Home position."""
        x_min = self._plot_scale_inputs["x_min"].value()
        x_max = self._plot_scale_inputs["x_max"].value()
        y_min = self._plot_scale_inputs["y_min"].value()
        y_max = self._plot_scale_inputs["y_max"].value()
        if x_min >= x_max or y_min >= y_max:
            QMessageBox.warning(self, "Некорректный масштаб", "Минимум должен быть меньше максимума.")
            return
        self._plot_initial_range = (x_min, x_max, y_min, y_max)
        self._restore_plot_scale()

    def _restore_plot_scale(self) -> None:
        """Return the plot to the user-defined initial X/Y range."""
        x_min, x_max, y_min, y_max = self._plot_initial_range
        self._plot.setXRange(x_min, x_max, padding=0)
        self._plot.setYRange(y_min, y_max, padding=0)

    def _sync_frequency_axis_unit(self, *_args) -> None:
        """Keep the bottom-axis unit aligned with the visible GHz range."""
        x_range = self._plot.getPlotItem().vb.viewRange()[0]
        self._frequency_axis.set_display_range(x_range[0], x_range[1])

    def _on_plot_mouse_moved(self, scene_position) -> None:
        """Show frequency and S21 coordinates next to the cursor."""
        plot_item = self._plot.getPlotItem()
        if not plot_item.sceneBoundingRect().contains(scene_position):
            self._plot_hover_label.hide()
            return
        cursor_value = plot_item.vb.mapSceneToView(scene_position)
        self._plot_hover_label.setText(f"f = {cursor_value.x():.3f} GHz; S21 = {cursor_value.y():.3f} dB")
        self._plot_hover_label.adjustSize()
        local = self._plot.mapFromScene(scene_position)
        self._plot_hover_label.move(local.x() + 12, local.y() + 12)
        self._plot_hover_label.show()

    def _export_plot_dialog(self) -> None:
        selected, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Экспорт графика",
            str(Path(self._last_files_directory()) / "s21.png"),
            "PNG (*.png)",
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        try:
            self.export_plot_to_path(path)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта графика", str(exc))

    def export_plot_to_path(self, path: str | Path) -> Path:
        """Export the current plot item at twice its on-screen width."""
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._plot.getPlotItem().sceneBoundingRect()
        if source.width() <= 0 or source.height() <= 0:
            raise ValueError("График имеет пустую область экспорта")
        width = max(1200, self._plot.width() * 2)
        height = max(1, round(width * source.height() / source.width()))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        if image.isNull():
            raise OSError("Не удалось выделить память для PNG графика")
        image.fill(self._plot.backgroundBrush().color())
        # ImageExporter creates a temporary Parameter tree connected to a
        # plain Python receiver. PySide 6.8 can write to a freed receiver when
        # these callbacks are destroyed, corrupting the heap after export.
        # Render the same plot rectangle with Qt and end painting before save.
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._plot.scene().render(painter, QtCore.QRectF(0, 0, width, height), source)
        finally:
            painter.end()
        writer = QImageWriter(str(destination), b"png")
        if not writer.write(image):
            raise OSError(f"Не удалось сохранить PNG: {writer.errorString()}")
        self._remember_file_directory(destination)
        return destination

    def _build_config(self) -> S21Config:
        values = dict(self._defaults.__dict__)
        for name, spin in self._config_inputs.items():
            spin.interpretText()
            if name.endswith("_length_m"):
                continue
            scale = S21Config.field_scale(name)
            values[name] = spin.value() / scale

        for index in range(1, 8):
            current = self._transformer_inputs(index)
            if current == self._transformer_baselines[index]:
                # Keep the exact original discretization for untouched legacy files.
                for suffix in ("w_start_m", "w_end_m"):
                    name = f"transf_{index}_{suffix}"
                    values[name] = getattr(self._defaults, name)
                continue
            try:
                steps = derive_transformer_steps(*(value * 1e-6 for value in current))
            except ValueError as error:
                raise ValueError(f"Элемент {ELEMENT_NUMBERS[f'T{index}']}: {error}") from error
            values[f"transf_{index}_dwdl_um"] = steps.n_um
            values[f"transf_{index}_dl_m"] = steps.dl_m

        if self._same_materials_checkbox is not None and self._same_materials_checkbox.isChecked():
            for top_name, bot_name in self._material_sync_map.items():
                values[bot_name] = values[top_name]

        return S21Config(**values)

    def _transformer_inputs(self, index: int) -> tuple[float, ...]:
        return tuple(
            self._config_inputs[f"transf_{index}_{suffix}"].value() for suffix in ("w_end_m", "w_start_m", "length_m")
        )

    def _remember_transformer_inputs(self) -> None:
        self._transformer_baselines = {index: self._transformer_inputs(index) for index in range(1, 8)}
        self._refresh_transformer_status()

    def _refresh_transformer_status(self) -> None:
        for index, status in self._transformer_status.items():
            if index not in self._transformer_baselines:
                continue
            try:
                current = self._transformer_inputs(index)
                if current == self._transformer_baselines[index]:
                    n = getattr(self._defaults, f"transf_{index}_dwdl_um")
                    dl_um = getattr(self._defaults, f"transf_{index}_dl_m") * 1e6
                    status.setText(f"n={n:g}; dl={dl_um:g} µm (из файла/исходных параметров)")
                else:
                    steps = derive_transformer_steps(*(value * 1e-6 for value in current))
                    status.setText(f"n={steps.n_um}; ступеней: {steps.intervals + 1}; dl={steps.dl_m * 1e6:g} µm")
                status.setStyleSheet("color: #555;")
            except ValueError as error:
                status.setText(str(error))
                status.setStyleSheet("color: #b91c1c;")

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
            svg = self._use_case.execute(config, show_details=self._schematic_details.isChecked())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        self._view.set_svg(svg, fit_width=self._schematic_details.isChecked())

    def _select_s21_output_directory(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Папка для таблицы S21", self._s21_output_directory.text()
        )
        if directory:
            self._s21_output_directory.setText(directory)
            self._s21_output_directory.setToolTip(directory)
            QSettings().setValue("Files/s21_output_directory", directory)

    def _s21_result_path(self) -> str | None:
        filename = self._s21_output.text().strip()
        if not filename:
            return None
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        if (
            filename in {".", ".."}
            or filename.endswith(".")
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in filename)
            or filename.split(".")[0].upper() in reserved
        ):
            raise ValueError(
                "Укажите только имя файла без пути и служебных символов; папку выберите кнопкой «Выбрать…»."
            )
        return str(Path(self._s21_output_directory.text()) / filename)

    def _run_s21(self) -> None:
        if self._s21_output is None or self._s21_status is None:
            return
        if self._s21_thread is not None:
            self._append_log_message("S21 calculation is already running.")
            return
        try:
            config = self._build_config()
            config.validate()
            output_path = self._s21_result_path()
        except ValueError as exc:
            self._append_log_message(f"ERROR: {exc}")
            QMessageBox.warning(self, "Invalid input", str(exc))
            return

        self._active_s21_output_path = output_path
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
        self._s21_worker = S21Worker(self._s21_use_case, config, output_path)
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

        output_path = self._active_s21_output_path
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
        # finished is emitted before the native thread processes its final
        # deferred deletions. Keep both Python wrappers alive until that cleanup
        # completes, so Shiboken cannot destroy a wrapper concurrently with its
        # QObject on the worker thread.
        if self._s21_thread is not None:
            self._s21_thread.wait()
        self._s21_thread = None
        self._s21_worker = None
        if self._run_s21_button is not None:
            self._run_s21_button.setEnabled(True)

    def _update_s21_plot(self, frequencies, s21_db) -> None:
        """Rotate only successful calculations; own the samples independently."""
        self._previous_theory_trace = self._theory_trace
        self._theory_trace = (list(frequencies), list(s21_db))
        self._redraw_plot()

    def _redraw_plot(self) -> None:
        """Render theory and all optional comparisons with a shared legend."""
        self._plot.clear()
        self._plot.addItem(self._plot_threshold_line, ignoreBounds=True)
        if self._previous_theory_trace is not None:
            previous = self._plot.plot(
                *self._previous_theory_trace,
                pen=pg.mkPen(color=(70, 70, 70, 153), width=2),
                name="Previous theory",
            )
            previous.setZValue(0)
        if self._theory_trace is not None:
            frequencies, s21_db = self._theory_trace
            pen = pg.mkPen(color="#1f77b4", width=2)
            current = self._plot.plot(
                frequencies,
                s21_db,
                pen=pen,
                symbol="o",
                symbolSize=4,
                symbolBrush="#1f77b4",
                symbolPen="#1f77b4",
                name="Theory",
            )
            current.setZValue(1)

        styles = {
            "Experiment": ("#2ca02c", Qt.PenStyle.DotLine),
        }
        for kind in ("Experiment",):
            trace = self._comparison_traces.get(kind)
            if trace is None:
                continue
            color, style = styles[kind]
            self._plot.plot(
                trace.frequencies,
                trace.coefficients,
                pen=pg.mkPen(color=color, width=2, style=style),
                name=kind,
            )

        # PlotItem enables auto-range again when curves are cleared/re-added.
        # Reapply the user's Home range so recalculation/import cannot silently
        # replace the requested issue-4 defaults (100…900 GHz, -20…0 dB).
        self._restore_plot_scale()

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

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "О программе",
            (
                "AOCapp\n"
                f"Версия: {__version__}\n"
                f"Репозиторий релизов: {REPO_SLUG}\n\n"
                "Расчёт и визуализация сверхпроводящей интегральной структуры, SVG preview и S21 response."
            ),
        )

    def check_updates(self) -> None:
        if self._update_fetch_thread is not None:
            QMessageBox.information(self, "Проверка обновлений", "Загрузка списка релизов уже выполняется.")
            return

        spinner = QtWidgets.QProgressDialog("Получение списка релизов...", "Отмена", 0, 0, self)
        spinner.setWindowModality(Qt.WindowModality.ApplicationModal)
        spinner.setAutoClose(True)
        spinner.show()
        self._update_spinner = spinner

        worker = FetchReleasesWorker(REPO_SLUG, limit=10, parent=self)
        self._update_fetch_thread = worker
        self._update_fetch_worker = worker

        conn = Qt.ConnectionType.QueuedConnection
        worker.status.connect(self._on_update_fetch_status, conn)
        worker.finished_fetch.connect(self._on_update_fetch_finished, conn)
        worker.error.connect(self._on_update_fetch_error, conn)

        worker.finished_fetch.connect(worker.deleteLater, conn)
        worker.error.connect(worker.deleteLater, conn)

        spinner.canceled.connect(self._cancel_update_fetch, conn)

        worker.start()

    @Slot()
    def _cancel_update_fetch(self) -> None:
        thread = self._update_fetch_thread
        if thread:
            thread.requestInterruption()
            thread.terminate()  # Forcefully terminate if blocked
            thread.wait(100)
        self._update_fetch_thread = None
        self._update_fetch_worker = None
        if self._update_spinner:
            self._update_spinner.close()
            self._update_spinner = None

    @Slot(list)
    def _on_update_fetch_finished(self, releases: list) -> None:
        self._cleanup_update_thread()
        spinner = self._update_spinner
        self._update_spinner = None
        if spinner:
            spinner.close()

        dialog = ReleasePickerDialog(releases, parent=self, current_version=__version__)
        res = dialog.exec()
        if res == QtWidgets.QDialog.Accepted:
            self._start_auto_update(dialog.selected)
        elif res == QtWidgets.QDialog.Accepted + 1:
            self._show_download_link(dialog.selected)

    @Slot(str)
    def _on_update_fetch_error(self, message: str) -> None:
        self._cleanup_update_thread()
        if self._update_spinner:
            self._update_spinner.close()
        self._update_spinner = None
        QMessageBox.critical(self, "Ошибка обновлений", f"Не удалось получить список релизов:\n{message}")

    @Slot(str)
    def _on_update_fetch_status(self, text: str) -> None:
        if self._update_spinner:
            self._update_spinner.setLabelText(text)

    def _cleanup_update_thread(self) -> None:
        thread = self._update_fetch_thread
        if thread:
            thread.requestInterruption()
            thread.quit()
            thread.wait(2000)
        self._update_fetch_thread = None
        self._update_fetch_worker = None

    def _show_download_link(self, release) -> None:
        url = release.asset.download_url
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Загрузка обновления")
        dialog.resize(680, 220)
        layout = QVBoxLayout(dialog)

        info = QLabel(f"Релиз {release.tag}. Подходящий файл для вашей системы: {release.asset.name}")
        info.setWordWrap(True)
        layout.addWidget(info)

        link = QLabel(f'<a href="{url}">{url}</a>')
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)
        layout.addWidget(link)

        buttons = QHBoxLayout()
        copy_button = QPushButton("Скопировать ссылку")
        open_button = QPushButton("Открыть в браузере")
        close_button = QPushButton("Закрыть")
        buttons.addWidget(copy_button)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(url))
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QtCore.QUrl(url)))
        close_button.clicked.connect(dialog.accept)
        dialog.exec()

    def _start_auto_update(self, release):
        if self._update_dl_thread is not None:
            return

        pd = QtWidgets.QProgressDialog("Загрузка обновления...", "Отмена", 0, 100, self)
        pd.setWindowTitle("Обновление")
        pd.setWindowModality(Qt.WindowModality.ApplicationModal)
        pd.setAutoClose(False)
        pd.show()
        self._update_spinner = pd

        worker = DownloadReleaseWorker(release.asset.download_url, parent=self)
        self._update_dl_thread = worker
        self._update_dl_worker = worker

        worker.status.connect(pd.setLabelText)
        worker.progress.connect(lambda d, t, s: self._on_update_dl_progress(d, t, s, pd))
        worker.error.connect(self._on_update_dl_error)
        worker.finished_download.connect(lambda src: self._on_update_dl_finished(src, release))

        worker.error.connect(worker.deleteLater)
        worker.finished_download.connect(worker.deleteLater)
        worker.finished.connect(self._on_update_dl_thread_finished)

        pd.canceled.connect(self._cancel_update_dl)
        worker.start()

    @Slot()
    def _cancel_update_dl(self) -> None:
        thread = self._update_dl_thread
        if thread:
            thread.requestInterruption()
            thread.terminate()  # Forcefully terminate if blocked
            thread.wait(100)
        self._update_dl_thread = None
        self._update_dl_worker = None
        if self._update_spinner:
            self._update_spinner.close()
            self._update_spinner = None

    def _on_update_dl_progress(self, downloaded, total, speed, pd):
        if total > 0:
            pd.setValue(int((downloaded / total) * 100))
            mb = downloaded / 1024 / 1024
            tot_mb = total / 1024 / 1024
            pd.setLabelText(f"Загрузка: {mb:.1f} / {tot_mb:.1f} MB ({speed:.1f} MB/s)")
        else:
            mb = downloaded / 1024 / 1024
            pd.setLabelText(f"Загрузка: {mb:.1f} MB ({speed:.1f} MB/s)")

    def _on_update_dl_error(self, message):
        if self._update_spinner:
            self._update_spinner.close()
        QMessageBox.critical(self, "Ошибка загрузки", f"Не удалось загрузить обновление:\n{message}")

    def _on_update_dl_finished(self, src_dir, release):
        if self._update_spinner:
            self._update_spinner.close()

        # Determine paths
        if getattr(sys, "frozen", False):
            # If running as a bundle (PyInstaller)
            exe_path = sys.executable
            install_dir = os.path.dirname(exe_path)

            if sys.platform == "darwin" and ".app/Contents/MacOS" in exe_path:
                # For macOS .app bundles
                app_bundle = exe_path.split(".app/Contents/MacOS")[0] + ".app"
                dst_dir = app_bundle
                updater_exe = os.path.join(os.path.dirname(exe_path), "updater")
            else:
                # Windows/Linux onedir
                dst_dir = install_dir
                updater_exe = os.path.join(install_dir, "updater.exe" if sys.platform == "win32" else "updater")

            if os.path.exists(updater_exe):
                cmd = [updater_exe, "--pid", str(os.getpid()), "--src", src_dir, "--dst", dst_dir, "--exe", exe_path]
            else:
                # Fallback to script if binary not found for some reason
                updater_script = _resource_path("updater.py")
                cmd = [
                    sys.executable,
                    str(updater_script),
                    "--pid",
                    str(os.getpid()),
                    "--src",
                    src_dir,
                    "--dst",
                    dst_dir,
                    "--exe",
                    exe_path,
                ]
        else:
            # If running from source (development)
            dst_dir = str(Path(__file__).parents[2])
            exe_path = sys.executable
            updater_script = Path(__file__).parents[2] / "updater.py"

            cmd = [
                sys.executable,
                str(updater_script),
                "--pid",
                str(os.getpid()),
                "--src",
                src_dir,
                "--dst",
                dst_dir,
                "--exe",
                exe_path,
            ]

        try:
            subprocess.Popen(cmd)
            QApplication.quit()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка запуска обновления", f"Не удалось запустить updater:\n{str(e)}")

    def _on_update_dl_thread_finished(self):
        self._update_dl_thread = None
        self._update_dl_worker = None
        self._update_spinner = None

    def closeEvent(self, event) -> None:
        with contextlib.suppress(Exception):
            self.save_settings()
        self._cleanup_update_thread()
        if self._s21_thread is not None:
            self._s21_thread.requestInterruption()
            self._s21_thread.quit()
            self._s21_thread.wait(1000)
        super().closeEvent(event)


def run_app(use_case: GenerateStructureUseCase, s21_use_case: CalculateS21UseCase) -> None:
    QtCore.QCoreApplication.setOrganizationName("AOCapp")
    QtCore.QCoreApplication.setApplicationName("AOCapp")
    app = QApplication(sys.argv)
    window = MainWindow(use_case, s21_use_case)
    window.resize(1440, 920)
    window.show()
    app.exec()
