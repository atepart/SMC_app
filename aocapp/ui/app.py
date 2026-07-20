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
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPainter, QWheelEvent
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
from aocapp.infrastructure.design_files import DesignFileService
from aocapp.ui.update_dialogs import DownloadReleaseWorker, FetchReleasesWorker, ReleasePickerDialog

CURRENT_DOCK_LAYOUT_VERSION = 1


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def _default_s21_output_path() -> Path:
    return Path.home() / "Documents" / "SMC_app" / "S21_dB.tab"


def _resolve_s21_output_path(path_text: str) -> str:
    output_path = Path(path_text).expanduser()
    if not output_path.is_absolute():
        output_path = Path.home() / "Documents" / "SMC_app" / output_path
    return str(output_path)


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

    def resizeEvent(self, event) -> None:
        """Keep the initial drawing fitted while QtAds settles dock sizes.

        QtAds performs several resizes after the SVG is first loaded.  Refitting
        only while ``_zoom_level == 0`` handles those layout changes without
        destroying a scale explicitly chosen by the user with the wheel.
        """
        super().resizeEvent(event)
        if self._svg_item is not None and self._zoom_level == 0:
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


class SafeDoubleSpinBox(QDoubleSpinBox):
    """Spin box whose wheel is armed only by an explicit mouse click.

    Merely moving the cursor over a long parameter form must keep scrolling the
    form.  A click arms wheel editing for this field until focus leaves it;
    arrow buttons and keyboard input continue to work as normal.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_armed = False

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


class CollapsibleParameterGroup(QGroupBox):
    """Checkable group box that actually removes its form from the layout."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(True)
        layout = QVBoxLayout(self)
        self.content = QWidget(self)
        self.form_layout = QFormLayout(self.content)
        self.form_layout.setLabelAlignment(Qt.AlignLeft)
        layout.addWidget(self.content)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self.toggled.connect(self._set_expanded)

    def _set_expanded(self, expanded: bool) -> None:
        """Hide the form and release its height back to the scroll layout."""
        self.content.setVisible(expanded)
        self.setMaximumHeight(16777215 if expanded else self.fontMetrics().height() + 18)
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
        self.setWindowIcon(QIcon(str(_resource_path("assets", "aocapp-icon.png"))))
        # QtAds calculates initial splitter ratios while docks are inserted, so
        # establish the reference size before building the workspace.
        self.resize(1440, 920)

        self._view = SvgGraphicsView()
        self._plot = pg.PlotWidget()
        self._config_inputs: Dict[str, QDoubleSpinBox] = {}
        self._parameter_groups: Dict[str, CollapsibleParameterGroup] = {}
        self._engineering_orders: Dict[str, QLineEdit] = {}
        self._s21_output: QLineEdit | None = None
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

        self._build_menu()
        self._configure_plot()
        self._build_ui()
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

            vbox.addWidget(box)

        controls_box = QGroupBox("Actions")
        controls_box.setObjectName("actions_box")
        self.actions_box = controls_box
        controls_layout = QVBoxLayout(controls_box)

        design_row = QHBoxLayout()
        load_design_button = QPushButton("Загрузить дизайн")
        load_design_button.clicked.connect(self._load_design_dialog)
        design_row.addWidget(load_design_button)
        save_design_button = QPushButton("Сохранить дизайн")
        save_design_button.clicked.connect(self._save_design_dialog)
        design_row.addWidget(save_design_button)
        controls_layout.addLayout(design_row)

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
        toolbar.addStretch(1)
        vbox.addLayout(toolbar)
        return panel

    def _build_plot_panel(self) -> QWidget:
        """Wrap the pyqtgraph widget for ownership by a QtAds dock."""
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._plot)
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
        """Return the last successful design directory or a useful default."""
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
            "Сохранить дизайн",
            str(Path(self._last_files_directory()) / "design.aocdesign"),
            "Дизайн AOCapp (*.aocdesign);;JSON (*.json)",
        )
        if not selected:
            return
        path = Path(selected)
        if not path.suffix:
            path = path.with_suffix(".aocdesign")
        try:
            self.save_design_to_path(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка сохранения дизайна", str(exc))

    def _load_design_dialog(self) -> None:
        """Select a design and apply it to every visible parameter editor."""
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Открыть дизайн",
            self._last_files_directory(),
            "Дизайн AOCapp (*.aocdesign *.json)",
        )
        if not selected:
            return
        try:
            self.load_design_from_path(selected)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка открытия дизайна", str(exc))

    def save_design_to_path(self, path: str | Path) -> Path:
        """Validate and persist the current configuration for UI and tests."""
        config = self._build_config()
        config.validate()
        destination = self._design_files.save(path, config)
        self._remember_file_directory(destination)
        if self._s21_status is not None:
            self._s21_status.setText(f"Дизайн сохранён: {destination}")
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

        for name, spin in self._config_inputs.items():
            blocked = spin.blockSignals(True)
            spin.setValue(getattr(config, name) * S21Config.field_scale(name))
            spin.blockSignals(blocked)
        if same_material:
            self._apply_material_sync()
        else:
            for bottom_name in self._material_sync_map.values():
                self._config_inputs[bottom_name].setEnabled(True)

        self._remember_file_directory(path)
        self._update_svg()
        if self._s21_status is not None:
            self._s21_status.setText(f"Дизайн загружен: {Path(path).expanduser()}")
        return config

    def _create_spinbox(self, name: str, field_info) -> SafeDoubleSpinBox:
        spin = SafeDoubleSpinBox()
        scale = S21Config.field_scale(name)
        default_value = getattr(self._defaults, name)
        if default_value is None:
            default_value = 0.0
        spin.setDecimals(field_info.decimals)
        spin.setRange(field_info.minimum, field_info.maximum)
        spin.setSingleStep(field_info.step)
        spin.setValue(default_value * scale)
        # Scaled metric dimensions get a separate immutable engineering-order
        # field, so the editable number remains uncluttered and unambiguous.
        if scale == 1.0:
            spin.setSuffix(field_info.suffix)
        if name in self._material_sync_map:
            spin.valueChanged.connect(self._apply_material_sync)
        return spin

    def _build_parameter_editor(self, name: str, spin: SafeDoubleSpinBox) -> QWidget:
        """Add an immutable ``×10^n`` field for SI values shown with a scale."""
        scale = S21Config.field_scale(name)
        if scale == 1.0:
            return spin

        exponent = -round(math.log10(scale))
        editor = QWidget(self)
        layout = QHBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(spin, stretch=1)
        order = QLineEdit(f"×10^{exponent} m", editor)
        order.setReadOnly(True)
        order.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        order.setFixedWidth(78)
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
        if output_path:
            output_path = _resolve_s21_output_path(output_path)
            self._s21_output.setText(output_path)
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
            output_path = _resolve_s21_output_path(output_path)
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
        self._plot.plot(
            frequencies, s21_db, pen=pen, symbol="o", symbolSize=4, symbolBrush="#ff7f0e", symbolPen="#1f77b4"
        )

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
