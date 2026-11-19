"""Interface scale (WP-065, GitHub #13): one preset for everything, a factor per area.

The preset scales the application font, so every widget that follows it —
menus, toolbar, fields, buttons, dialogs — grows at once and without a
restart; the larger texts of WP-043 are multiples of that font and follow
too.  An area factor enlarges one part on top of the preset: the parameter
panel, the plot texts or the numbers on the schematic.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# Preset key → (menu title, factor of the platform font).  «Обычный» is the
# size before WP-065.
UI_SCALE_PRESETS: dict[str, tuple[str, float]] = {
    "small": ("Мелкий", 0.9),
    "normal": ("Обычный", 1.0),
    "large": ("Крупный", 1.25),
    "max": ("Максимальный", 1.5),
}
DEFAULT_UI_SCALE = "normal"

# Area key → menu title; each is enlarged by one of AREA_SCALE_STEPS.
UI_SCALE_AREAS: dict[str, str] = {
    "parameters": "Панель параметров",
    "plot": "График",
    "schematic": "Номера на схеме",
}
AREA_SCALE_STEPS: tuple[float, ...] = (1.0, 1.25, 1.5, 1.75, 2.0)

_SETTINGS_PRESET = "View/ui_scale"
_SETTINGS_AREA = "View/area_scale/{}"
# The platform font before any preset, kept on the application so that
# windows created later (and tests) never compound the factor.
_BASE_FONT_PROPERTY = "smcapp_base_point_size"
_FALLBACK_POINT_SIZE = 10.0
# Widget classes the platform may give their own font (macOS: QToolButton 10 pt,
# QHeaderView 11 pt …; Windows: QMenu, QMessageBox …).  The application font
# does not reach them, so each is scaled from its own platform size.
_CLASS_FONT_NAMES = (
    "QAbstractButton",
    "QPushButton",
    "QToolButton",
    "QCheckBox",
    "QRadioButton",
    "QLabel",
    "QComboBox",
    "QMenu",
    "QMenuBar",
    "QTabBar",
    "QHeaderView",
    "QListView",
    "QTreeView",
    "QTableView",
    "QGroupBox",
    "QMessageBox",
    "QStatusBar",
    "QToolTip",
    "QTipLabel",
    "QDockWidgetTitle",
    "QMdiSubWindowTitleBar",
    "QSmallFont",
    "QMiniFont",
)
_base_class_sizes: dict[str, float] | None = None


@dataclass(frozen=True)
class UiScale:
    """The chosen preset and the factor of every area."""

    preset: str = DEFAULT_UI_SCALE
    areas: tuple[tuple[str, float], ...] = tuple((area, 1.0) for area in UI_SCALE_AREAS)

    @property
    def factor(self) -> float:
        return UI_SCALE_PRESETS[self.preset][1]

    def area(self, name: str) -> float:
        return dict(self.areas)[name]

    def with_preset(self, preset: str) -> UiScale:
        if preset not in UI_SCALE_PRESETS:
            raise ValueError(f"Неизвестный масштаб: {preset}")
        return UiScale(preset, self.areas)

    def with_area(self, name: str, factor: float) -> UiScale:
        if name not in UI_SCALE_AREAS:
            raise ValueError(f"Неизвестная область: {name}")
        if factor not in AREA_SCALE_STEPS:
            raise ValueError(f"Масштаб области должен быть одним из {AREA_SCALE_STEPS}")
        return UiScale(self.preset, tuple((area, factor if area == name else value) for area, value in self.areas))

    def stepped(self, step: int) -> UiScale:
        """The next larger (+1) or smaller (−1) preset; the ends stay where they are."""
        keys = list(UI_SCALE_PRESETS)
        index = min(max(keys.index(self.preset) + step, 0), len(keys) - 1)
        return self.with_preset(keys[index])


def load_ui_scale(settings: QSettings | None = None) -> UiScale:
    """The saved scale; anything unknown falls back to «Обычный» / 100 %."""
    settings = settings or QSettings()
    preset = settings.value(_SETTINGS_PRESET, DEFAULT_UI_SCALE, type=str)
    scale = UiScale(preset if preset in UI_SCALE_PRESETS else DEFAULT_UI_SCALE)
    for area in UI_SCALE_AREAS:
        try:
            factor = float(settings.value(_SETTINGS_AREA.format(area), 1.0))
        except (TypeError, ValueError):
            continue
        if factor in AREA_SCALE_STEPS:
            scale = scale.with_area(area, factor)
    return scale


def save_ui_scale(scale: UiScale, settings: QSettings | None = None) -> None:
    settings = settings or QSettings()
    settings.setValue(_SETTINGS_PRESET, scale.preset)
    for area, factor in scale.areas:
        settings.setValue(_SETTINGS_AREA.format(area), factor)


def base_point_size(app: QApplication | None = None) -> float:
    """The platform font size before any preset (13 pt on macOS, 9 pt on Windows)."""
    global _base_class_sizes
    app = app or QApplication.instance()
    stored = app.property(_BASE_FONT_PROPERTY)
    if stored:
        return float(stored)
    size = QApplication.font().pointSizeF()
    size = size if size > 0 else _FALLBACK_POINT_SIZE
    # Every listed class: one the platform registered at the default size
    # (macOS: QPushButton 13 pt) keeps it too and cannot be told apart.
    _base_class_sizes = {
        name: QApplication.font(name).pointSizeF()
        for name in _CLASS_FONT_NAMES
        if QApplication.font(name).pointSizeF() > 0
    }
    app.setProperty(_BASE_FONT_PROPERTY, size)
    return size


def base_class_point_sizes() -> dict[str, float]:
    """Platform sizes of the widget classes with their own font (see :data:`_CLASS_FONT_NAMES`)."""
    base_point_size()
    return dict(_base_class_sizes or {})


def apply_application_font(scale: UiScale, app: QApplication | None = None) -> bool:
    """Set the application font and the platform's class fonts to the preset.

    Also after a style change: ``QApplication.setStyle`` (a theme switch)
    restores the platform's class fonts.  ``True`` if a size changed.
    """
    app = app or QApplication.instance()
    size = round(base_point_size(app) * scale.factor, 1)
    changed = False
    font = QFont(QApplication.font())
    if font.pointSizeF() != size:
        font.setPointSizeF(size)
        QApplication.setFont(font)
        changed = True
    for name, class_size in base_class_point_sizes().items():
        class_font = QFont(QApplication.font(name))
        target = round(class_size * scale.factor, 1)
        if class_font.pointSizeF() != target:
            class_font.setPointSizeF(target)
            QApplication.setFont(class_font, name)
            changed = True
    return changed
