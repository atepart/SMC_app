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

from smcapp.application.s21_use_case import CalculateS21UseCase
from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow
from smcapp.ui.plot_legend import CheckableItemSample, PlainItemSample
from smcapp.ui.theme import THEME_COLORS, Theme, apply_application_theme

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
    window.load_comparison_trace("Experiment", experiment, "GHz")


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

    # buff comes from «Буфер» (WP-041); HFSS is imported since WP-040.
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

    window.load_comparison_trace("Experiment", tmp_path / "experiment.txt", "GHz")
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


HFSS_EXAMPLE = Path(__file__).resolve().parent / "data" / "hfss_s21_example.tab"


def _import_through_menu(window: MainWindow, kind: str, path: Path, monkeypatch) -> None:
    """Trigger the real "Открыть файл" menu action; the file dialog and the unit dialog are answered.

    The unit dialog is accepted with what it preselected from the header, as OK would.
    """
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    action = next(action for action in window.open_files_menu.actions() if action.text() == kind)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(path), ""))
    monkeypatch.setattr(TraceImportDialog, "exec", lambda dialog: QtWidgets.QDialog.DialogCode.Accepted)
    action.trigger()
    QtWidgets.QApplication.processEvents()


@pytest.mark.parametrize("theme", list(Theme))
def test_hfss_import_adds_dashed_curve_on_s21_axis(window: MainWindow, tmp_path, monkeypatch, theme) -> None:
    window.set_theme(theme)
    _with_all_plotted_curves(window, tmp_path)
    home = window._plot_initial_range
    config = window._build_config()
    home_inputs = {name: spin.value() for name, spin in window._plot_scale_inputs.items()}

    _import_through_menu(window, "HFSS", HFSS_EXAMPLE, monkeypatch)

    assert [name for name, _ in _legend(window)] == ["SMC", "prev", "HFSS", "exp"]
    assert isinstance(dict(_legend(window))["HFSS"], CheckableItemSample)
    hfss = _curves(window)["HFSS"]
    # THz in the file, GHz on the shared S21 axis.
    assert hfss.xData[0] == pytest.approx(100.0) and hfss.xData[-1] == pytest.approx(900.0)
    assert hfss.yData[0] == pytest.approx(-1.821818542601)
    assert hfss.getViewBox() is window._plot.getPlotItem().vb
    pen = hfss.opts["pen"]
    assert pen.style() == QtCore.Qt.PenStyle.DashLine and pen.widthF() == 2
    assert pen.color().name() == THEME_COLORS[theme].hfss_curve
    assert hfss.opts["symbol"] is None
    assert window._s21_status.text().startswith("HFSS: загружено 81 точек")

    # Plot-only: neither the calculation parameters nor Home change.
    assert window._build_config() == config
    assert window._plot_initial_range == home
    assert {name: spin.value() for name, spin in window._plot_scale_inputs.items()} == home_inputs
    view = window._plot.getPlotItem().vb.viewRange()
    assert view[0] == pytest.approx([home[0], home[1]]) and view[1] == pytest.approx([home[2], home[3]])


def test_hfss_reimport_replaces_curve_and_keeps_check_box(window: MainWindow, tmp_path, monkeypatch) -> None:
    # Room for the four-row legend: the test window gives the plot only ~160 px.
    window._plot.setMinimumHeight(420)
    _with_all_plotted_curves(window, tmp_path)
    _import_through_menu(window, "HFSS", HFSS_EXAMPLE, monkeypatch)
    _click_sample(window, dict(_legend(window))["HFSS"])
    assert not _curves(window)["HFSS"].isVisible()

    second = tmp_path / "second.tab"
    second.write_text('"Freq [THz]"\t"dB(S(2,1)) []"\n0.2\t-6\n0.4\t-3\n0.6\t-7\n', encoding="utf-8")
    _import_through_menu(window, "HFSS", second, monkeypatch)

    names = [name for name, _ in _legend(window)]
    assert names.count("HFSS") == 1
    hfss = _curves(window)["HFSS"]
    assert hfss.xData.tolist() == pytest.approx([200.0, 400.0, 600.0])
    assert hfss.yData.tolist() == [-6.0, -3.0, -7.0]
    assert not hfss.isVisible()  # the unchecked box survives the new import
    assert window._comparison_traces["HFSS"].source == second
    assert window._s21_status.text().startswith("HFSS: загружено 3 точек")
    assert _curves(window)["exp"].isVisible()


def test_bad_hfss_file_shows_dialog_and_keeps_previous_curve(window: MainWindow, tmp_path, monkeypatch) -> None:
    _import_through_menu(window, "HFSS", HFSS_EXAMPLE, monkeypatch)
    broken = tmp_path / "broken.tab"
    broken.write_text('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n0.2\tabc\n', encoding="utf-8")
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda _parent, title, text: shown.append((title, text)))

    _import_through_menu(window, "HFSS", broken, monkeypatch)

    assert shown == [("Ошибка импорта HFSS", "Строка 3: значения должны быть числами: '0.2\\tabc'.")]
    assert window._comparison_traces["HFSS"].source == HFSS_EXAMPLE
    assert len(_curves(window)["HFSS"].xData) == 81


def test_zoom_and_pan_survive_recalculation_import_and_buffer(window: MainWindow, tmp_path) -> None:
    """WP-047, BUG-025: redrawing the plot must not throw the user's view back to Home."""
    view_box = window._plot.getPlotItem().vb
    home = window._plot_initial_range

    # Without zooming the first calculation stays on Home, not on the data range.
    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    assert view_box.viewRange() == [pytest.approx([home[0], home[1]]), pytest.approx([home[2], home[3]])]

    view_box.scaleBy((0.5, 0.5))
    view_box.translateBy(x=40.0, y=1.5)
    zoomed = view_box.viewRange()
    assert zoomed[0] != pytest.approx([home[0], home[1]])

    window._update_s21_plot(FREQUENCIES, [-9.0, -3.0, -1.5, -4.0, -11.0])
    experiment = tmp_path / "experiment.txt"
    experiment.write_text("100 -11\n500 -2.5\n900 -13\n", encoding="utf-8")
    window.load_comparison_trace("Experiment", experiment, "GHz")
    window.load_comparison_trace("HFSS", HFSS_EXAMPLE)
    window.store_buffer()
    assert view_box.viewRange() == [pytest.approx(zoomed[0]), pytest.approx(zoomed[1])]

    # Home still returns to the requested range.
    window._restore_plot_scale()
    assert view_box.viewRange() == [pytest.approx([home[0], home[1]]), pytest.approx([home[2], home[3]])]


def test_auto_range_follows_new_data(window: MainWindow) -> None:
    """With the "A" button pressed the view keeps following the curves."""
    view_box = window._plot.getPlotItem().vb
    view_box.enableAutoRange()
    window._update_s21_plot([1000.0, 1200.0, 1400.0], [-40.0, -35.0, -30.0])
    QtWidgets.QApplication.processEvents()
    x_range, y_range = view_box.viewRange()
    assert x_range[0] < 1000.0 < 1400.0 < x_range[1] and x_range[1] < 1600.0
    assert y_range[0] < -40.0 and y_range[1] < -20.0


# WP-055: decimal commas, column and Y-quantity choice, current on the right axis.

ORIGIN_TABLE = "Freq\tS21\tI\nGHz\tdB\tmA\n100,0\t-12,5\t0,01\n500,0\t-3,5\t0,1\n900,0\t-9,0\t1,0\n"


def _origin_file(tmp_path) -> Path:
    path = tmp_path / "origin.dat"
    path.write_text(ORIGIN_TABLE, encoding="utf-8")
    return path


def _import_choosing(window: MainWindow, kind: str, path: Path, monkeypatch, y_column: int, quantity: str) -> None:
    """The real menu action; the import dialog answers with the Y column and quantity given."""
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    def exec_(dialog):
        dialog.select_columns(0, y_column)
        dialog.select_quantity(quantity)
        return QtWidgets.QDialog.DialogCode.Accepted

    action = next(action for action in window.open_files_menu.actions() if action.text() == kind)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(path), ""))
    monkeypatch.setattr(TraceImportDialog, "exec", exec_)
    action.trigger()
    QtWidgets.QApplication.processEvents()


def test_import_dialog_reads_decimal_commas_and_offers_columns_and_quantities(window: MainWindow, tmp_path) -> None:
    from smcapp.infrastructure.trace_files import read_data_table
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    ok = QtWidgets.QDialogButtonBox.StandardButton.Ok
    dialog = TraceImportDialog("Experiment", read_data_table(_origin_file(tmp_path)), window)

    assert dialog.separator_combo.currentText() == "Авто (Табуляция)"
    assert dialog.decimal_combo.currentText() == "Авто (Запятая «,»)"
    assert dialog.preview.columnCount() == 3 and dialog.preview.rowCount() == 3
    assert dialog.preview.horizontalHeaderItem(2).text() == "3: I, mA"
    assert dialog.preview.item(0, 2).text() == "0.01"
    # X with "GHz" in its header, Y the dB column; both guessed from the header.
    assert dialog.selected_columns() == (0, 1) and dialog.selected_unit() == "GHz"
    assert dialog.selected_quantity() == "dB" and dialog.button_box.button(ok).isEnabled()
    assert "левая ось" in dialog.y_result_label.text()

    dialog.select_columns(0, 2)
    assert dialog.selected_quantity() == "mA"
    assert "правая ось, логарифмическая шкала" in dialog.y_result_label.text()
    dialog.select_quantity("mA log")
    assert "правая ось, линейная шкала" in dialog.y_result_label.text()
    trace = dialog.comparison_trace()
    assert trace.quantity == "mA log" and trace.coefficients == (0.01, 0.1, 1.0)

    # A wrong separator: the error is shown and OK is off until it is set back.
    dialog.select_format("space", ".")
    assert "не тот разделитель" in dialog.error_label.text()
    assert not dialog.button_box.button(ok).isEnabled()
    dialog.select_format(None, None)
    assert dialog.error_label.text() == "" and dialog.button_box.button(ok).isEnabled()

    dialog.select_columns(1, 1)
    assert "разными" in dialog.error_label.text() and not dialog.button_box.button(ok).isEnabled()


def test_log_scale_needs_positive_values(window: MainWindow, tmp_path) -> None:
    from smcapp.infrastructure.trace_files import read_data_table
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    path = tmp_path / "negative.txt"
    path.write_text("Freq [GHz] I [mA]\n100 -0.5\n200 -0.1\n", encoding="utf-8")
    dialog = TraceImportDialog("Experiment", read_data_table(path), window)
    assert dialog.selected_quantity() == "mA"
    assert "Все значения ≤ 0" in dialog.y_result_label.text()
    assert not dialog.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.select_quantity("mA log")
    assert dialog.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_current_goes_to_a_right_log_axis_with_its_own_home(window: MainWindow, tmp_path, monkeypatch) -> None:
    import math

    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    home = window._plot_initial_range
    plot_item = window._plot.getPlotItem()
    assert not plot_item.getAxis("right").isVisible()
    assert not window._plot_y2_inputs["y2_min"].isVisible()

    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "mA")

    right = plot_item.getAxis("right")
    assert right.isVisible() and right.logMode and right.labelText == "I, mA"
    [exp] = window._right_curve_items
    assert exp.getViewBox() is window._right_view and exp.name() == "exp"
    assert exp.yData.tolist() == pytest.approx([-2.0, -1.0, 0.0])  # log10 of the mA values
    assert [name for name, _ in _legend(window)] == ["SMC", "exp"]
    assert "exp" not in _curves(window)  # not on the S21 axis
    assert "I, mA: правая ось, логарифмическая шкала" in window._s21_status.text()
    # Y2 fields appear, filled from the data; the S21 view stays on Home.
    assert window._plot_y2_inputs["y2_min"].isVisible()
    assert window._plot_y2_labels["y2_min"].text() == "Y2 min, mA"
    low, high = window._right_view.viewRange()[1]
    assert low < -2.0 and high > 0.0
    assert window._plot_y2_inputs["y2_min"].value() == pytest.approx(10.0**low)
    assert plot_item.vb.viewRange()[1] == pytest.approx([home[2], home[3]])
    # The X range is shared.
    assert window._right_view.viewRange()[0] == pytest.approx(plot_item.vb.viewRange()[0])

    # Y2 min/max become part of Home.
    window._plot_y2_inputs["y2_min"].setValue(0.001)
    window._plot_y2_inputs["y2_max"].setValue(10.0)
    window._apply_plot_scale()
    assert window._right_view.viewRange()[1] == pytest.approx([-3.0, 1.0])
    window._right_view.scaleBy((1, 0.5))
    window._restore_plot_scale()
    assert window._right_view.viewRange()[1] == pytest.approx([-3.0, 1.0])

    # Zero is not on a log scale: refused, Home unchanged.
    warnings: list[str] = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    window._plot_y2_inputs["y2_min"].setValue(0.0)
    window._apply_plot_scale()
    assert warnings == ["На логарифмической шкале Y2 min должен быть больше нуля."]
    assert window._plot_initial_y2 == pytest.approx((0.001, 10.0))

    # Hover shows the current too.
    window._plot.resize(900, 600)
    QtWidgets.QApplication.processEvents()
    center = plot_item.vb.sceneBoundingRect().center()
    window._on_plot_mouse_moved(center)
    expected = 10.0 ** window._right_view.mapSceneToView(center).y()
    assert window._plot_hover_label.text().endswith(f"I = {expected:.3g} mA")
    assert math.isfinite(expected)


def test_log_values_use_a_linear_right_axis_and_db_goes_back_left(window: MainWindow, tmp_path, monkeypatch) -> None:
    path = tmp_path / "log.txt"
    path.write_text("Freq [GHz]; lg I [uA]\n100; -1,5\n500; 0,25\n", encoding="utf-8")
    _import_choosing(window, "HFSS", path, monkeypatch, 1, "µA log")

    right = window._plot.getPlotItem().getAxis("right")
    assert right.isVisible() and not right.logMode and right.labelText == "log₁₀(I / µA)"
    [hfss] = window._right_curve_items
    assert hfss.yData.tolist() == pytest.approx([-1.5, 0.25])
    assert window._plot_y2_labels["y2_max"].text() == "Y2 max, lg µA"
    assert window._plot_y2_inputs["y2_min"].value() < -1.5

    # The same file as dB: back on the S21 axis, the right axis and Y2 fields go away.
    _import_choosing(window, "HFSS", path, monkeypatch, 1, "dB")
    assert window._right_curve_items == [] and not right.isVisible()
    assert _curves(window)["HFSS"].yData.tolist() == [-1.5, 0.25]
    assert not window._plot_y2_inputs["y2_max"].isVisible()


@pytest.mark.parametrize("first, second", [(Theme.DARK, Theme.LIGHT), (Theme.LIGHT, Theme.DARK)])
def test_right_axis_label_follows_the_theme(window: MainWindow, tmp_path, monkeypatch, first, second) -> None:
    """BUG-028: the right axis label kept Qt's default black instead of the theme colour."""
    window.set_theme(first)
    _import_choosing(window, "HFSS", _origin_file(tmp_path), monkeypatch, 2, "A log")
    plot_item = window._plot.getPlotItem()
    right, left = plot_item.getAxis("right"), plot_item.getAxis("left")

    def colour(axis) -> str:
        return QtGui.QColor(axis.labelStyle["color"]).name()

    assert right.isVisible() and right.labelText == "log₁₀(I / A)"
    assert colour(right) == colour(left) == QtGui.QColor(THEME_COLORS[first].plot_foreground).name()
    assert right.labelStyle["color"] in right.label.toHtml()  # the drawn text, not only the style
    font_size = right.labelStyle["font-size"]

    window.set_theme(second)
    assert colour(right) == QtGui.QColor(THEME_COLORS[second].plot_foreground).name()
    # A new import of a current keeps the theme colour and the label size.
    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "A log")
    assert colour(right) == QtGui.QColor(THEME_COLORS[second].plot_foreground).name()
    assert right.labelStyle["font-size"] == font_size
