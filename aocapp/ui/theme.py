"""Colour themes for the desktop UI.

"По умолчанию" is the platform look the application always had.  "Светлая" and
"Тёмная" share one QmixElements-like design — Fusion widgets, flat panels and an
orange accent for the active dock tab, headings, selection and pressed toolbar
buttons — and differ only in their :class:`_Skin` colours.  Widgets are recoloured
through the application palette and style sheet, QtAds docks through their own
manager style sheet, pyqtgraph and the SVG sheet through :class:`ThemeColors`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from aocapp.domain.models import SvgColorScheme
from aocapp.infrastructure.svg_renderer import DARK_SVG_SCHEME

THEME_SETTINGS_KEY = "Appearance/theme"
_NATIVE_STYLE_PROPERTY = "aocappNativeStyle"


class Theme(StrEnum):
    DEFAULT = "default"
    LIGHT = "light"
    DARK = "dark"


THEME_TITLES = {Theme.DEFAULT: "По умолчанию", Theme.LIGHT: "Светлая", Theme.DARK: "Тёмная"}

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
    # ``None`` keeps the platform default (the default theme's look).
    heading_text: str | None
    schematic_backdrop: str | None
    schematic_scheme: SvgColorScheme | None = None


_LIGHT_PLOT = dict(
    plot_background="#ffffff",
    plot_foreground="#7f7f7f",
    previous_curve=(70, 70, 70, 153),
    theory_curve="#1f77b4",
    experiment_curve="#2ca02c",
    threshold_line="#dc2626",
    muted_text="#555555",
    error_text="#b91c1c",
)

THEME_COLORS = {
    Theme.DEFAULT: ThemeColors(**_LIGHT_PLOT, heading_text=None, schematic_backdrop=None),
    Theme.LIGHT: ThemeColors(**_LIGHT_PLOT, heading_text="#b85c00", schematic_backdrop="#e2e2e2"),
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
        schematic_backdrop="#161616",
        schematic_scheme=DARK_SVG_SCHEME,
    ),
}


@dataclass(frozen=True)
class _Skin:
    """Colours of a styled (Fusion) theme; the layout of the sheets is shared."""

    # QPalette
    window: str
    text: str
    base: str
    alternate_base: str
    button: str
    placeholder: str
    light: str
    midlight: str
    mid: str
    dark: str
    shadow: str
    on_accent: str
    link: str
    disabled_text: str
    disabled_base: str
    disabled_highlight: str
    # Style sheets
    border: str
    border_soft: str
    hover: str
    hover_border: str
    pressed: str
    bar: str
    bar_edge: str
    menu: str
    statusbar: str
    scrollbar: str
    handle: str
    handle_hover: str
    heading: str
    dock_container: str
    dock_titlebar: str
    dock_tab: str
    dock_tab_hover: str
    dock_tab_text: str
    title_button_hover: str
    # Asset folder with arrow/check images for this skin.
    icons: str
    # QtAds' stock title-bar icons are dark grey; dark skins need light copies.
    light_dock_icons: bool


_SKINS = {
    Theme.LIGHT: _Skin(
        window="#f3f3f3",
        text="#1f1f1f",
        base="#ffffff",
        alternate_base="#f7f7f7",
        button="#fafafa",
        placeholder="#8a8a8a",
        light="#ffffff",
        midlight="#ececec",
        mid="#d0d0d0",
        dark="#a8a8a8",
        shadow="#7a7a7a",
        on_accent="#1e1e1e",
        link="#b85c00",
        disabled_text="#a0a0a0",
        disabled_base="#f0f0f0",
        disabled_highlight="#d6d6d6",
        border="#c4c4c4",
        border_soft="#dedede",
        hover="#e9e9e9",
        hover_border="#b0b0b0",
        pressed="#fde3bd",
        bar="#ebebeb",
        bar_edge="#d0d0d0",
        menu="#ffffff",
        statusbar="#ececec",
        scrollbar="#ededed",
        handle="#c2c2c2",
        handle_hover="#a8a8a8",
        heading="#b85c00",
        dock_container="#d6d6d6",
        dock_titlebar="#e8e8e8",
        dock_tab="#e1e1e1",
        dock_tab_hover="#ececec",
        dock_tab_text="#4a4a4a",
        title_button_hover="rgba(0, 0, 0, 30)",
        icons="theme-light",
        light_dock_icons=False,
    ),
    Theme.DARK: _Skin(
        window="#2b2b2b",
        text="#e6e6e6",
        base="#232323",
        alternate_base="#303030",
        button="#3c3c3c",
        placeholder="#8a8a8a",
        light="#4a4a4a",
        midlight="#3f3f3f",
        mid="#333333",
        dark="#1e1e1e",
        shadow="#141414",
        on_accent="#1e1e1e",
        link="#ff9900",
        disabled_text="#7a7a7a",
        disabled_base="#2b2b2b",
        disabled_highlight="#5a5a5a",
        border="#4a4a4a",
        border_soft="#3a3a3a",
        hover="#3f3f3f",
        hover_border="#5a5a5a",
        pressed="#4a3a1f",
        bar="#333333",
        bar_edge="#1e1e1e",
        menu="#2f2f2f",
        statusbar="#252525",
        scrollbar="#262626",
        handle="#555555",
        handle_hover="#6e6e6e",
        heading=ACCENT,
        dock_container="#1e1e1e",
        dock_titlebar="#2f2f2f",
        dock_tab="#333333",
        dock_tab_hover="#3c3c3c",
        dock_tab_text="#cfcfcf",
        title_button_hover="rgba(255, 255, 255, 40)",
        icons="theme-dark",
        light_dock_icons=True,
    ),
}


def load_theme(settings: QSettings | None = None) -> Theme:
    """Return the saved theme; anything unknown falls back to the default."""
    value = (settings or QSettings()).value(THEME_SETTINGS_KEY, Theme.DEFAULT.value, type=str)
    try:
        return Theme(value)
    except ValueError:
        return Theme.DEFAULT


def save_theme(theme: Theme, settings: QSettings | None = None) -> None:
    (settings or QSettings()).setValue(THEME_SETTINGS_KEY, Theme(theme).value)


def styled_palette(theme: Theme) -> QPalette:
    """Return the Fusion palette of a styled theme."""
    s = _SKINS[theme]
    role = QPalette.ColorRole
    palette = QPalette()
    for color_role, color in (
        (role.Window, s.window),
        (role.WindowText, s.text),
        (role.Base, s.base),
        (role.AlternateBase, s.alternate_base),
        (role.ToolTipBase, s.menu),
        (role.ToolTipText, s.text),
        (role.PlaceholderText, s.placeholder),
        (role.Text, s.text),
        (role.Button, s.button),
        (role.ButtonText, s.text),
        (role.BrightText, s.link),
        (role.Light, s.light),
        (role.Midlight, s.midlight),
        (role.Mid, s.mid),
        (role.Dark, s.dark),
        (role.Shadow, s.shadow),
        (role.Highlight, ACCENT),
        (role.HighlightedText, s.on_accent),
        (role.Link, s.link),
        (role.LinkVisited, s.link),
    ):
        palette.setColor(color_role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for color_role, color in (
        (role.WindowText, s.disabled_text),
        (role.Text, s.disabled_text),
        (role.ButtonText, s.disabled_text),
        (role.Base, s.disabled_base),
        (role.Highlight, s.disabled_highlight),
    ):
        palette.setColor(disabled, color_role, QColor(color))
    return palette


def _application_stylesheet(s: _Skin, icons: str) -> str:
    return f"""
QToolTip {{ color: {s.text}; background: {s.menu}; border: 1px solid {s.border}; }}
QMenuBar {{ background: {s.window}; border-bottom: 1px solid {s.bar_edge}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {s.hover}; color: {s.heading}; }}
QMenu {{ background: {s.menu}; border: 1px solid {s.border}; padding: 4px 0; }}
QMenu::item {{ padding: 4px 24px 4px 24px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {s.on_accent}; }}
QMenu::item:disabled {{ color: {s.disabled_text}; }}
QMenu::separator {{ height: 1px; background: {s.border}; margin: 4px 8px; }}
QToolBar {{ background: {s.bar}; border: none; border-bottom: 1px solid {s.bar_edge}; spacing: 4px; padding: 2px; }}
QToolBar QToolButton {{ padding: 3px 8px; border: 1px solid transparent; border-radius: 3px; }}
QToolBar QToolButton:hover {{ background: {s.hover}; border-color: {s.hover_border}; }}
QToolBar QToolButton:pressed, QToolBar QToolButton:checked, QToolBar QToolButton:open {{
    background: {s.pressed}; border-color: {ACCENT};
}}
QStatusBar {{ background: {s.statusbar}; border-top: 1px solid {s.border}; }}
QGroupBox {{ border: 1px solid {s.border}; border-radius: 3px; margin-top: 14px; padding-top: 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {s.heading}; font-weight: bold; }}
QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit {{
    background: {s.base}; border: 1px solid {s.border}; border-radius: 2px;
    selection-background-color: {ACCENT}; selection-color: {s.on_accent};
}}
QLineEdit:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled {{
    color: {s.disabled_text}; background: {s.disabled_base}; border-color: {s.border_soft};
}}
QAbstractSpinBox {{ padding-right: 16px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 16px; background: {s.bar}; border-left: 1px solid {s.border};
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-top: 1px solid {s.border_soft}; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {s.pressed}; }}
QAbstractSpinBox::up-arrow {{ image: url("{icons}/arrow-up.svg"); width: 8px; height: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url("{icons}/arrow-down.svg"); width: 8px; height: 8px; }}
QCheckBox::indicator {{
    width: 13px; height: 13px; border: 1px solid {s.dark}; border-radius: 2px; background: {s.base};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{icons}/check.svg"); }}
QCheckBox::indicator:disabled {{ border-color: {s.border}; background: {s.disabled_base}; }}
QPushButton {{ background: {s.button}; border: 1px solid {s.border}; border-radius: 3px; padding: 4px 10px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT}; color: {s.on_accent}; }}
QPushButton:disabled {{ color: {s.disabled_text}; border-color: {s.border_soft}; }}
QScrollArea {{ border: none; }}
QAbstractItemView {{ background: {s.base}; alternate-background-color: {s.alternate_base}; gridline-color: {s.border_soft}; }}
QAbstractItemView::item:selected {{ background: {ACCENT}; color: {s.on_accent}; }}
QHeaderView::section {{ background: {s.bar}; color: {s.text}; border: none; border-right: 1px solid {s.bar_edge};
    border-bottom: 1px solid {s.bar_edge}; padding: 4px; }}
QScrollBar:vertical {{ background: {s.scrollbar}; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: {s.scrollbar}; height: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {s.handle}; min-height: 24px; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {s.handle}; min-width: 24px; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {s.handle_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {s.dock_container}; }}
QProgressBar {{ border: 1px solid {s.border}; border-radius: 2px; text-align: center; background: {s.base}; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
"""


def _dock_stylesheet(s: _Skin, icons: str) -> str:
    # Appended to the QtAds default sheet, so only colours are overridden.
    sheet = f"""
ads--CDockContainerWidget {{ background: {s.dock_container}; }}
ads--CDockContainerWidget ads--CDockSplitter::handle {{ background: {s.dock_container}; }}
ads--CDockAreaWidget {{ background: {s.window}; border: 1px solid {s.border_soft}; }}
ads--CDockAreaTitleBar {{ background: {s.dock_titlebar}; border-bottom: 2px solid {ACCENT}; }}
ads--CDockWidgetTab {{ background: {s.dock_tab}; border-color: {s.dock_container}; border-width: 0 1px 0 0; padding: 0 4px; }}
ads--CDockWidgetTab:hover {{ background: {s.dock_tab_hover}; }}
ads--CDockWidgetTab[activeTab="true"] {{ background: {ACCENT}; }}
ads--CDockWidgetTab QLabel {{ color: {s.dock_tab_text}; }}
ads--CDockWidgetTab[activeTab="true"] QLabel {{ color: {s.on_accent}; font-weight: bold; }}
ads--CDockWidget {{ background: {s.window}; border-color: {s.border_soft}; }}
ads--CTitleBarButton:hover, #tabCloseButton:hover {{ background: {s.title_button_hover}; border: none; }}
"""
    if s.light_dock_icons:
        sheet += f"""
#tabsMenuButton {{ qproperty-icon: url("{icons}/tabs-menu-button.svg"); }}
#dockAreaCloseButton {{
    qproperty-icon: url("{icons}/close-button.svg"), url("{icons}/close-button-disabled.svg") disabled;
}}
#detachGroupButton {{
    qproperty-icon: url("{icons}/detach-button.svg"), url("{icons}/detach-button-disabled.svg") disabled;
}}
"""
    return sheet


def apply_application_theme(app: QApplication, theme: Theme, assets: Path) -> None:
    """Switch style, palette and style sheet of the whole application.

    The styled themes need Fusion, which draws every control from the palette;
    the default theme returns to the native style and system palette, so it
    looks exactly as before themes existed.  ``assets`` is the folder holding
    each skin's arrow and check-mark images.
    """
    # With a style sheet set, ``app.style()`` is an anonymous wrapper; drop it
    # first so the real style name can be read and compared.
    app.setStyleSheet("")
    native_style = app.property(_NATIVE_STYLE_PROPERTY)
    if not native_style:
        native_style = app.style().name()
        app.setProperty(_NATIVE_STYLE_PROPERTY, native_style)
    skin = _SKINS.get(theme)
    style = "fusion" if skin else native_style
    # Re-creating the current style would needlessly re-polish every widget.
    if app.style().name().lower() != style.lower():
        app.setStyle(style)
    if skin:
        app.setPalette(styled_palette(theme))
        app.setStyleSheet(_application_stylesheet(skin, (assets / skin.icons).as_posix()))
    else:
        # An empty palette drops the override and follows the platform again.
        app.setPalette(QPalette())


def dock_stylesheet(theme: Theme, default_stylesheet: str, assets: Path) -> str:
    """Return the QtAds manager style sheet for ``theme``."""
    skin = _SKINS.get(theme)
    if skin is None:
        return default_stylesheet
    return default_stylesheet + _dock_stylesheet(skin, (assets / skin.icons).as_posix())
