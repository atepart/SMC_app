"""Larger fonts, the Run S21 button and rounded cursor coordinates (WP-043, GitHub #11)."""

from __future__ import annotations

import gc
import re
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from smcapp.application.s21_use_case import CalculateS21UseCase
from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow, format_plot_coordinates, scaled_font
from smcapp.ui.theme import THEME_COLORS, Theme, apply_application_theme, run_button_stylesheet

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FREQUENCIES = [100.0, 300.0, 500.0, 700.0, 900.0]
# Before WP-043: platform font everywhere, pyqtgraph's 9 pt legend.
OLD_LEGEND_POINTS = 9.0


@pytest.fixture
def window():
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance()
    window = MainWindow(
        GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()),
        cast(CalculateS21UseCase, Mock()),
    )
    window.resize(1440, 920)
    window.show()
    app.processEvents()
    yield window
    window.save_settings = Mock()
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
    apply_application_theme(app, Theme.DEFAULT, ASSETS)
    QtCore.QSettings().clear()
    app.processEvents()


def _base_points() -> float:
    return QtWidgets.QApplication.font().pointSizeF()


def _points(css_size: str) -> float:
    match = re.fullmatch(r"([\d.]+)pt", css_size)
    assert match, css_size
    return float(match.group(1))


@pytest.mark.parametrize(
    ("frequency", "s21", "expected"),
    [
        (393.001, -9.748, "f = 393 GHz; S21 = -9.75 dB"),  # the picture in GitHub #11
        (393.6, -9.744, "f = 394 GHz; S21 = -9.74 dB"),
        (1234.4, -20.0, "f = 1234 GHz; S21 = -20.00 dB"),
        (0.4, -0.004, "f = 0 GHz; S21 = 0.00 dB"),  # no "-0.00"
        (-0.4, 0.001, "f = 0 GHz; S21 = 0.00 dB"),  # no "-0"
    ],
)
def test_coordinates_round_frequency_to_1_ghz_and_s21_to_001_db(frequency, s21, expected) -> None:
    assert format_plot_coordinates(frequency, s21) == expected


def test_cursor_plate_uses_rounded_format_and_larger_font(window: MainWindow) -> None:
    view_box = window._plot.getPlotItem().vb
    window._on_plot_mouse_moved(view_box.mapToScene(view_box.boundingRect().center()))
    label = window._plot_hover_label
    assert label.isVisible()
    assert re.fullmatch(r"f = \d+ GHz; S21 = -?\d+\.\d\d dB", label.text()), label.text()
    assert label.font().pointSizeF() > _base_points()
    # The plate grows with its text instead of cutting it off.
    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())


def test_parameter_group_titles_and_fields_are_larger(window: MainWindow) -> None:
    base = _base_points()
    assert window._parameter_groups
    for group in window._parameter_groups.values():
        title = group.toggle_button.font()
        assert title.bold()
        assert title.pointSizeF() > base * 1.2
        fields = group.content.findChildren(QtWidgets.QWidget)
        labels = [w for w in fields if isinstance(w, QtWidgets.QLabel)]
        spins = [w for w in fields if isinstance(w, QtWidgets.QAbstractSpinBox)]
        assert labels and spins
        for widget in labels + spins + [spin.lineEdit() for spin in spins]:
            assert widget.font().pointSizeF() > base, (group.toggle_button.text(), widget)
            # Titles stay larger than the fields under them.
            assert widget.font().pointSizeF() < title.pointSizeF()
    # The numbers really are drawn larger: a value is wider than with the platform font.
    spin = window._config_inputs["mex4_width_m"]
    plain = QtGui.QFontMetrics(QtWidgets.QApplication.font()).horizontalAdvance(spin.text())
    assert spin.lineEdit().fontMetrics().horizontalAdvance(spin.text()) > plain


def test_run_s21_button_is_prominent_but_compact(window: MainWindow) -> None:
    button = window._run_s21_button
    preview = next(b for b in window.actions_box.findChildren(QtWidgets.QPushButton) if b.text() == "Update Preview")
    assert button.font().bold()
    assert button.font().pointSizeF() >= 1.1 * _base_points()
    assert button.fontMetrics().height() > preview.fontMetrics().height()
    # The text fits, yet the button is about half its WP-043 size (owner's request).
    assert button.height() >= button.fontMetrics().height() + 4
    wp043_font = QtGui.QFontMetrics(scaled_font(1.6, bold=True))
    wp043_height = round(wp043_font.height() * 2.2)
    assert button.height() <= 0.6 * wp043_height
    assert button.fontMetrics().height() <= 0.8 * wp043_font.height()


def _button_colour(button: QtWidgets.QPushButton) -> QtGui.QColor:
    """Fill colour of the button, sampled left of its centred text."""
    image = button.grab().toImage()
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(10 * ratio), round(button.height() / 2 * ratio))


def _close(actual: QtGui.QColor, expected: str) -> bool:
    wanted = QtGui.QColor(expected)
    return all(abs(a - b) <= 3 for a, b in zip(actual.getRgb()[:3], wanted.getRgb()[:3], strict=True))


@pytest.mark.parametrize("theme", list(Theme))
def test_run_s21_button_colours_follow_the_theme(window: MainWindow, theme: Theme) -> None:
    window.set_theme(theme)
    QtWidgets.QApplication.processEvents()
    button = window._run_s21_button
    colours = THEME_COLORS[theme].run_button
    assert button.styleSheet() == run_button_stylesheet(theme)

    normal = _button_colour(button)
    assert _close(normal, colours.background), (normal.name(), colours.background)
    if theme == Theme.DARK:
        assert normal.name() == "#ffffff"
        assert QtGui.QColor(colours.text).lightness() < 64  # dark text on white
    else:
        # Reddish: red clearly dominates, but the text colour is darker still.
        assert normal.red() > normal.green() + 25 and normal.red() > normal.blue() + 25
        assert QtGui.QColor(colours.text).lightness() < normal.lightness()

    button.setDown(True)
    pressed = _button_colour(button)
    button.setDown(False)
    assert _close(pressed, colours.pressed), (pressed.name(), colours.pressed)
    assert pressed != normal

    # Disabled while S21 is being calculated.
    button.setEnabled(False)
    disabled = _button_colour(button)
    button.setEnabled(True)
    assert _close(disabled, colours.disabled_background), (disabled.name(), colours.disabled_background)
    assert disabled != normal


def test_default_and_light_run_buttons_share_the_reddish_look() -> None:
    assert THEME_COLORS[Theme.DEFAULT].run_button == THEME_COLORS[Theme.LIGHT].run_button
    assert THEME_COLORS[Theme.DARK].run_button != THEME_COLORS[Theme.LIGHT].run_button


def test_plot_title_axes_ticks_and_legend_are_larger(window: MainWindow) -> None:
    base = _base_points()
    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    QtWidgets.QApplication.processEvents()
    plot_item = window._plot.getPlotItem()

    title = plot_item.titleLabel
    assert _points(title.opts["size"]) > base * 1.3
    assert title.opts["bold"]
    # pyqtgraph's fixed 30 px title row would clip the larger title.
    assert plot_item.layout.rowMinimumHeight(0) >= title.item.boundingRect().height()

    for axis_name in ("left", "bottom"):
        axis = plot_item.getAxis(axis_name)
        assert _points(axis.labelStyle["font-size"]) > base * 1.2
        assert axis.style["tickFont"].pointSizeF() > base

    legend = window._plot_legend
    assert _points(legend.opts["labelTextSize"]) > max(base, OLD_LEGEND_POINTS)
    for _sample, label in legend.items:
        assert label.opts["size"] == legend.opts["labelTextSize"]


def test_theme_change_keeps_larger_plot_fonts_and_bottom_unit_switch_keeps_style(window: MainWindow) -> None:
    window.set_theme(Theme.DARK)
    plot_item = window._plot.getPlotItem()
    assert _points(plot_item.titleLabel.opts["size"]) > _base_points() * 1.3
    assert plot_item.layout.rowMinimumHeight(0) >= max(30, plot_item.titleLabel.item.boundingRect().height())
    window._plot.setXRange(100.0, 2000.0, padding=0)
    QtWidgets.QApplication.processEvents()
    bottom = plot_item.getAxis("bottom")
    assert "THz" in bottom.labelString()
    assert _points(bottom.labelStyle["font-size"]) > _base_points() * 1.2


@pytest.mark.parametrize("theme", list(Theme))
def test_narrowest_parameter_panel_cuts_nothing_off(window: MainWindow, theme: Theme) -> None:
    window.set_theme(theme)
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    splitter = window.dock_manager.dockContainers()[0].rootSplitter()
    splitter.setSizes([0, sum(splitter.sizes())])
    app.processEvents()

    panel = window.parameters_dock.widget()
    assert panel.width() >= panel.minimumSizeHint().width()
    inner = window.parameters_scroll.widget()
    assert inner.width() >= inner.minimumSizeHint().width()
    assert not window.parameters_scroll.horizontalScrollBar().isVisible()
    for button in window.actions_box.findChildren(QtWidgets.QPushButton):
        assert button.width() >= button.sizeHint().width(), button.text()
    for group in window._parameter_groups.values():
        assert group.toggle_button.width() >= group.toggle_button.sizeHint().width()
        for label in group.content.findChildren(QtWidgets.QLabel):
            if label.isVisible() and not label.wordWrap():
                assert label.width() >= label.minimumSizeHint().width(), label.text()


def _three_curves(window: MainWindow, tmp_path) -> None:
    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    window._update_s21_plot(FREQUENCIES, [-9.0, -3.0, -1.5, -4.0, -11.0])
    experiment = tmp_path / "experiment.txt"
    experiment.write_text("100 -11\n500 -2.5\n900 -13\n", encoding="utf-8")
    window.load_comparison_trace("Experiment", experiment, "GHz")
    QtWidgets.QApplication.processEvents()


def _legend_rows(window: MainWindow) -> list[str | None]:
    layout = window._plot_legend.layout
    return [
        layout.itemAt(row, 1).text if layout.itemAt(row, 1) is not None else None for row in range(layout.rowCount())
    ]


def test_png_export_scales_the_legend_and_keeps_its_rows_from_the_top(
    window: MainWindow, tmp_path, monkeypatch
) -> None:
    _three_curves(window, tmp_path)
    window.set_curve_visible("prev", False)
    legend = window._plot_legend
    flag = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    assert legend.flags() & flag
    scene = window._plot.scene()
    seen = {}
    real_render = scene.render

    def render(*args, **kwargs):
        seen["ignores"] = bool(legend.flags() & flag)
        seen["rows"] = _legend_rows(window)[:2]
        seen["inside"] = window._plot.getPlotItem().vb.sceneBoundingRect().contains(legend.sceneBoundingRect())
        return real_render(*args, **kwargs)

    monkeypatch.setattr(scene, "render", render)
    window.export_plot_to_path(tmp_path / "plot.png")
    window.export_plot_to_path(tmp_path / "again.png")  # repeated exports do not drift down
    assert seen == {"ignores": False, "rows": ["SMC", "exp"], "inside": True}
    assert legend.flags() & flag
    assert _legend_rows(window)[:3] == ["SMC", "prev", "exp"]


HFSS_EXAMPLE = Path(__file__).resolve().parent / "data" / "hfss_s21_example.tab"


def _legend_cells(window: MainWindow) -> dict[str, tuple[int, int]]:
    layout = window._plot_legend.layout
    cells = {}
    for row in range(layout.rowCount()):
        for column in range(layout.columnCount()):
            item = layout.itemAt(row, column)
            if item is not None and hasattr(item, "text") and isinstance(item.text, str):
                cells[item.text] = (row, column)
    return cells


def test_legend_rows_start_at_the_top_and_many_curves_use_two_columns(window: MainWindow, tmp_path) -> None:
    _three_curves(window, tmp_path)
    window._update_s21_plot(FREQUENCIES, [-8.0, -3.0, -1.0, -4.0, -10.0])  # redraw: rows must not drift
    assert _legend_cells(window) == {"SMC": (0, 1), "prev": (1, 1), "exp": (2, 1)}
    window.load_comparison_trace("HFSS", HFSS_EXAMPLE)
    QtWidgets.QApplication.processEvents()
    assert _legend_cells(window) == {"SMC": (0, 1), "prev": (0, 3), "HFSS": (1, 1), "exp": (1, 3)}
    # Fits the data area of the 1440×920 window, so no entry is cut off.
    view_box = window._plot.getPlotItem().vb
    assert view_box.sceneBoundingRect().contains(window._plot_legend.sceneBoundingRect())
    # Check boxes still work in the two-column layout.
    sample = next(sample for sample, label in window._plot_legend.items if label.text == "exp")
    scene_point = sample.mapToScene(QtCore.QPointF(6, 12))
    QtTest.QTest.mouseClick(
        window._plot.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=window._plot.mapFromScene(scene_point)
    )
    QtWidgets.QApplication.processEvents()
    assert not window.is_curve_visible("exp")


def test_plot_data_area_holds_three_legend_rows_at_1440x920(window: MainWindow, tmp_path) -> None:
    _three_curves(window, tmp_path)
    view_box = window._plot.getPlotItem().vb
    legend = window._plot_legend
    assert view_box.sceneBoundingRect().contains(legend.sceneBoundingRect())
