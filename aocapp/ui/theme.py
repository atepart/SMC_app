"""Light and dark colour themes for the desktop UI.

The light theme is the platform look the application always had.  The dark
theme follows the QmixElements style: anthracite surfaces, light text and an
orange accent for the active dock tab, headings, selection and pressed
toolbar buttons.  Widgets are recoloured through the application palette and
style sheet, QtAds docks through their own manager style sheet, and pyqtgraph
through the colours in :class:`ThemeColors`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEME_SETTINGS_KEY = "Appearance/theme"
_NATIVE_STYLE_PROPERTY = "aocappNativeStyle"


class Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"


THEME_TITLES = {Theme.LIGHT: "Светлая", Theme.DARK: "Тёмная"}

ACCENT = "#f39c12"


@dataclass(frozen=True)
class ThemeColors:
    """Colours that Qt palettes and style sheets cannot reach."""

    plot_background: str
    plot_foreground: str
    previous_curve: tuple[int, int, int, int]
    theory_curve: str
    experiment_curve: str
    threshold_line: str
    muted_text: str
    error_text: str
    # ``None`` keeps the platform default (the light theme's former look).
    heading_text: str | None
    schematic_backdrop: str | None


THEME_COLORS = {
    Theme.LIGHT: ThemeColors(
        plot_background="#ffffff",
        plot_foreground="#7f7f7f",
        previous_curve=(70, 70, 70, 153),
        theory_curve="#1f77b4",
        experiment_curve="#2ca02c",
        threshold_line="#dc2626",
        muted_text="#555555",
        error_text="#b91c1c",
        heading_text=None,
        schematic_backdrop=None,
    ),
    Theme.DARK: ThemeColors(
        plot_background="#232323",
        plot_foreground="#b4b4b4",
        previous_curve=(200, 200, 200, 140),
        theory_curve="#5dade2",
        experiment_curve="#58d68d",
        threshold_line="#ef4444",
        muted_text="#a6a6a6",
        error_text="#f87171",
        heading_text=ACCENT,
        schematic_backdrop="#1b1b1b",
    ),
}


_DARK_PALETTE = {
    QPalette.ColorRole.Window: "#2b2b2b",
    QPalette.ColorRole.WindowText: "#e6e6e6",
    QPalette.ColorRole.Base: "#232323",
    QPalette.ColorRole.AlternateBase: "#303030",
    QPalette.ColorRole.ToolTipBase: "#3c3c3c",
    QPalette.ColorRole.ToolTipText: "#e6e6e6",
    QPalette.ColorRole.PlaceholderText: "#8a8a8a",
    QPalette.ColorRole.Text: "#e6e6e6",
    QPalette.ColorRole.Button: "#3c3c3c",
    QPalette.ColorRole.ButtonText: "#e6e6e6",
    QPalette.ColorRole.BrightText: "#ff9900",
    QPalette.ColorRole.Light: "#4a4a4a",
    QPalette.ColorRole.Midlight: "#3f3f3f",
    QPalette.ColorRole.Mid: "#333333",
    QPalette.ColorRole.Dark: "#1e1e1e",
    QPalette.ColorRole.Shadow: "#141414",
    QPalette.ColorRole.Highlight: ACCENT,
    QPalette.ColorRole.HighlightedText: "#1e1e1e",
    QPalette.ColorRole.Link: "#ff9900",
    QPalette.ColorRole.LinkVisited: "#d35400",
}

_DARK_DISABLED = {
    QPalette.ColorRole.WindowText: "#7a7a7a",
    QPalette.ColorRole.Text: "#7a7a7a",
    QPalette.ColorRole.ButtonText: "#7a7a7a",
    QPalette.ColorRole.Base: "#2b2b2b",
    QPalette.ColorRole.Highlight: "#5a5a5a",
}

_DARK_STYLESHEET = f"""
QToolTip {{ color: #e6e6e6; background: #3c3c3c; border: 1px solid #5a5a5a; }}
QMenuBar {{ background: #2b2b2b; border-bottom: 1px solid #1e1e1e; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: #3c3c3c; color: {ACCENT}; }}
QMenu {{ background: #2f2f2f; border: 1px solid #4a4a4a; padding: 4px 0; }}
QMenu::item {{ padding: 4px 24px 4px 24px; }}
QMenu::item:selected {{ background: {ACCENT}; color: #1e1e1e; }}
QMenu::item:disabled {{ color: #7a7a7a; }}
QMenu::separator {{ height: 1px; background: #4a4a4a; margin: 4px 8px; }}
QToolBar {{ background: #333333; border: none; border-bottom: 1px solid #1e1e1e; spacing: 4px; padding: 2px; }}
QToolBar QToolButton {{ padding: 3px 8px; border: 1px solid transparent; border-radius: 3px; }}
QToolBar QToolButton:hover {{ background: #3f3f3f; border-color: #5a5a5a; }}
QToolBar QToolButton:pressed, QToolBar QToolButton:checked, QToolBar QToolButton:open {{
    background: #4a3a1f; border-color: {ACCENT};
}}
QStatusBar {{ background: #252525; border-top: 1px solid #444444; }}
QGroupBox {{ border: 1px solid #4a4a4a; border-radius: 3px; margin-top: 14px; padding-top: 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {ACCENT}; font-weight: bold; }}
QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit {{
    background: #232323; border: 1px solid #4a4a4a; border-radius: 2px;
    selection-background-color: {ACCENT}; selection-color: #1e1e1e;
}}
QLineEdit:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled {{ color: #7a7a7a; background: #2b2b2b; border-color: #3a3a3a; }}
QAbstractSpinBox {{ padding-right: 16px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 16px; background: #333333; border-left: 1px solid #4a4a4a;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-top: 1px solid #3a3a3a; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #4a3a1f; }}
QAbstractSpinBox::up-arrow {{ image: url("{{icons}}/arrow-up.svg"); width: 8px; height: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url("{{icons}}/arrow-down.svg"); width: 8px; height: 8px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid #8a8a8a; border-radius: 2px; background: #232323; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{{icons}}/check.svg"); }}
QCheckBox::indicator:disabled {{ border-color: #4a4a4a; background: #2b2b2b; }}
QPushButton {{ background: #3c3c3c; border: 1px solid #555555; border-radius: 3px; padding: 4px 10px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT}; color: #1e1e1e; }}
QPushButton:disabled {{ color: #7a7a7a; border-color: #3a3a3a; }}
QScrollArea {{ border: none; }}
QAbstractItemView {{ background: #232323; alternate-background-color: #2b2b2b; gridline-color: #3a3a3a; }}
QAbstractItemView::item:selected {{ background: {ACCENT}; color: #1e1e1e; }}
QHeaderView::section {{ background: #333333; color: #e6e6e6; border: none; border-right: 1px solid #1e1e1e;
    border-bottom: 1px solid #1e1e1e; padding: 4px; }}
QScrollBar:vertical {{ background: #262626; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: #262626; height: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #555555; min-height: 24px; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #555555; min-width: 24px; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:hover {{ background: #6e6e6e; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: #1e1e1e; }}
QProgressBar {{ border: 1px solid #4a4a4a; border-radius: 2px; text-align: center; background: #232323; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
"""

# Appended to the QtAds default sheet, so only colours are overridden.
_DARK_DOCK_STYLESHEET = f"""
ads--CDockContainerWidget {{ background: #1e1e1e; }}
ads--CDockContainerWidget ads--CDockSplitter::handle {{ background: #1e1e1e; }}
ads--CDockAreaWidget {{ background: #2b2b2b; border: 1px solid #3a3a3a; }}
ads--CDockAreaTitleBar {{ background: #2f2f2f; border-bottom: 2px solid {ACCENT}; }}
ads--CDockWidgetTab {{ background: #333333; border-color: #1e1e1e; border-width: 0 1px 0 0; padding: 0 4px; }}
ads--CDockWidgetTab:hover {{ background: #3c3c3c; }}
ads--CDockWidgetTab[activeTab="true"] {{ background: {ACCENT}; }}
ads--CDockWidgetTab QLabel {{ color: #cfcfcf; }}
ads--CDockWidgetTab[activeTab="true"] QLabel {{ color: #1e1e1e; font-weight: bold; }}
ads--CDockWidget {{ background: #2b2b2b; border-color: #3a3a3a; }}
ads--CTitleBarButton:hover, #tabCloseButton:hover {{ background: rgba(255, 255, 255, 40); border: none; }}
#tabsMenuButton {{ qproperty-icon: url("{{icons}}/tabs-menu-button.svg"); }}
#dockAreaCloseButton {{
    qproperty-icon: url("{{icons}}/close-button.svg"), url("{{icons}}/close-button-disabled.svg") disabled;
}}
#detachGroupButton {{
    qproperty-icon: url("{{icons}}/detach-button.svg"), url("{{icons}}/detach-button-disabled.svg") disabled;
}}
"""


def load_theme(settings: QSettings | None = None) -> Theme:
    """Return the saved theme; anything unknown falls back to light."""
    value = (settings or QSettings()).value(THEME_SETTINGS_KEY, Theme.LIGHT.value, type=str)
    try:
        return Theme(value)
    except ValueError:
        return Theme.LIGHT


def save_theme(theme: Theme, settings: QSettings | None = None) -> None:
    (settings or QSettings()).setValue(THEME_SETTINGS_KEY, Theme(theme).value)


def dark_palette() -> QPalette:
    palette = QPalette()
    for role, color in _DARK_PALETTE.items():
        palette.setColor(role, QColor(color))
    for role, color in _DARK_DISABLED.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return palette


def apply_application_theme(app: QApplication, theme: Theme, dark_icons: Path) -> None:
    """Switch style, palette and style sheet of the whole application.

    The dark theme needs Fusion, which draws every control from the palette;
    the light theme returns to the native style and system palette, so it looks
    exactly as before themes existed.  ``dark_icons`` holds the light arrow and
    check-mark images that the dark style sheet draws on dark controls.
    """
    # With a style sheet set, ``app.style()`` is an anonymous wrapper; drop it
    # first so the real style name can be read and compared.
    app.setStyleSheet("")
    native_style = app.property(_NATIVE_STYLE_PROPERTY)
    if not native_style:
        native_style = app.style().name()
        app.setProperty(_NATIVE_STYLE_PROPERTY, native_style)
    style = "fusion" if theme is Theme.DARK else native_style
    # Re-creating the current style would needlessly re-polish every widget.
    if app.style().name().lower() != style.lower():
        app.setStyle(style)
    if theme is Theme.DARK:
        app.setPalette(dark_palette())
        app.setStyleSheet(_DARK_STYLESHEET.replace("{icons}", dark_icons.as_posix()))
    else:
        # An empty palette drops the override and follows the platform again.
        app.setPalette(QPalette())


def dock_stylesheet(theme: Theme, default_stylesheet: str, dark_icons: Path) -> str:
    """Return the QtAds manager style sheet for ``theme``.

    The stock QtAds title-bar icons are dark grey; ``dark_icons`` holds light
    copies that stay visible on the dark title bar.
    """
    if theme is Theme.DARK:
        return default_stylesheet + _DARK_DOCK_STYLESHEET.replace("{icons}", dark_icons.as_posix())
    return default_stylesheet
