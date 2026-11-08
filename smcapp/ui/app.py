"""PySide6 UI for grouped parameter input and SVG preview."""

from __future__ import annotations

import contextlib
import math
import os
import subprocess
import sys
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QByteArray, QObject, QPointF, QRectF, QSettings, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QImageWriter,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QTransform,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsPathItem,
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

from smcapp.application.s21_use_case import CalculateS21UseCase
from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.application.version import REPO_SLUG, __version__
from smcapp.domain.circuit import CORNERS, TransformerSection, composition, with_element
from smcapp.domain.models import Point, SvgColorScheme
from smcapp.domain.s21_models import S21Config, split_element_field
from smcapp.domain.transformers import derive_transformer_steps, transformer_dl_max_um
from smcapp.infrastructure.design_files import DesignFileService
from smcapp.infrastructure.geometry import SIGNAL_INPUT
from smcapp.infrastructure.hover import ElementHitMap, NumberMark
from smcapp.infrastructure.settings import migrate_legacy_settings
from smcapp.infrastructure.trace_files import ComparisonTrace, HfssTabReader, TraceFileReader
from smcapp.ui.plot_legend import CheckableItemSample, PlainItemSample
from smcapp.ui.theme import (
    ACCENT,
    THEME_COLORS,
    THEME_TITLES,
    Theme,
    apply_application_theme,
    dock_stylesheet,
    load_theme,
    run_button_stylesheet,
    save_theme,
)
from smcapp.ui.update_dialogs import DownloadReleaseWorker, FetchReleasesWorker, ReleasePickerDialog

CURRENT_DOCK_LAYOUT_VERSION = 1

# Plot curves by legend name (GitHub #11), in legend order: the current
# calculation, the previous one, the frozen buffer, an imported HFSS
# simulation and the measured experiment.
SMC_CURVE = "SMC"
PREV_CURVE = "prev"
BUFF_CURVE = "buff"
HFSS_CURVE = "HFSS"
EXP_CURVE = "exp"
# Imported comparison traces ("Открыть файл" menu kind) and their curve names.
COMPARISON_CURVE_NAMES = {"HFSS": HFSS_CURVE, "Experiment": EXP_CURVE}
# File dialog filter per kind: HFSS exports .tab tables with a header row.
_COMPARISON_FILE_FILTERS = {
    "HFSS": "HFSS (*.tab);;Все файлы (*)",
    "Experiment": "Двухколоночный текст (*.txt *.dat *.tab);;Все файлы (*)",
}
# Draw order: the thick grey buffer at the bottom, the current SMC on top.
_CURVE_Z_VALUES = {BUFF_CURVE: -0.5, PREV_CURVE: 0.0, HFSS_CURVE: 0.25, EXP_CURVE: 0.5, SMC_CURVE: 1.0}
BASE_CURVE_WIDTH = 2.0
SMC_SYMBOL_SIZE = 3.5

# Larger text where it matters (GitHub #11), as multiples of the platform's
# application font: 13 pt on macOS and 9 pt on Windows scale alike.
PARAMETER_TITLE_SCALE = 1.3
PARAMETER_FIELD_SCALE = 1.15
# Run S21: bold and a little larger than the fields, about half the WP-043 size.
RUN_BUTTON_SCALE = 1.15
RUN_BUTTON_HEIGHT_LINES = 1.5
PLOT_TITLE_SCALE = 1.4
PLOT_AXIS_LABEL_SCALE = 1.25
PLOT_TICK_SCALE = 1.15
PLOT_LEGEND_SCALE = 1.2
LEGEND_SINGLE_COLUMN_MAX = 3
PLOT_HOVER_SCALE = 1.2
# Default parameter panel width above its content's minimum, in px.
PARAMETERS_WIDTH_RESERVE = 24


def scaled_point_size(scale: float) -> float:
    """Point size ``scale`` times the application font (10 pt if it is pixel-sized)."""
    base = QApplication.font().pointSizeF()
    return round((base if base > 0 else 10.0) * scale, 1)


def scaled_font(scale: float, bold: bool = False) -> QFont:
    font = QFont(QApplication.font())
    font.setPointSizeF(scaled_point_size(scale))
    font.setBold(bold)
    return font


def format_plot_coordinates(frequency_ghz: float, s21_db: float) -> str:
    """Cursor plate text: frequency to 1 GHz, S21 to 0.01 dB (GitHub #11)."""
    # ``+ 0.0`` turns a rounded -0.0 into 0.0, so no "-0" or "-0.00" is shown.
    frequency = round(frequency_ghz) + 0.0
    s21 = round(s21_db, 2) + 0.0
    return f"f = {frequency:.0f} GHz; S21 = {s21:.2f} dB"


@dataclass(frozen=True)
class ParameterBuffer:
    """In-memory «Буфер» (GitHub #11): parameters plus the frozen buff curve.

    ``trace`` is the SMC curve at the moment of «Записать», or ``None`` when
    nothing had been calculated yet; it never follows later calculations.
    """

    config: S21Config
    same_material: bool
    trace: tuple[list[float], list[float]] | None


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
        # Last pin: SVG point, wanted viewport position, transform and the
        # viewport position actually reached (scroll bars are whole pixels).
        self._pin: tuple[QPointF, QPointF, QTransform, QPointF] | None = None
        # GitHub #10: the number of the element under the cursor is highlighted
        # by overlay items above the SVG; the hit map comes with each drawing.
        self._hit_map: ElementHitMap | None = None
        self._highlight_color = QColor(ACCENT)
        self._highlight_items: tuple[QGraphicsPathItem, QGraphicsPathItem] | None = None
        self._hovered: NumberMark | None = None
        self._hover_position: QPointF | None = None
        self._redrawing = False
        self.viewport().setMouseTracking(True)

    def set_svg(
        self,
        svg_text: str,
        *,
        fit_width: bool = False,
        anchor: QPointF | None = None,
        hit_map: ElementHitMap | None = None,
    ) -> None:
        """Show a new drawing and re-test the hover against its *hit_map*."""
        self._redrawing = True
        try:
            self._hit_map = hit_map
            self._load_svg(svg_text, fit_width=fit_width, anchor=anchor)
        finally:
            self._redrawing = False
        self._refresh_hover()

    def _load_svg(self, svg_text: str, *, fit_width: bool, anchor: QPointF | None) -> None:
        """Show a new drawing, keeping the user's zoom and place within one mode.

        Parameter edits redraw the SVG while the user inspects an element.  A
        zoomed drawing keeps *anchor* (the signal input, in SVG user units) at
        the same place on screen; the dimension sheet keeps the SVG point in
        the view centre.  The wanted place is remembered until the user pans
        or zooms, so whole-pixel scrolling never accumulates into a drift.
        A different mode starts from the fitted view.
        """
        keep_view = self._svg_item is not None and fit_width == self._fit_width
        if keep_view:
            pin_svg, pin_px = self._current_pin(None if fit_width else anchor)
            transform = self.transform()
        renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        item = QGraphicsSvgItem()
        item.setSharedRenderer(renderer)

        scene = self.scene()
        if scene is None:
            scene = QGraphicsScene(self)
            self.setScene(scene)
        # ``clear`` deletes the old overlay items too.
        self._highlight_items = None
        self._hovered = None
        scene.clear()
        scene.addItem(item)
        self._add_highlight_items(scene)
        scene.setSceneRect(item.boundingRect())

        self._renderer = renderer
        self._svg_item = item
        self._fit_width = fit_width
        if not keep_view:
            self._pin = None
            self.reset_view()
            return
        if self._zoom_level == 0:
            self._fit_default()
        else:
            self.setTransform(transform)
        if self._zoom_level != 0 or self._fit_width:
            self._place(pin_svg, pin_px)
        else:
            self._pin = None

    def _viewport_position(self, svg_point: QPointF) -> QPointF:
        """Exact (sub-pixel) viewport position of an SVG point."""
        return self.viewportTransform().map(self._svg_to_scene(svg_point))

    def _current_pin(self, anchor: QPointF | None) -> tuple[QPointF, QPointF]:
        """The SVG point to keep and where on the viewport it should stay."""
        if self._pin is not None:
            svg, wanted, transform, reached = self._pin
            moved = self._viewport_position(svg) - reached
            same_point = anchor is None or anchor == svg
            if same_point and transform == self.transform() and abs(moved.x()) + abs(moved.y()) < 1e-6:
                return svg, wanted
        if anchor is not None:
            return anchor, self._viewport_position(anchor)
        centre = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        inverse, _ok = self.viewportTransform().inverted()
        return self._scene_to_svg(inverse.map(centre)), centre

    def _place(self, svg_point: QPointF, wanted: QPointF) -> None:
        """Scroll so that *svg_point* lands on *wanted* (to the nearest pixel)."""
        offset = self._viewport_position(svg_point) - wanted
        for bar, delta in ((self.horizontalScrollBar(), offset.x()), (self.verticalScrollBar(), offset.y())):
            bar.setValue(bar.value() + round(delta))
        self._pin = (svg_point, wanted, self.transform(), self._viewport_position(svg_point))

    def _scene_to_svg(self, point: QPointF) -> QPointF:
        box, rect = self._renderer.viewBoxF(), self._svg_item.boundingRect()
        return QPointF(
            box.x() + point.x() * box.width() / max(rect.width(), 1e-9),
            box.y() + point.y() * box.height() / max(rect.height(), 1e-9),
        )

    def _svg_to_scene(self, point: QPointF) -> QPointF:
        box, rect = self._renderer.viewBoxF(), self._svg_item.boundingRect()
        return QPointF(
            (point.x() - box.x()) * rect.width() / max(box.width(), 1e-9),
            (point.y() - box.y()) * rect.height() / max(box.height(), 1e-9),
        )

    # Hover highlight of element numbers (GitHub #10) ----------------------

    # Thin lines stay easy to hit: the cursor may miss the metal by this much.
    HOVER_TOLERANCE_PX = 4.0
    # Plate around the number and the accent arrow, in SVG user units.
    PLATE_PADDING = (3.0, 2.5)
    ARROW_WIDTH = 1.4
    ARROW_HEAD = (7.0, 3.0)

    @property
    def hovered_element(self) -> str | None:
        return None if self._hovered is None else self._hovered.element_id

    @property
    def highlight_items(self) -> tuple[QGraphicsPathItem, QGraphicsPathItem] | None:
        """The plate under the number and the accent arrow (for tests)."""
        return self._highlight_items

    def set_highlight_color(self, color: str) -> None:
        self._highlight_color = QColor(color)
        self._style_highlight_items()

    def _add_highlight_items(self, scene: QGraphicsScene) -> None:
        plate, arrow = QGraphicsPathItem(), QGraphicsPathItem()
        for z, overlay in ((2, plate), (1, arrow)):
            overlay.setZValue(z)
            overlay.setVisible(False)
            overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            scene.addItem(overlay)
        self._highlight_items = (plate, arrow)
        self._style_highlight_items()

    def _style_highlight_items(self) -> None:
        if self._highlight_items is None:
            return
        plate, arrow = self._highlight_items
        fill = QColor(self._highlight_color)
        fill.setAlpha(110)
        plate.setBrush(QBrush(fill))
        border = QPen(self._highlight_color, 1.5)
        border.setCosmetic(True)
        plate.setPen(border)
        arrow.setBrush(QBrush(self._highlight_color))
        arrow.setPen(QPen(Qt.PenStyle.NoPen))

    def _svg_scale(self) -> float:
        """Scene units per SVG user unit."""
        box, rect = self._renderer.viewBoxF(), self._svg_item.boundingRect()
        return rect.width() / max(box.width(), 1e-9)

    def _show_highlight(self, mark: NumberMark | None) -> None:
        self._hovered = mark
        if self._highlight_items is None:
            return
        plate, arrow = self._highlight_items
        if mark is None:
            plate.setVisible(False)
            arrow.setVisible(False)
            return
        pad_x, pad_y = self.PLATE_PADDING
        box = mark.box
        rect = QRectF(
            self._svg_to_scene(QPointF(box.x0 - pad_x, box.y0 - pad_y)),
            self._svg_to_scene(QPointF(box.x1 + pad_x, box.y1 + pad_y)),
        )
        outline = QPainterPath()
        outline.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        plate.setPath(outline)
        # The arrow again in the accent colour, drawn over the grey one.
        start, tip = mark.arrow.start, mark.arrow.end
        length = math.hypot(tip.x - start.x, tip.y - start.y)
        head_length, head_half = self.ARROW_HEAD
        path = QPainterPath()
        if length > 1e-9:
            ux, uy = (tip.x - start.x) / length, (tip.y - start.y) / length
            base = QPointF(tip.x - ux * min(head_length, length), tip.y - uy * min(head_length, length))
            scale = self._svg_scale()
            stroke = QPainterPath(self._svg_to_scene(QPointF(start.x, start.y)))
            stroke.lineTo(self._svg_to_scene(base))
            stroker = QPainterPathStroker()
            stroker.setWidth(self.ARROW_WIDTH * scale)
            path = stroker.createStroke(stroke)
            head = QPainterPath(self._svg_to_scene(QPointF(tip.x, tip.y)))
            head.lineTo(self._svg_to_scene(QPointF(base.x() - uy * head_half, base.y() + ux * head_half)))
            head.lineTo(self._svg_to_scene(QPointF(base.x() + uy * head_half, base.y() - ux * head_half)))
            head.closeSubpath()
            path = path.united(head)
        arrow.setPath(path)
        plate.setVisible(True)
        arrow.setVisible(True)

    def _update_hover(self, position: QPointF) -> None:
        """Highlight the number of the element under the viewport *position*."""
        self._hover_position = QPointF(position)
        if self._redrawing:
            return
        if self._hit_map is None or self._svg_item is None or self._renderer is None:
            self._show_highlight(None)
            return
        inverse, _ok = self.viewportTransform().inverted()
        svg = self._scene_to_svg(inverse.map(QPointF(position)))
        pixels_per_unit = abs(self.transform().m11()) * self._svg_scale()
        tolerance = self.HOVER_TOLERANCE_PX / max(pixels_per_unit, 1e-9)
        mark = self._hit_map.mark_at(Point(svg.x(), svg.y()), tolerance)
        if mark != self._hovered:
            self._show_highlight(mark)

    def _refresh_hover(self) -> None:
        if self._hover_position is None:
            self._show_highlight(None)
        else:
            self._update_hover(self._hover_position)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self._update_hover(event.position())

    def viewportEvent(self, event) -> bool:
        if event.type() == QtCore.QEvent.Type.Leave:
            self._hover_position = None
            self._show_highlight(None)
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        # Panning and zooming move the drawing under a still cursor.
        super().scrollContentsBy(dx, dy)
        if self._hover_position is not None:
            self._update_hover(self._hover_position)

    def reset_view(self) -> None:
        if self._svg_item is None:
            return
        self._pin = None
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

    returnPressed = Signal()
    # GitHub #10 keyboard: Ctrl+↑/↓ previous/next field, Ctrl+Tab next block.
    fieldNavigation = Signal(int)
    blockNavigation = Signal(int)
    COARSE_FACTOR = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel_armed = False
        self.setLocale(QtCore.QLocale.c())
        self.setKeyboardTracking(False)
        # The inner line edit has the focus and would turn Meta+Tab into Tab.
        self.lineEdit().installEventFilter(self)

    @staticmethod
    def _control_held(event) -> bool:
        # Windows/Linux Ctrl; on macOS the physical Control key is Meta in Qt
        # (Cmd is Control there and Cmd+Tab belongs to the system).
        return bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))

    def _block_navigation(self, event) -> bool:
        """Handle Ctrl+Tab / Ctrl+Shift+Tab before Qt's focus chain sees them."""
        if event.type() not in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.ShortcutOverride):
            return False
        if event.key() not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) or not self._control_held(event):
            return False
        if event.type() == QtCore.QEvent.Type.KeyPress:
            backwards = event.key() == Qt.Key.Key_Backtab or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.blockNavigation.emit(-1 if backwards else 1)
        event.accept()
        return True

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        # The line edit would otherwise use Cmd+↓ (end of text) on macOS.
        if watched is self.lineEdit() and (self._block_navigation(event) or self._arrow_keys(event)):
            return True
        return super().eventFilter(watched, event)

    def event(self, event) -> bool:  # noqa: D401 - Qt API
        return self._block_navigation(event) or super().event(event)

    def _arrow_keys(self, event) -> bool:
        """Ctrl+↓/↑ move like Tab/Shift+Tab; Alt+↑/↓ change by a coarse step."""
        if event.type() not in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.ShortcutOverride):
            return False
        if event.key() not in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            return False
        control = self._control_held(event)
        if not control and not event.modifiers() & Qt.KeyboardModifier.AltModifier:
            return False
        if event.type() == QtCore.QEvent.Type.KeyPress:
            direction = 1 if event.key() == Qt.Key.Key_Up else -1
            if control:
                self.fieldNavigation.emit(-direction)
            else:
                self.stepBy(direction * self.COARSE_FACTOR)
        event.accept()
        return True

    def keyPressEvent(self, event) -> None:
        if self._arrow_keys(event):
            return
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()

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


class ParameterScrollArea(QScrollArea):
    """Vertical-only scroll area that is never narrower than its form.

    Its minimum width is the form's, so the dock cannot be dragged so narrow
    that labels, numbers or units are cut off.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        hint = super().minimumSizeHint()
        widget = self.widget()
        if widget is None:
            return hint
        width = widget.minimumSizeHint().width() + self.verticalScrollBar().sizeHint().width() + 2 * self.frameWidth()
        return QSize(max(hint.width(), width), hint.height())


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
        self.toggle_button.setFont(scaled_font(PARAMETER_TITLE_SCALE, bold=True))
        self.toggle_button.setStyleSheet("QToolButton { border: 0; padding: 2px; }")
        layout.addWidget(self.toggle_button)
        self.content = QWidget(self)
        self.form_layout = QFormLayout(self.content)
        self.form_layout.setLabelAlignment(Qt.AlignLeft)
        layout.addWidget(self.content)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        self.toggle_button.toggled.connect(self._set_expanded)

    def apply_field_font(self) -> None:
        """Enlarge labels, numbers and units of the fields (GitHub #11).

        Set on every widget: under the QtAds style sheet Qt does not pass a
        parent's font on to its children.
        """
        font = scaled_font(PARAMETER_FIELD_SCALE)
        for widget in self.content.findChildren(QWidget):
            widget.setFont(font)

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
        self.setWindowTitle(f"smcapp {__version__}")
        self.setWindowIcon(QIcon(str(_resource_path("assets", "smc-logo.png"))))
        # QtAds calculates initial splitter ratios while docks are inserted, so
        # establish the reference size before building the workspace.
        self.resize(1440, 920)

        self._view = SvgGraphicsView()
        self._frequency_axis = FrequencyAxisItem()
        self._plot = pg.PlotWidget(axisItems={"bottom": self._frequency_axis})
        self._config_inputs: Dict[str, QDoubleSpinBox] = {}
        self._parameter_groups: Dict[str, CollapsibleParameterGroup] = {}
        self._engineering_orders: Dict[str, QLabel] = {}
        self._parameter_units: Dict[str, QLabel] = {}
        # Transformer editors (W1, W2, L) by element prefix when last filled.
        self._transformer_baselines: dict[str, tuple[float, ...]] = {}
        # Values shown when the editors were filled; an untouched editor keeps
        # the exact loaded value instead of its rounded display (GitHub #10).
        self._loaded_ui_values: dict[str, float] = {}
        self._transformer_status: dict[str, QLabel] = {}
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
        # HFSS .tab: header row and frequency in THz; experiment: plain GHz pairs.
        self._trace_readers = {"HFSS": HfssTabReader(), "Experiment": TraceFileReader()}
        self._comparison_traces: dict[str, ComparisonTrace] = {}
        self._theory_trace: tuple[object, object] | None = None
        self._previous_theory_trace: tuple[object, object] | None = None
        # Parameters of the calculation running now and of the one shown as SMC.
        self._s21_running_config: S21Config | None = None
        self._theory_config: S21Config | None = None
        self._buffer: ParameterBuffer | None = None
        # Curves unchecked in the legend; the data stays, only the curve hides.
        self._hidden_curves: set[str] = set()
        self._theme = load_theme()
        self._svg_scheme: SvgColorScheme | None = None
        self._muted_labels: list[QLabel] = []
        self._heading_labels: list[QLabel] = []

        self._build_menu()
        self._configure_plot()
        self._build_ui()
        self._remember_transformer_inputs()
        self._apply_material_sync()
        self._update_svg()
        self._apply_theme(self._theme)

    def _build_menu(self) -> None:
        view_menu = self.menuBar().addMenu("Вид")
        self.theme_menu = view_menu.addMenu("Тема")
        self._theme_actions: dict[Theme, QAction] = {}
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for theme in Theme:
            action = QAction(THEME_TITLES[theme], self)
            action.setCheckable(True)
            action.setChecked(theme is self._theme)
            action.triggered.connect(lambda _checked, current=theme: self.set_theme(current))
            theme_group.addAction(action)
            self.theme_menu.addAction(action)
            self._theme_actions[theme] = action

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
        self._default_dock_stylesheet = self.dock_manager.styleSheet()

        self.parameters_dock = CDockWidget("Параметры")
        self.parameters_dock.setObjectName("parameters_dock")
        # No QtAds scroll area around the panel: it has its own vertical one, and
        # the dock's minimum width is the content's, so nothing is cut off.
        self.parameters_dock.setWidget(self._build_controls(), CDockWidget.eInsertMode.ForceNoScrollArea)
        self.parameters_dock.setMinimumSizeHintMode(CDockWidget.eMinimumSizeHintMode.MinimumSizeHintFromContent)

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

        scroll = ParameterScrollArea(panel)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        vbox = QVBoxLayout(inner)

        title = QLabel("Параметры структуры")
        self._heading_labels.append(title)
        vbox.addWidget(title)

        subtitle = QLabel(
            "Номера элементов идут слева направо от ФФО. W1 — ширина слева, W2 — справа; L — общая длина. "
            "Enter в поле обновляет схему; Run S21 пересчитывает график. "
            "Ctrl+↓/↑ — следующее/предыдущее поле, Ctrl+Tab — следующий блок, Alt+↑/↓ — грубый шаг ×10."
        )
        subtitle.setWordWrap(True)
        self._muted_labels.append(subtitle)
        vbox.addWidget(subtitle)

        fields_by_group = {group: [] for group in self._defaults.group_order()}
        for field_info in self._defaults.ui_fields():
            fields_by_group.setdefault(field_info.group, []).append(field_info)

        for group_name in self._defaults.group_order():
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
                prefix = f"{field_info.number} · " if field_info.number is not None else ""
                label = QLabel(prefix + field_info.label)
                label.setToolTip(field_info.description)
                spin.setToolTip(field_info.description)
                self._config_inputs[field_info.name] = spin
                form.addRow(label, self._build_parameter_editor(field_info.name, spin, field_info.suffix))

            if group_fields[0].element_id == "SIS":
                sis_line = next(slot.number for slot in self._defaults.element_slots() if slot.element_id == "SIS-line")
                hint = QLabel(
                    "Wb — ширина для индуктивности растекания токов у детектора. "
                    f"Ширина металла у SIS: элемент {sis_line} «Линия SIS», W1 и W2."
                )
                hint.setWordWrap(True)
                form.addRow(hint)

            element = split_element_field(group_fields[0].name)
            if element is not None and isinstance(self._defaults.element(element[0]), TransformerSection):
                status = QLabel()
                status.setWordWrap(True)
                self._transformer_status[element[0]] = status
                form.addRow(status)
                for info in group_fields:
                    self._config_inputs[info.name].valueChanged.connect(self._refresh_transformer_status)

            box.apply_field_font()
            vbox.addWidget(box)

        controls_box = QGroupBox("Actions")
        controls_box.setObjectName("actions_box")
        self.actions_box = controls_box
        controls_layout = QVBoxLayout(controls_box)

        design_row = QHBoxLayout()
        load_design_button = QPushButton("Открыть параметры…")
        load_design_button.setObjectName("load_parameters_button")
        load_design_button.setToolTip(
            "Загрузить все поля S21Config из версионного файла smcapp и обновить preview. "
            "Форматы Mathcad .mcd/.mcdx не поддерживаются."
        )
        load_design_button.clicked.connect(self._load_design_dialog)
        design_row.addWidget(load_design_button)
        save_design_button = QPushButton("Сохранить параметры…")
        save_design_button.setObjectName("save_parameters_button")
        save_design_button.setToolTip(
            "Сохранить полный набор текущих входных параметров в версионный JSON smcapp; "
            "кривая S21 и Mathcad-лист в файл не входят."
        )
        save_design_button.clicked.connect(self._save_design_dialog)
        design_row.addWidget(save_design_button)
        controls_layout.addLayout(design_row)

        parameter_hint = QLabel("Файл параметров smcapp — не файл Mathcad; S21 рассчитывается отдельно.")
        parameter_hint.setObjectName("parameter_file_hint")
        parameter_hint.setWordWrap(True)
        controls_layout.addWidget(parameter_hint)

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
        run_button.setObjectName("run_s21_button")
        # Much larger than the other buttons (GitHub #11); colours come from the theme.
        run_font = scaled_font(RUN_BUTTON_SCALE, bold=True)
        run_button.setFont(run_font)
        run_button.setMinimumHeight(round(QFontMetrics(run_font).height() * RUN_BUTTON_HEIGHT_LINES))
        run_button.clicked.connect(self._run_s21)
        self._run_s21_button = run_button
        controls_layout.addWidget(run_button)

        self._s21_status = QLabel("The grouped preview mirrors the new backend parameter model.")
        self._s21_status.setWordWrap(True)
        self._muted_labels.append(self._s21_status)
        controls_layout.addWidget(self._s21_status)

        # Buttons keep their whole text: the panel's minimum width grows instead.
        for button in controls_box.findChildren(QPushButton):
            policy = button.sizePolicy()
            policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Minimum)
            button.setSizePolicy(policy)

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
        self._schematic_details = QCheckBox("Пояснения")
        self._schematic_details.setObjectName("schematic_details")
        self._schematic_details.setToolTip(
            "Показать под схемой пояснения: размеры каждого элемента со стрелками в увеличенных выносках. "
            "Номера элементов, SIS и 50 Ω видны всегда"
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
                ("x_min", "X min, GHz", 100.0),
                ("x_max", "X max, GHz", 900.0),
                ("y_min", "Y min, dB", -20.0),
                ("y_max", "Y max, dB", 0.0),
            )
        ):
            controls.addWidget(QLabel(label), 0, column * 2)
            spin = SafeDoubleSpinBox(panel)
            spin.setRange(-1_000_000.0, 1_000_000.0)
            spin.setDecimals(0 if name.startswith("x_") else 2)  # frequencies: 1 GHz
            spin.setValue(value)
            spin.setSingleStep(10.0 if name.startswith("x_") else 5.0)
            spin.setFixedWidth(90)
            spin.returnPressed.connect(self._apply_plot_scale)
            self._plot_scale_inputs[name] = spin
            controls.addWidget(spin, 0, column * 2 + 1)
        controls.addWidget(QLabel("Y line, dB"), 1, 0)
        self._plot_threshold_input = SafeDoubleSpinBox(panel)
        self._plot_threshold_input.setRange(-1_000_000.0, 1_000_000.0)
        self._plot_threshold_input.setDecimals(2)
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
        design_action = self.open_files_menu.addAction("Параметры smcapp")
        design_action.setToolTip("Открыть .smcdesign/.json или старый .aocdesign/.aocapp с параметрами расчёта")
        design_action.triggered.connect(self._load_design_dialog)
        hfss_action = self.open_files_menu.addAction("HFSS")
        hfss_action.setToolTip("Добавить на график расчёт HFSS (.tab, частота в THz, S21 в dB)")
        hfss_action.triggered.connect(lambda: self._open_trace_dialog("HFSS"))
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
        toolbar.addSeparator()

        theme_button = QtWidgets.QToolButton(self)
        theme_button.setObjectName("theme_button")
        theme_button.setText("Тема")
        theme_button.setToolTip("Светлая или тёмная тема; выбор сохраняется")
        theme_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        theme_button.setMenu(self.theme_menu)
        toolbar.addWidget(theme_button)

        # «Буфер» right of «Тема» (GitHub #11): one remembered parameter set
        # with its frozen buff curve.
        self.buffer_menu = QtWidgets.QMenu("Буфер", self)
        self.buffer_store_action = self.buffer_menu.addAction("Записать")
        self.buffer_store_action.setToolTip("Запомнить все параметры и текущую кривую SMC как кривую buff")
        self.buffer_store_action.triggered.connect(self.store_buffer)
        self.buffer_restore_action = self.buffer_menu.addAction("Восстановить")
        self.buffer_restore_action.setToolTip("Вернуть параметры из буфера; кривая buff остаётся")
        self.buffer_restore_action.triggered.connect(self.restore_buffer)
        self.buffer_restore_action.setEnabled(False)
        self.buffer_menu.setToolTipsVisible(True)

        buffer_button = QtWidgets.QToolButton(self)
        buffer_button.setObjectName("buffer_button")
        buffer_button.setText("Буфер")
        buffer_button.setToolTip("Записать параметры и кривую buff или восстановить параметры")
        buffer_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        buffer_button.setMenu(self.buffer_menu)
        toolbar.addWidget(buffer_button)

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
                # Room above the content's minimum: a theme with slightly wider
                # buttons then does not push the other panels aside.
                minimum = self.parameters_dock.widget().minimumSizeHint().width() + PARAMETERS_WIDTH_RESERVE
                parameters_width = max(280, total_width // 4, minimum)
                root_splitter.setSizes([parameters_width, total_width - parameters_width])
        with contextlib.suppress(Exception):
            right_splitter = self.schematic_dock.dockAreaWidget().parentSplitter()
            total_height = max(sum(right_splitter.sizes()), self.height() - 80)
            right_splitter.setSizes(
                [
                    # Below half the height the schematic would shrink; the log
                    # gives way so the larger plot texts (GitHub #11) leave a
                    # data area tall enough for the legend.
                    total_height * 50 // 100,
                    total_height * 38 // 100,
                    total_height * 12 // 100,
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
        self._sync_parameters_minimum_width()
        self._apply_default_dock_sizes()
        self.save_settings()

    @property
    def theme(self) -> Theme:
        return self._theme

    def set_theme(self, theme: Theme) -> None:
        """Switch the theme on the fly and remember it for the next launch."""
        self._apply_theme(theme)
        save_theme(self._theme)

    def _apply_theme(self, theme: Theme) -> None:
        """Recolour widgets, QtAds docks, the plot and the schematic backdrop."""
        self._theme = Theme(theme)
        colors = THEME_COLORS[self._theme]
        assets = _resource_path("assets")
        apply_application_theme(QApplication.instance(), self._theme, assets)
        self.dock_manager.setStyleSheet(dock_stylesheet(self._theme, self._default_dock_stylesheet, assets))
        for label in self._muted_labels:
            label.setStyleSheet(f"color: {colors.muted_text};")
        heading = "font-weight: bold; font-size: 16px;"
        if colors.heading_text:
            heading += f" color: {colors.heading_text};"
        for label in self._heading_labels:
            label.setStyleSheet(heading)
        if self._run_s21_button is not None:
            self._run_s21_button.setStyleSheet(run_button_stylesheet(self._theme))
        backdrop = colors.schematic_backdrop
        self._view.setBackgroundBrush(QBrush(QColor(backdrop)) if backdrop else QBrush())
        self._view.set_highlight_color(colors.schematic_highlight)
        if colors.schematic_scheme != self._svg_scheme:
            # Redraw the sheet in the theme's colours; set_svg keeps zoom and position.
            with contextlib.suppress(ValueError, OSError):
                self._render_svg()
        self._apply_plot_theme()
        self._refresh_transformer_status()
        self._theme_actions[self._theme].setChecked(True)
        self._sync_parameters_minimum_width()
        # Buttons take the new style sheet's padding only when polished.
        QtCore.QTimer.singleShot(0, self._sync_parameters_minimum_width)

    def _sync_parameters_minimum_width(self) -> None:
        """Keep the parameter panel at least as wide as its content.

        QtAds caches a dock area's minimum size when a panel is inserted, but a
        theme changes button padding and so the content's minimum width.
        """
        try:
            area = self.parameters_dock.dockAreaWidget()
        except RuntimeError:  # the deferred call came after the window was closed
            return
        if area is None:
            return
        previous = getattr(self, "_parameters_minimum_area", None)
        if previous is not None and previous is not area:
            with contextlib.suppress(RuntimeError):  # the old area may be deleted
                previous.setMinimumWidth(0)
        self._parameters_minimum_area = area
        panel = self.parameters_dock.widget()
        panel.layout().activate()
        # The area's own border (1 px each side in the styled themes) and margins.
        frame = 2 * area.frameWidth() + area.contentsMargins().left() + area.contentsMargins().right()
        if area.isVisible() and panel.isVisible():
            frame = max(frame, min(area.width() - panel.width(), 24))
        area.setMinimumWidth(panel.minimumSizeHint().width() + frame)

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
        selected, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить параметры smcapp",
            str(Path(self._last_files_directory()) / "parameters.smcdesign"),
            "Параметры smcapp (*.smcdesign);;JSON (*.json)",
        )
        if not selected:
            return
        path = Path(selected)
        if not path.suffix:
            path = path.with_suffix(".json" if selected_filter == "JSON (*.json)" else ".smcdesign")
        try:
            self.save_design_to_path(path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка сохранения параметров", str(exc))

    def _load_design_dialog(self) -> None:
        """Select a smcapp parameter set and apply it to every editor."""
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Открыть параметры smcapp",
            self._last_files_directory(),
            "Параметры smcapp (*.smcdesign *.json *.aocdesign *.aocapp)",
        )
        if not selected:
            return
        try:
            self.load_design_from_path(selected)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Ошибка открытия параметров", str(exc))

    def _open_trace_dialog(self, kind: str) -> None:
        """Select and add an HFSS or experiment comparison table."""
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            f"Открыть {kind}",
            self._last_files_directory(),
            _COMPARISON_FILE_FILTERS[kind],
        )
        if not selected:
            return
        try:
            self.load_comparison_trace(kind, selected)
        except (OSError, UnicodeError, ValueError) as exc:
            QMessageBox.critical(self, f"Ошибка импорта {kind}", str(exc))

    def load_comparison_trace(self, kind: str, path: str | Path) -> ComparisonTrace:
        """Load a plot-only trace; it never changes calculation parameters."""
        if kind not in COMPARISON_CURVE_NAMES:
            raise ValueError(f"Неизвестный тип сравнительного графика: {kind}.")
        trace = self._trace_readers[kind].load(path)
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
        self._apply_config(config, same_material)
        self._remember_file_directory(path)
        if self._s21_status is not None:
            self._s21_status.setText(f"Параметры загружены: {Path(path).expanduser()}")
        return config

    def _apply_config(self, config: S21Config, same_material: bool) -> None:
        """Fill every editor from a validated configuration and redraw the schematic.

        Untouched editors then build back the exact values (not their rounded
        display), and the transformer n/dl come from ``config`` itself.
        """
        if composition(config) != composition(self._defaults):
            # The panel is rebuilt for another composition in WP-044, stage 3.
            raise ValueError("Состав элементов Mex01/Mex02/Mex03 отличается от текущей панели.")
        if self._same_materials_checkbox is not None:
            self._same_materials_checkbox.setChecked(same_material)

        self._defaults = config
        for name, spin in self._config_inputs.items():
            blocked = spin.blockSignals(True)
            spin.setValue(config.ui_value(name))
            spin.blockSignals(blocked)
            self._loaded_ui_values[name] = spin.value()
        self._remember_transformer_inputs()
        if same_material:
            self._apply_material_sync()
        else:
            for bottom_name in self._material_sync_map.values():
                self._config_inputs[bottom_name].setEnabled(True)
        self._update_svg()

    @property
    def parameter_buffer(self) -> ParameterBuffer | None:
        return self._buffer

    def store_buffer(self) -> ParameterBuffer | None:
        """«Буфер → Записать»: remember all parameters and freeze SMC as buff.

        A validation error is shown in a dialog and leaves the buffer as it was.
        """
        try:
            config = self._build_config()
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка записи в буфер", str(exc))
            return None
        same_material = self._same_materials_checkbox is not None and self._same_materials_checkbox.isChecked()
        trace = None
        if self._theory_trace is not None:
            frequencies, values = self._theory_trace
            trace = (list(frequencies), list(values))
        self._buffer = ParameterBuffer(config=config, same_material=same_material, trace=trace)
        self.buffer_restore_action.setEnabled(True)
        self._redraw_plot()

        if trace is None:
            message = "Буфер: параметры записаны; кривой buff нет — расчёт S21 ещё не выполнялся."
        else:
            message = f"Буфер: параметры и кривая buff ({len(trace[0])} точек) записаны."
            if self._theory_config is not None and self._theory_config != config:
                message += " Параметры изменены после последнего расчёта: buff — кривая этого расчёта."
        self._append_log_message(message)
        if self._s21_status is not None:
            self._s21_status.setText(message)
        return self._buffer

    def restore_buffer(self) -> S21Config | None:
        """«Буфер → Восстановить»: put the remembered parameters back; buff stays."""
        if self._buffer is None:
            return None
        self._apply_config(self._buffer.config, self._buffer.same_material)
        message = "Буфер: параметры восстановлены; кривая buff не изменена."
        self._append_log_message(message)
        if self._s21_status is not None:
            self._s21_status.setText(message)
        return self._buffer.config

    def _create_spinbox(self, name: str, field_info) -> SafeDoubleSpinBox:
        spin = SafeDoubleSpinBox()
        spin.setDecimals(field_info.decimals)
        spin.setRange(field_info.minimum, field_info.maximum)
        spin.setSingleStep(field_info.step)
        spin.setValue(self._defaults.ui_value(name))
        self._loaded_ui_values[name] = spin.value()
        spin.returnPressed.connect(self._update_svg)
        spin.fieldNavigation.connect(lambda step, current=spin: self._move_to_field(current, step))
        spin.blockNavigation.connect(lambda step, current=spin: self._move_to_block(current, step))
        if name in self._material_sync_map:
            spin.valueChanged.connect(self._apply_material_sync)
        return spin

    def _parameter_blocks(self) -> list[tuple[CollapsibleParameterGroup, list[SafeDoubleSpinBox]]]:
        """Parameter blocks top to bottom with their editable fields in form order."""
        blocks = []
        for box in self._parameter_groups.values():
            form = box.form_layout
            spins = []
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                widget = item.widget() if item is not None else None
                if widget is None:
                    continue
                candidates = (
                    [widget] if isinstance(widget, SafeDoubleSpinBox) else widget.findChildren(SafeDoubleSpinBox)
                )
                spins.extend(spin for spin in candidates if spin.isEnabled())
            blocks.append((box, spins))
        return blocks

    def _focus_field(self, spin: SafeDoubleSpinBox) -> None:
        self.parameters_scroll.ensureWidgetVisible(spin)
        spin.setFocus(Qt.FocusReason.TabFocusReason)  # selects the value, as Tab does
        spin.selectAll()

    def _move_to_field(self, current: SafeDoubleSpinBox, step: int) -> None:
        """Ctrl+↓/Ctrl+↑: the next/previous field of expanded blocks, like Tab."""
        spins = [spin for box, block in self._parameter_blocks() if box.isChecked() for spin in block]
        if current in spins:
            self._focus_field(spins[(spins.index(current) + step) % len(spins)])

    def _move_to_block(self, current: SafeDoubleSpinBox, step: int) -> None:
        """Ctrl+Tab/Ctrl+Shift+Tab: the first field of the next/previous block."""
        blocks = [(box, spins) for box, spins in self._parameter_blocks() if spins]
        index = next((i for i, (_box, spins) in enumerate(blocks) if current in spins), None)
        if index is None:
            return
        box, spins = blocks[(index + step) % len(blocks)]
        box.setChecked(True)  # a collapsed target block opens
        QApplication.processEvents()
        self._focus_field(spins[0])

    def _build_parameter_editor(self, name: str, spin: SafeDoubleSpinBox, suffix: str) -> QWidget:
        """Keep units outside every numeric editor, preserving SI conversions."""
        scale = S21Config.field_scale(name)
        if not suffix:
            return spin
        editor = QWidget(self)
        layout = QHBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(spin, stretch=1)
        scaled = scale != 1.0 and name != "sis_cap_f_per_um2"
        if scaled:
            exponent = -round(math.log10(scale))
            # σ is entered per µm (18.000 1/(Ω·µm)), the stored value per metre.
            text = "1/(Ω·µm)" if name.startswith("sigma0_") else f"×10^{exponent} m"
        else:
            text = suffix.strip().replace("Ohm", "Ω").replace("um", "µm").replace("^2", "²").replace("*", "·")
            text = text.replace("deg", "°")
        order = QLabel(text, editor)
        order.setMinimumWidth(78)
        self._parameter_units[name] = order
        if scaled:
            self._engineering_orders[name] = order
        layout.addWidget(order)
        return editor

    def _set_plot_title(self, color: str | None = None) -> None:
        options = {"size": f"{scaled_point_size(PLOT_TITLE_SCALE)}pt", "bold": True}
        if color is not None:
            options["color"] = color
        plot_item = self._plot.getPlotItem()
        plot_item.setTitle("S21 vs Frequency", **options)
        # setTitle fixes the title row at 30 px, which would clip the larger title.
        title_height = max(30, round(QFontMetrics(scaled_font(PLOT_TITLE_SCALE, bold=True)).height() * 1.5))
        plot_item.titleLabel.setMaximumHeight(title_height)
        plot_item.layout.setRowFixedHeight(0, title_height)

    def _configure_plot(self) -> None:
        self._set_plot_title()
        plot_item = self._plot.getPlotItem()
        axis_label_style = {"font-size": f"{scaled_point_size(PLOT_AXIS_LABEL_SCALE)}pt"}
        self._plot.setLabel("left", "S21", units="dB", **axis_label_style)
        self._plot.setLabel("bottom", "Frequency", units="GHz", **axis_label_style)
        tick_font = scaled_font(PLOT_TICK_SCALE)
        for axis_name in ("left", "bottom"):
            plot_item.getAxis(axis_name).setStyle(tickFont=tick_font)
        self._plot.showGrid(x=True, y=True, alpha=0.10)
        self._plot.setMenuEnabled(False)
        self._plot_legend = self._plot.addLegend(
            offset=(10, 10),
            sampleType=CheckableItemSample,
            labelTextSize=f"{scaled_point_size(PLOT_LEGEND_SCALE)}pt",
        )
        self._plot_legend.sigSampleClicked.connect(self._on_legend_sample_clicked)
        self._plot_threshold_line = pg.InfiniteLine(pos=-5.0, angle=0)
        self._plot_threshold_line.setZValue(-1)
        self._plot.addItem(self._plot_threshold_line, ignoreBounds=True)
        self._plot.getPlotItem().setContentsMargins(12, 12, 12, 12)
        self._apply_plot_theme()
        self._plot_initial_range = (100.0, 900.0, -20.0, 0.0)
        self._plot_hover_label = QLabel(self._plot)
        self._plot_hover_label.setStyleSheet(
            "QLabel { background: rgba(30, 30, 30, 150); color: white; padding: 3px 6px; border-radius: 3px; }"
        )
        self._plot_hover_label.setFont(scaled_font(PLOT_HOVER_SCALE))
        self._plot_hover_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._plot_hover_label.hide()
        self._plot.scene().sigMouseMoved.connect(self._on_plot_mouse_moved)
        # Leaving the widget sends no further moves, so hide the label on leave.
        self._plot.viewport().installEventFilter(self)
        self._plot.getPlotItem().vb.sigXRangeChanged.connect(self._sync_frequency_axis_unit)
        self._restore_plot_scale()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QtCore.QEvent.Type.Leave and watched == self._plot.viewport():
            self._plot_hover_label.hide()
        return super().eventFilter(watched, event)

    def _apply_plot_theme(self) -> None:
        """Recolour the plot in place, keeping curves and the current range."""
        colors = THEME_COLORS[self._theme]
        pg.setConfigOption("background", colors.plot_background)
        pg.setConfigOption("foreground", colors.plot_foreground)
        self._plot.setBackground(colors.plot_background)
        self._set_plot_title(colors.plot_foreground)
        axis_pen = pg.mkPen(colors.plot_foreground, width=1)
        for axis_name in ("left", "bottom"):
            axis = self._plot.getPlotItem().getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)
        self._plot_legend.setLabelTextColor(colors.plot_foreground)
        self._plot_threshold_line.setPen(pg.mkPen(colors.threshold_line, width=1))
        for item in self._plot.listDataItems():
            style = self._curve_style(item.name())
            item.setPen(style["pen"])
            if "symbolBrush" in style:
                item.setSymbolBrush(style["symbolBrush"])
                item.setSymbolPen(style["symbolPen"])
        for sample, _label in self._plot_legend.items:
            sample.update()  # the check box follows the legend text colour

    def _curve_style(self, name: str) -> dict:
        """Return the pyqtgraph pen options for a named curve in the current theme.

        Base width 2 px (GitHub #11): SMC with small but visible points, prev
        red, buff grey and twice as thick, HFSS dashed (black; light in the
        dark theme), exp dark green, finely dotted and 1.5 times as thick.
        """
        colors = THEME_COLORS[self._theme]
        if name == SMC_CURVE:
            color = colors.smc_curve
            return {
                "pen": pg.mkPen(color=color, width=BASE_CURVE_WIDTH),
                "symbol": "o",
                "symbolSize": SMC_SYMBOL_SIZE,
                "symbolBrush": color,
                "symbolPen": color,
            }
        if name == PREV_CURVE:
            return {"pen": pg.mkPen(color=colors.prev_curve, width=BASE_CURVE_WIDTH)}
        if name == BUFF_CURVE:
            return {"pen": pg.mkPen(color=colors.buff_curve, width=2 * BASE_CURVE_WIDTH)}
        if name == HFSS_CURVE:
            pen = pg.mkPen(color=colors.hfss_curve, width=BASE_CURVE_WIDTH, style=Qt.PenStyle.DashLine)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)  # square caps would close the gaps
            return {"pen": pen}
        if name == EXP_CURVE:
            pen = pg.mkPen(color=colors.exp_curve, width=1.5 * BASE_CURVE_WIDTH)
            # Round dots of the pen width, one free dot width apart.
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setDashPattern([0.01, 2.0])
            return {"pen": pen}
        raise ValueError(f"Неизвестная кривая графика: {name}.")

    def is_curve_visible(self, name: str) -> bool:
        """Whether the curve's legend check box is on (also for curves not plotted yet)."""
        return name not in self._hidden_curves

    def set_curve_visible(self, name: str, visible: bool) -> None:
        """Show or hide a curve as its legend check box does; the data stays."""
        if visible:
            self._hidden_curves.discard(name)
        else:
            self._hidden_curves.add(name)
        for item in self._plot.listDataItems():
            if item.name() == name:
                item.setVisible(visible)
        for sample, _label in self._plot_legend.items:
            sample.update()

    def _on_legend_sample_clicked(self, item) -> None:
        """The legend sample already toggled the curve; remember it for redraws."""
        self.set_curve_visible(item.name(), item.isVisible())

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
        view_box = self._plot.getPlotItem().vb
        # Only the data area has coordinates; the title and axes around it do not.
        if not view_box.sceneBoundingRect().contains(scene_position):
            self._plot_hover_label.hide()
            return
        # Over the legend the label would cover the check boxes below the cursor.
        if self._plot_legend.sceneBoundingRect().contains(scene_position):
            self._plot_hover_label.hide()
            return
        cursor_value = view_box.mapSceneToView(scene_position)
        self._plot_hover_label.setText(format_plot_coordinates(cursor_value.x(), cursor_value.y()))
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
            with self._legend_for_export():
                self._plot.scene().render(painter, QtCore.QRectF(0, 0, width, height), source)
        finally:
            painter.end()
        writer = QImageWriter(str(destination), b"png")
        if not writer.write(image):
            raise OSError(f"Не удалось сохранить PNG: {writer.errorString()}")
        self._remember_file_directory(destination)
        return destination

    @contextlib.contextmanager
    def _legend_for_export(self):
        """List only the visible curves, without check boxes and to scale, while exporting."""
        legend = self._plot_legend
        entries = [(sample.item, label.text) for sample, label in legend.items]

        def rebuild(sample_type, only_visible: bool) -> None:
            legend.clear()
            legend.sampleType = sample_type
            for item, name in entries:
                if item.isVisible() or not only_visible:
                    legend.addItem(item, name)
            self._arrange_legend()

        # pyqtgraph keeps the legend unscaled on screen; the PNG is rendered
        # about twice as wide, so it must scale with the rest of the plot.
        ignores_transformations = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
        rebuild(PlainItemSample, only_visible=True)
        legend.setFlag(ignores_transformations, False)
        try:
            yield
        finally:
            legend.setFlag(ignores_transformations, True)
            rebuild(CheckableItemSample, only_visible=False)

    def _build_config(self) -> S21Config:
        values = dict(self._defaults.__dict__)
        elements: dict[str, dict[str, float]] = {}
        for name, spin in self._config_inputs.items():
            spin.interpretText()
            if spin.value() == self._loaded_ui_values.get(name):
                continue  # untouched: keep the exact value, not its rounded display
            value = spin.value() / S21Config.field_scale(name)
            target = split_element_field(name)
            if target is None:
                values[name] = value
            else:
                elements.setdefault(target[0], {})[target[1]] = value

        if self._same_materials_checkbox is not None and self._same_materials_checkbox.isChecked():
            for top_name, bot_name in self._material_sync_map.items():
                values[bot_name] = values[top_name]
        config = S21Config(**values)

        for prefix, changes in elements.items():
            element = config.element(prefix)
            if isinstance(element, TransformerSection):
                continue  # derived below from W1, W2 and L together
            config = with_element(config, prefix, replace(element, **changes))
        for prefix in self._transformer_status:
            current = self._transformer_inputs(prefix)
            if current == self._transformer_baselines.get(prefix):
                # Keep the exact original discretization for untouched elements.
                continue
            try:
                steps = derive_transformer_steps(
                    *(value * 1e-6 for value in current), max_dl_um=transformer_dl_max_um(prefix in CORNERS)
                )
            except ValueError as error:
                number = next(slot.number for slot in config.element_slots() if slot.prefix == prefix)
                raise ValueError(f"Элемент {number}: {error}") from error
            # A touched width takes the editor value, an untouched one stays exact.
            changes = elements.get(prefix, {})
            element = config.element(prefix)
            transformer = TransformerSection(
                changes.get("w1_m", element.w1_m), changes.get("w2_m", element.w2_m), steps.n_um, steps.dl_m
            )
            config = with_element(config, prefix, transformer)
        return config

    def _transformer_inputs(self, prefix: str) -> tuple[float, ...]:
        return tuple(self._config_inputs[f"{prefix}_{suffix}"].value() for suffix in ("w1_m", "w2_m", "length_m"))

    def _remember_transformer_inputs(self) -> None:
        self._transformer_baselines = {prefix: self._transformer_inputs(prefix) for prefix in self._transformer_status}
        self._refresh_transformer_status()

    def _refresh_transformer_status(self) -> None:
        colors = THEME_COLORS[self._theme]
        for prefix, status in self._transformer_status.items():
            if prefix not in self._transformer_baselines:
                continue
            try:
                current = self._transformer_inputs(prefix)
                if current == self._transformer_baselines[prefix]:
                    element = self._defaults.element(prefix)
                    status.setText(f"n={element.n_um:g}; dl={element.dl_m * 1e6:g} µm (из файла/исходных параметров)")
                else:
                    steps = derive_transformer_steps(
                        *(value * 1e-6 for value in current), max_dl_um=transformer_dl_max_um(prefix in CORNERS)
                    )
                    status.setText(f"n={steps.n_um}; ступеней: {steps.intervals + 1}; dl={steps.dl_m * 1e6:g} µm")
                status.setStyleSheet(f"color: {colors.muted_text};")
            except ValueError as error:
                status.setText(str(error))
                status.setStyleSheet(f"color: {colors.error_text};")

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
            self._render_svg()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))

    def _render_svg(self) -> None:
        """Draw the current parameters in the colours of the current theme."""
        scheme = THEME_COLORS[self._theme].schematic_scheme
        details = self._schematic_details.isChecked()
        drawing = self._use_case.draw(self._build_config(), show_details=details, scheme=scheme)
        self._svg_scheme = scheme
        anchor = QPointF(SIGNAL_INPUT.x, SIGNAL_INPUT.y)
        hit_map = ElementHitMap.from_geometry(drawing.geometry)
        self._view.set_svg(drawing.svg, fit_width=details, anchor=anchor, hit_map=hit_map)

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
        self._s21_running_config = config
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
        self._theory_config = self._s21_running_config
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
        self._theory_config = None  # set by _on_s21_finished for a real run
        self._redraw_plot()

    def _redraw_plot(self) -> None:
        """Render SMC and all optional comparisons with a shared legend."""
        self._plot.clear()
        self._plot.addItem(self._plot_threshold_line, ignoreBounds=True)
        curves: list[tuple[str, object, object]] = []
        if self._theory_trace is not None:
            curves.append((SMC_CURVE, *self._theory_trace))
        if self._previous_theory_trace is not None:
            curves.append((PREV_CURVE, *self._previous_theory_trace))
        if self._buffer is not None and self._buffer.trace is not None:
            curves.append((BUFF_CURVE, *self._buffer.trace))
        for kind, name in COMPARISON_CURVE_NAMES.items():
            trace = self._comparison_traces.get(kind)
            if trace is not None:
                curves.append((name, trace.frequencies, trace.coefficients))
        # Legend in the GitHub #11 order; unchecked curves stay hidden.
        order = (SMC_CURVE, PREV_CURVE, BUFF_CURVE, HFSS_CURVE, EXP_CURVE)
        for name, frequencies, values in sorted(curves, key=lambda curve: order.index(curve[0])):
            item = self._plot.plot(frequencies, values, name=name, **self._curve_style(name))
            item.setZValue(_CURVE_Z_VALUES[name])
            item.setVisible(self.is_curve_visible(name))
        self._arrange_legend()

        # PlotItem enables auto-range again when curves are cleared/re-added.
        # Reapply the user's Home range so recalculation/import cannot silently
        # replace the requested issue-4 defaults (100…900 GHz, -20…0 dB).
        self._restore_plot_scale()

    def _arrange_legend(self) -> None:
        """Lay the legend out from its top row: one column, two for many curves.

        LegendItem.addItem continues below rows it has removed (the grid keeps
        its row count), so the entries could slide out of the plot area; and
        with the larger text (GitHub #11) five rows in one column would not
        fit a 1440×920 window.
        """
        legend = self._plot_legend
        columns = 1 if len(legend.items) <= LEGEND_SINGLE_COLUMN_MAX else 2
        for sample, label in legend.items:
            legend.layout.removeItem(sample)
            legend.layout.removeItem(label)
        for index, (sample, label) in enumerate(legend.items):
            row, column = divmod(index, columns)
            legend.layout.addItem(sample, row, 2 * column, alignment=Qt.AlignmentFlag.AlignVCenter)
            legend.layout.addItem(label, row, 2 * column + 1)
        legend.columnCount = columns
        legend.rowCount = math.ceil(len(legend.items) / columns)
        legend.updateSize()
        legend.layout.activate()

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
                "smcapp\n"
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
        # The legend's pyqtgraph anchor re-reads its ViewBox on every legend
        # geometry change. After a theme switch the legend still resizes while
        # the window is destroyed, after the ViewBox is gone, which prints a
        # RuntimeError on exit. A closed main window no longer needs anchoring.
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            legend = self._plot_legend
            legend.geometryChanged.disconnect(legend._GraphicsWidgetAnchor__geometryChanged)
        self._cleanup_update_thread()
        if self._s21_thread is not None:
            self._s21_thread.requestInterruption()
            self._s21_thread.quit()
            self._s21_thread.wait(1000)
        super().closeEvent(event)


def run_app(use_case: GenerateStructureUseCase, s21_use_case: CalculateS21UseCase) -> None:
    QtCore.QCoreApplication.setOrganizationName("smcapp")
    QtCore.QCoreApplication.setApplicationName("smcapp")
    app = QApplication(sys.argv)
    migrate_legacy_settings(QSettings("AOCapp", "AOCapp"), QSettings())
    window = MainWindow(use_case, s21_use_case)
    window.resize(1440, 920)
    window.show()
    app.exec()
