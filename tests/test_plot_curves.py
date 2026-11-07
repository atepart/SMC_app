"""Curve names, styles and legend check boxes of the S21 plot (WP-039, GitHub #11)."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pyqtgraph as pg
import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow
from aocapp.ui.plot_legend import CheckableItemSample, PlainItemSample
from aocapp.ui.theme import THEME_COLORS, Theme, apply_application_theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FREQUENCIES = [100.0, 300.0, 500.0, 700.0, 900.0]


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


def _with_all_plotted_curves(window: MainWindow, tmp_path) -> None:
    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    window._update_s21_plot(FREQUENCIES, [-9.0, -3.0, -1.5, -4.0, -11.0])
    experiment = tmp_path / "experiment.txt"
    experiment.write_text("100 -11\n500 -2.5\n900 -13\n", encoding="utf-8")
    window.load_comparison_trace("Experiment", experiment)


def _curves(window: MainWindow) -> dict:
    return {item.name(): item for item in window._plot.listDataItems()}


def _legend(window: MainWindow) -> list[tuple[str, object]]:
    return [(label.text, sample) for sample, label in window._plot_legend.items]


def _click_sample(window: MainWindow, sample) -> None:
    """A real left click on the legend sample's check box through the plot viewport."""
    scene_point = sample.mapToScene(QtCore.QPointF(6, 10))
    view_point = window._plot.mapFromScene(scene_point)
    QTest.mouseClick(window._plot.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=view_point)
    QtWidgets.QApplication.processEvents()


def test_legend_names_follow_github_11_in_order(window: MainWindow, tmp_path) -> None:
    _with_all_plotted_curves(window, tmp_path)

    assert [name for name, _ in _legend(window)] == ["SMC", "prev", "exp"]
    assert all(isinstance(sample, CheckableItemSample) for _, sample in _legend(window))
    curves = _curves(window)
    assert curves["SMC"].zValue() > max(curves[name].zValue() for name in ("prev", "exp"))
    # The menu still says "Experiment"; only the curve is called "exp".
    assert set(window._comparison_traces) == {"Experiment"}


@pytest.mark.parametrize("theme", list(Theme))
def test_curve_colours_and_widths_per_theme(window: MainWindow, tmp_path, theme: Theme) -> None:
    _with_all_plotted_curves(window, tmp_path)
    window.set_theme(theme)
    colors = THEME_COLORS[theme]
    curves = _curves(window)

    smc = curves["SMC"]
    assert smc.opts["pen"].color().name() == colors.smc_curve
    assert smc.opts["pen"].widthF() == 2
    # Smaller points than the former 4 px, but still drawn in the curve colour.
    assert 0 < smc.opts["symbolSize"] < 4
    assert smc.opts["symbol"] == "o"
    assert pg.mkBrush(smc.opts["symbolBrush"]).color().name() == colors.smc_curve

    prev = curves["prev"].opts["pen"]
    assert prev.color().name() == colors.prev_curve
    assert prev.widthF() == 2 and prev.style() == QtCore.Qt.PenStyle.SolidLine
    red = QtGui.QColor(colors.prev_curve)
    assert red.red() > 200 and red.green() < 120 and red.blue() < 120

    exp = curves["exp"].opts["pen"]
    assert exp.color().name() == colors.exp_curve
    assert exp.widthF() == 3  # 1.5 × the base 2 px
    assert exp.style() == QtCore.Qt.PenStyle.CustomDashLine
    assert exp.capStyle() == QtCore.Qt.PenCapStyle.RoundCap
    dot, gap = exp.dashPattern()
    assert dot < 0.1 and gap == pytest.approx(2.0)  # round dots of the pen width
    green = QtGui.QColor(colors.exp_curve)
    assert green.green() > green.red() and green.green() > green.blue()

    # buff and HFSS arrive with WP-041/WP-040; their style is ready now.
    buff = window._curve_style("buff")["pen"]
    assert buff.widthF() == 4  # twice the base width
    grey = QtGui.QColor(colors.buff_curve)
    assert grey.red() == grey.green() == grey.blue()
    hfss = window._curve_style("HFSS")["pen"]
    assert hfss.widthF() == 2 and hfss.style() == QtCore.Qt.PenStyle.DashLine
    assert hfss.color().name() == colors.hfss_curve
    if theme == Theme.DARK:
        # Black would vanish on the dark plot: a light dashed curve instead.
        assert QtGui.QColor(colors.hfss_curve).lightness() > 200
    else:
        assert colors.hfss_curve == "#000000"

    with pytest.raises(ValueError, match="Неизвестная кривая"):
        window._curve_style("Theory")


@pytest.mark.parametrize(
    "theme,expected", [(Theme.DEFAULT, "#c8c8c8"), (Theme.LIGHT, "#c8c8c8"), (Theme.DARK, "#ffffff")]
)
def test_db_level_line_is_light_grey_or_white(window: MainWindow, theme: Theme, expected: str) -> None:
    window.set_theme(theme)
    color = window._plot_threshold_line.pen.color()
    assert THEME_COLORS[theme].threshold_line == expected
    assert color.name() == expected
    assert color.red() == color.green() == color.blue()  # no longer red


def test_check_box_hides_curve_and_survives_recalculation_import_and_theme(window: MainWindow, tmp_path) -> None:
    _with_all_plotted_curves(window, tmp_path)
    legend = dict(_legend(window))
    assert legend["SMC"].checked and legend["prev"].checked

    _click_sample(window, legend["SMC"])

    assert not _curves(window)["SMC"].isVisible()
    assert _curves(window)["prev"].isVisible()
    assert not window.is_curve_visible("SMC")
    assert not dict(_legend(window))["SMC"].checked
    assert window._theory_trace is not None  # the data is kept

    window._update_s21_plot(FREQUENCIES, [-8.0, -2.0, -1.0, -3.0, -10.0])
    assert not _curves(window)["SMC"].isVisible()
    assert _curves(window)["SMC"].yData.tolist() == [-8.0, -2.0, -1.0, -3.0, -10.0]
    assert [name for name, _ in _legend(window)] == ["SMC", "prev", "exp"]

    window.load_comparison_trace("Experiment", tmp_path / "experiment.txt")
    assert not _curves(window)["SMC"].isVisible()

    window.set_theme(Theme.DARK)
    smc = _curves(window)["SMC"]
    assert not smc.isVisible()
    assert smc.opts["pen"].color().name() == THEME_COLORS[Theme.DARK].smc_curve

    _click_sample(window, dict(_legend(window))["SMC"])
    assert _curves(window)["SMC"].isVisible()
    assert window.is_curve_visible("SMC")
    window._update_s21_plot(FREQUENCIES, [-7.0, -2.0, -1.0, -3.0, -9.0])
    assert _curves(window)["SMC"].isVisible()


def test_unchecked_curve_stays_hidden_when_its_data_returns(window: MainWindow, tmp_path) -> None:
    window.set_curve_visible("exp", False)
    _with_all_plotted_curves(window, tmp_path)
    assert not _curves(window)["exp"].isVisible()
    assert not dict(_legend(window))["exp"].checked


def test_png_export_lists_only_visible_curves_and_restores_legend(window: MainWindow, tmp_path, monkeypatch) -> None:
    _with_all_plotted_curves(window, tmp_path)
    window.set_curve_visible("prev", False)
    scene = window._plot.scene()
    seen: dict[str, object] = {}
    real_render = scene.render

    def render(*args, **kwargs):
        seen["legend"] = [(label.text, type(sample)) for sample, label in window._plot_legend.items]
        seen["visible"] = {name for name, item in _curves(window).items() if item.isVisible()}
        return real_render(*args, **kwargs)

    monkeypatch.setattr(scene, "render", render)
    destination = window.export_plot_to_path(tmp_path / "plot.png")

    assert destination.read_bytes().startswith(b"\x89PNG")
    assert seen["legend"] == [("SMC", PlainItemSample), ("exp", PlainItemSample)]
    assert seen["visible"] == {"SMC", "exp"}
    assert [(name, type(sample)) for name, sample in _legend(window)] == [
        ("SMC", CheckableItemSample),
        ("prev", CheckableItemSample),
        ("exp", CheckableItemSample),
    ]
    assert not _curves(window)["prev"].isVisible()
    assert not window.is_curve_visible("prev")
    # The restored check boxes still toggle their curves.
    _click_sample(window, dict(_legend(window))["prev"])
    assert _curves(window)["prev"].isVisible()


def test_no_cursor_coordinates_over_the_legend(window: MainWindow, tmp_path) -> None:
    _with_all_plotted_curves(window, tmp_path)
    QtWidgets.QApplication.processEvents()
    legend = window._plot_legend
    over_legend = legend.mapToScene(legend.boundingRect().center())
    window._on_plot_mouse_moved(over_legend)
    assert not window._plot_hover_label.isVisible()
    plot_area = window._plot.getPlotItem().vb.sceneBoundingRect().center()
    window._on_plot_mouse_moved(plot_area)
    assert window._plot_hover_label.isVisible()
