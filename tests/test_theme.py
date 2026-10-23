"""Light/dark theme switching and persistence (WP-024)."""

from __future__ import annotations

import gc
import re
import sys
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow
from aocapp.ui.theme import (
    THEME_COLORS,
    THEME_SETTINGS_KEY,
    Theme,
    apply_application_theme,
    dock_stylesheet,
    load_theme,
)

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _window_color() -> str:
    return QtWidgets.QApplication.palette().color(QtGui.QPalette.ColorRole.Window).name()


@pytest.fixture
def make_window():
    """Create windows after the test prepares QSettings; restore light afterwards."""
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance()
    windows: list[MainWindow] = []

    def factory() -> MainWindow:
        window = MainWindow(
            GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()),
            cast(CalculateS21UseCase, Mock()),
        )
        window.resize(1440, 920)
        window.show()
        app.processEvents()
        windows.append(window)
        return window

    yield factory
    for window in windows:
        window.save_settings = Mock()
        window.close()
        window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
    # The palette and style sheet are application-wide: leave other tests in light.
    apply_application_theme(app, Theme.LIGHT, ASSETS / "theme-dark")
    QtCore.QSettings().clear()
    app.processEvents()


def test_switching_theme_recolours_application_docks_and_plot_and_is_saved(make_window) -> None:
    window = make_window()
    app = QtWidgets.QApplication.instance()
    light_palette = _window_color()
    default_docks = window.dock_manager.styleSheet()
    assert window.theme is Theme.LIGHT
    assert app.styleSheet() == ""
    assert window._theme_actions[Theme.LIGHT].isChecked()

    window._theme_actions[Theme.DARK].trigger()
    app.processEvents()

    assert window.theme is Theme.DARK
    assert _window_color() == "#2b2b2b"
    assert "QMenu::item:selected" in app.styleSheet()
    assert window.dock_manager.styleSheet().startswith(default_docks)
    assert 'ads--CDockWidgetTab[activeTab="true"] { background: #f39c12; }' in window.dock_manager.styleSheet()
    assert window._plot.backgroundBrush().color().name() == THEME_COLORS[Theme.DARK].plot_background
    assert window._view.backgroundBrush().color().name() == THEME_COLORS[Theme.DARK].schematic_backdrop
    assert window._theme_actions[Theme.DARK].isChecked()
    assert QtCore.QSettings().value(THEME_SETTINGS_KEY) == "dark"

    window._theme_actions[Theme.LIGHT].trigger()
    app.processEvents()

    assert _window_color() == light_palette
    assert app.styleSheet() == ""
    assert window.dock_manager.styleSheet() == default_docks
    assert window._plot.backgroundBrush().color().name() == "#ffffff"
    assert window._view.backgroundBrush().style() == QtCore.Qt.BrushStyle.NoBrush
    assert QtCore.QSettings().value(THEME_SETTINGS_KEY) == "light"


def test_theme_switch_recolours_existing_curves_without_resetting_zoom(make_window) -> None:
    window = make_window()
    window._update_s21_plot([100.0, 500.0, 900.0], [-10.0, -3.0, -12.0])
    window._update_s21_plot([100.0, 500.0, 900.0], [-8.0, -2.0, -11.0])
    view_box = window._plot.getPlotItem().vb
    view_box.setRange(xRange=(300.0, 600.0), yRange=(-9.0, -1.0), padding=0)
    before = view_box.viewRange()

    window.set_theme(Theme.DARK)

    curves = {item.name(): item for item in window._plot.listDataItems()}
    dark = THEME_COLORS[Theme.DARK]
    assert curves["Theory"].opts["pen"].color().name() == dark.theory_curve
    assert curves["Previous theory"].opts["pen"].color().getRgb() == dark.previous_curve
    assert window._plot_threshold_line.pen.color().name() == dark.threshold_line
    assert window._plot.getPlotItem().getAxis("left").textPen().color().name() == dark.plot_foreground
    assert [value for pair in view_box.viewRange() for value in pair] == pytest.approx(
        [v for pair in before for v in pair]
    )
    status = next(iter(window._transformer_status.values()))
    assert dark.muted_text in status.styleSheet() or dark.error_text in status.styleSheet()


def test_saved_dark_theme_is_applied_to_a_new_window(make_window) -> None:
    QtCore.QSettings().setValue(THEME_SETTINGS_KEY, "dark")

    window = make_window()

    assert window.theme is Theme.DARK
    assert _window_color() == "#2b2b2b"
    assert window._theme_actions[Theme.DARK].isChecked()
    assert window._plot.backgroundBrush().color().name() == THEME_COLORS[Theme.DARK].plot_background


def test_unknown_saved_theme_falls_back_to_light() -> None:
    settings = QtCore.QSettings()
    settings.setValue(THEME_SETTINGS_KEY, "solarized")
    assert load_theme(settings) is Theme.LIGHT
    settings.remove(THEME_SETTINGS_KEY)
    assert load_theme(settings) is Theme.LIGHT


def test_dark_icons_referenced_by_style_sheets_exist() -> None:
    app = QtWidgets.QApplication.instance()
    icons = ASSETS / "theme-dark"
    assert dock_stylesheet(Theme.LIGHT, "base", icons) == "base"
    try:
        apply_application_theme(app, Theme.DARK, icons)
        sheets = dock_stylesheet(Theme.DARK, "base", icons) + app.styleSheet()
    finally:
        apply_application_theme(app, Theme.LIGHT, icons)
    assert app.styleSheet() == ""
    referenced = set(re.findall(r'url\("([^"]+)"\)', sheets))
    assert len(referenced) == 8
    for path in referenced:
        assert Path(path).is_file(), path


def test_closed_window_legend_no_longer_reads_its_deleted_viewbox(make_window, monkeypatch) -> None:
    """Exit after a theme switch must not print 'ViewBox already deleted'."""
    window = make_window()
    window._update_s21_plot([100.0, 500.0, 900.0], [-10.0, -3.0, -12.0])
    legend = window._plot_legend
    errors: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda _type, error, _tb: errors.append(error))
    deleted_viewbox = Mock()
    deleted_viewbox.boundingRect.side_effect = RuntimeError("Internal C++ object (ViewBox) already deleted.")
    real_viewbox = legend._GraphicsWidgetAnchor__parent
    legend._GraphicsWidgetAnchor__parent = deleted_viewbox
    try:
        legend.geometryChanged.emit()
        assert len(errors) == 1  # the open window still follows its ViewBox

        window.close()
        legend.geometryChanged.emit()
    finally:
        legend._GraphicsWidgetAnchor__parent = real_viewbox
    assert len(errors) == 1
