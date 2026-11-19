"""Curve names, styles and legend check boxes of the S21 plot (WP-039, GitHub #11)."""

from __future__ import annotations

import gc
import math
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
    # A value that is not a number only skips its point (WP-063); a row wider than the table is an error.
    broken.write_text('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-3\n0.2\t-4\t5\n', encoding="utf-8")
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda _parent, title, text: shown.append((title, text)))

    _import_through_menu(window, "HFSS", broken, monkeypatch)

    assert shown == [("Ошибка импорта HFSS", "Строка 3: ожидалось 2 столбца, найдено 3.")]
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
    assert "правая ось, квадрат I² в логарифмической шкале" in dialog.y_result_label.text()
    dialog.select_quantity("mA² log")
    assert "правая ось, линейная шкала: значения уже lg(I² / mA²), рисуются как есть" in dialog.y_result_label.text()
    trace = dialog.comparison_trace()
    assert trace.quantity == "mA² log" and trace.coefficients == (0.01, 0.1, 1.0)

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
    dialog.select_quantity("mA² log")
    assert dialog.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_wrapped_quantity_note_is_not_cut_off(window: MainWindow, tmp_path) -> None:
    """WP-067: a note that wraps onto more lines gets their height instead of being clipped."""
    from smcapp.infrastructure.trace_files import read_data_table
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    path = tmp_path / "ratio.txt"
    path.write_text("Freq [GHz]\tI/Ig\t(I/Ig)^2\n100\t0.5\t0.25\n200\t0.7\t0.49\n", encoding="utf-8")
    dialog = TraceImportDialog("Experiment", read_data_table(path), window)
    dialog.show()
    dialog.resize(480, dialog.height())
    QtWidgets.QApplication.processEvents()
    dialog.select_columns(0, 2)
    assert dialog.selected_quantity() == "(I/Ig)²"
    QtWidgets.QApplication.processEvents()
    label = dialog.y_result_label
    one_line = label.fontMetrics().height()
    assert label.heightForWidth(label.width()) > one_line * 1.5  # the note really wraps here
    assert label.height() >= label.heightForWidth(label.width())
    assert dialog.rect().contains(label.geometry().translated(label.parentWidget().mapTo(dialog, QtCore.QPoint())))
    # Back to a short note: the label shrinks again.
    dialog.select_quantity("dB")
    QtWidgets.QApplication.processEvents()
    assert label.minimumHeight() == label.heightForWidth(label.width())
    dialog.close()


DASHES_EXAMPLE = Path(__file__).resolve().parent / "data" / "exp_hd34_11_12_dashes.tab"


def test_import_dialog_reports_rows_skipped_for_dashes(window: MainWindow, tmp_path) -> None:
    """WP-063 / BUG-029: the owner's file with "--" opens; the skipped lines are named."""
    from smcapp.infrastructure.trace_files import read_data_table
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    ok = QtWidgets.QDialogButtonBox.StandardButton.Ok
    dialog = TraceImportDialog("Experiment", read_data_table(DASHES_EXAMPLE), window)
    assert dialog.error_label.text() == ""
    assert "Строк с числами: 210" in dialog.details_label.text()
    assert "(200 точек)" in dialog.y_result_label.text()
    assert "Пропущено строк без чисел в X/Y: 10 (строки 201–210)." in dialog.y_result_label.text()
    dialog.unit_buttons["GHz"].click()
    assert dialog.button_box.button(ok).isEnabled()
    trace = dialog.comparison_trace()
    assert len(trace.frequencies) == 200 and trace.frequencies[-1] == pytest.approx(796.56702)

    # Skipped cells are previewed as written; a Y column of dashes only leaves nothing to import.
    path = tmp_path / "dashes.txt"
    path.write_text("Freq [GHz]\tS21 [dB]\tI [mA]\n100\t--\t0,5\n110\tn/a\t0,7\n", encoding="utf-8")
    dialog = TraceImportDialog("Experiment", read_data_table(path), window)
    assert dialog.preview.item(0, 1).text() == "--" and dialog.preview.item(1, 1).text() == "n/a"
    dialog.select_columns(0, 1)
    assert "нет ни одной пары чисел" in dialog.error_label.text()
    assert not dialog.button_box.button(ok).isEnabled()
    dialog.select_columns(0, 2)
    assert dialog.error_label.text() == "" and dialog.button_box.button(ok).isEnabled()


def test_dash_file_imports_through_the_menu(window: MainWindow, monkeypatch) -> None:
    from smcapp.ui.trace_import_dialog import TraceImportDialog

    def exec_(dialog):
        dialog.unit_buttons["GHz"].click()
        return QtWidgets.QDialog.DialogCode.Accepted

    action = next(action for action in window.open_files_menu.actions() if action.text() == "Experiment")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(DASHES_EXAMPLE), ""))
    monkeypatch.setattr(TraceImportDialog, "exec", exec_)
    action.trigger()
    QtWidgets.QApplication.processEvents()

    exp = _curves(window)["exp"]
    assert len(exp.xData) == 200 and exp.xData[-1] == pytest.approx(796.56702)


def test_current_goes_to_a_right_log_axis_with_its_own_home(window: MainWindow, tmp_path, monkeypatch) -> None:
    import math

    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    home = window._plot_initial_range
    plot_item = window._plot.getPlotItem()
    assert not plot_item.getAxis("right").isVisible()
    # WP-060: greyed out and empty without a current (their place: the Y2 row test below).
    assert not window._plot_y2_inputs["y2_min"].isEnabled()
    assert window._plot_y2_inputs["y2_min"].text() == "" and window._plot_y2_labels["y2_min"].text() == "Y2 min"

    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "mA")

    right = plot_item.getAxis("right")
    assert right.isVisible() and right.logMode and right.labelText == "I², mA²"
    [exp] = window._right_curve_items
    assert exp.getViewBox() is window._right_view and exp.name() == "exp"
    assert exp.yData.tolist() == pytest.approx([-4.0, -2.0, 0.0])  # WP-064: lg I² of the mA values
    assert [name for name, _ in _legend(window)] == ["SMC", "exp"]
    assert "exp" not in _curves(window)  # not on the S21 axis
    assert "I, mA: правая ось, квадрат I² в логарифмической шкале" in window._s21_status.text()
    # Y2 fields appear, filled from the data; the S21 view stays on Home.
    assert window._plot_y2_inputs["y2_min"].isEnabled() and window._plot_y2_inputs["y2_min"].text() != ""
    assert window._plot_y2_labels["y2_min"].text() == "Y2 min, mA²"
    low, high = window._right_view.viewRange()[1]
    assert low < -4.0 and high > 0.0
    assert window._plot_y2_inputs["y2_min"].value() == pytest.approx(10.0**low)
    assert plot_item.vb.viewRange()[1] == pytest.approx([home[2], home[3]])
    # The X range is shared.
    assert window._right_view.viewRange()[0] == pytest.approx(plot_item.vb.viewRange()[0])

    # Y2 min/max become part of Home.
    window._plot_y2_inputs["y2_min"].setValue(0.001)
    window._plot_y2_inputs["y2_max"].setValue(10.0)
    window._apply_plot_scale()
    assert window._right_view.viewRange()[1] == pytest.approx([-3.0, 1.0])
    assert window._plot_y2_span_label.text() == "ΔY2 = -40.0 dB"  # 10·lg(0.001 / 10)
    window._right_view.scaleBy((1, 0.5))
    assert window._plot_y2_span_label.text() == "ΔY2 = -20.0 dB"  # the wheel zoom changes the span
    window._restore_plot_scale()
    assert window._right_view.viewRange()[1] == pytest.approx([-3.0, 1.0])
    assert window._plot_y2_span_label.text() == "ΔY2 = -40.0 dB"

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
    assert window._plot_hover_label.text().endswith(f"I² = {expected:.3g} mA²; I = {math.sqrt(expected):.3g} mA")
    assert math.isfinite(expected)


def _grid_position(window: MainWindow, widget) -> tuple[int, int]:
    row, column, _rows, _columns = window._plot_controls.getItemPosition(window._plot_controls.indexOf(widget))
    return row, column


def test_y2_fields_sit_after_y_max_and_wrap_under_it_when_narrow(window: MainWindow, tmp_path, monkeypatch) -> None:
    """WP-060 (GitHub #12): Y2 min/max in the first row after Y max, as on the owner's screenshot."""
    # Wide enough for one row whatever the platform font (macOS 13 pt needs more than Windows 9 pt).
    window.resize(1900, 920)
    QtWidgets.QApplication.processEvents()
    y_max_row, y_max_column = _grid_position(window, window._plot_scale_inputs["y_max"])
    controls = window._plot_controls_widget
    assert controls.width() >= window._plot_controls_row_width(with_y2=True)
    assert _grid_position(window, window._plot_y2_labels["y2_min"]) == (y_max_row, y_max_column + 1)
    assert _grid_position(window, window._plot_y2_inputs["y2_min"]) == (y_max_row, y_max_column + 2)
    assert _grid_position(window, window._plot_y2_inputs["y2_max"]) == (y_max_row, y_max_column + 4)
    for name in ("y2_min", "y2_max"):
        assert window._plot_y2_inputs[name].isVisible() and not window._plot_y2_inputs[name].isEnabled()
        assert not window._plot_y2_labels[name].isEnabled()

    # A current on the right axis enables them in place, with its unit.
    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "mA")
    assert window._plot_y2_inputs["y2_max"].isEnabled() and window._plot_y2_labels["y2_max"].isEnabled()
    assert window._plot_y2_labels["y2_max"].text() == "Y2 max, mA²"
    # The label width is reserved for the longest unit: the row does not move.
    assert _grid_position(window, window._plot_y2_inputs["y2_min"]) == (y_max_row, y_max_column + 2)

    # Too narrow for one row: under Y min/Y max, the first row is not clipped.
    window.resize(900, 920)
    QtWidgets.QApplication.processEvents()
    assert window._plot_y2_inputs["y2_max"].isVisible()
    assert controls.width() < window._plot_controls_row_width(with_y2=True)
    y_min_row, y_min_column = _grid_position(window, window._plot_scale_inputs["y_min"])
    assert _grid_position(window, window._plot_y2_labels["y2_min"]) == (y_min_row + 2, y_min_column - 1)
    assert _grid_position(window, window._plot_y2_inputs["y2_max"]) == (y_min_row + 2, y_max_column)
    assert controls.width() >= window._plot_controls_row_width(with_y2=False)
    for widget in (window._plot_scale_inputs["y_max"], window._plot_y2_inputs["y2_max"]):
        assert widget.geometry().right() <= controls.width()

    # Wide again: back in the first row.
    window.resize(1900, 920)
    QtWidgets.QApplication.processEvents()
    assert _grid_position(window, window._plot_y2_inputs["y2_min"]) == (y_max_row, y_max_column + 2)

    # Without a current a narrow panel keeps two rows: no third row of greyed-out fields.
    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "dB")
    window.resize(900, 920)
    QtWidgets.QApplication.processEvents()
    assert not window._plot_y2_inputs["y2_min"].isEnabled() and not window._plot_y2_inputs["y2_min"].isVisible()
    window.resize(1900, 920)
    QtWidgets.QApplication.processEvents()
    assert window._plot_y2_inputs["y2_min"].isVisible() and not window._plot_y2_inputs["y2_min"].isEnabled()


def test_y2_span_in_db_follows_fields_zoom_and_pan(window: MainWindow, tmp_path, monkeypatch) -> None:
    """WP-064: next to Y2 min/max, 10·lg(Y2 min / Y2 max) of I² — 1500…15000 → −10 dB (owner's example)."""
    window.resize(1900, 920)
    QtWidgets.QApplication.processEvents()
    span = window._plot_y2_span_label
    assert span.isVisible() and not span.isEnabled() and span.text() == "ΔY2, dB"
    assert _grid_position(window, span) == _grid_position(window, window._plot_y2_inputs["y2_max"])[:1] + (12,)

    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "µA")
    assert span.isEnabled() and span.text().startswith("ΔY2 = -") and span.text().endswith(" dB")
    y2_min, y2_max = window._plot_y2_inputs["y2_min"], window._plot_y2_inputs["y2_max"]
    assert window._plot_y2_labels["y2_min"].text() == "Y2 min, µA²"
    # Typing shows the span of the typed range, Enter makes it the view and Home.
    y2_min.setValue(1500.0)
    y2_max.setValue(15000.0)
    assert span.text() == "ΔY2 = -10.0 dB"
    y2_min.setValue(150.0)
    assert span.text() == "ΔY2 = -20.0 dB"
    window._apply_plot_scale()
    assert window._right_view.viewRange()[1] == pytest.approx([math.log10(150.0), math.log10(15000.0)])
    assert span.text() == "ΔY2 = -20.0 dB"
    # Wheel zoom on the right axis changes the span; panning keeps it.
    window._right_view.scaleBy((1, 0.5))
    assert span.text() == "ΔY2 = -10.0 dB"
    window._right_view.translateBy(y=0.3)
    assert span.text() == "ΔY2 = -10.0 dB"
    window._restore_plot_scale()
    assert span.text() == "ΔY2 = -20.0 dB"
    # Y2 min ≤ 0 typed on the log scale: no span from the fields, the view's stays.
    y2_min.setValue(0.0)
    assert span.text() == "ΔY2 = -20.0 dB"

    # Narrow panel: the span follows the fields under Y min/Y max.
    window.resize(900, 920)
    QtWidgets.QApplication.processEvents()
    assert span.isVisible() and _grid_position(window, span) == (_grid_position(window, y2_max)[0], 8)


def test_right_axis_hover_shows_the_square_and_the_current(window: MainWindow, tmp_path, monkeypatch) -> None:
    from smcapp.infrastructure.trace_files import Y_QUANTITIES
    from smcapp.ui.app import format_right_axis_span, format_right_axis_value

    assert format_right_axis_value(Y_QUANTITIES["µA"], math.log10(1500.0)) == "I² = 1.5e+03 µA²; I = 38.7 µA"
    assert format_right_axis_value(Y_QUANTITIES["I/Ig"], 2.0) == "(I/I_g)² = 100; I/I_g = 10"
    assert format_right_axis_value(Y_QUANTITIES["(I/Ig)²"], 2.0) == "(I/I_g)² = 100; I/I_g = 10"
    assert format_right_axis_value(Y_QUANTITIES["µA² log"], 3.2) == "lg(I² / µA²) = 3.200; I = 39.8 µA"
    assert format_right_axis_value(Y_QUANTITIES["(I/Ig)² log"], 2.0) == "lg (I/I_g)² = 2.000; I/I_g = 10"
    assert format_right_axis_span(-9.99999) == "ΔY2 = -10.0 dB" and format_right_axis_span(-0.01) == "ΔY2 = 0.0 dB"


def test_log_values_use_a_linear_right_axis_and_db_goes_back_left(window: MainWindow, tmp_path, monkeypatch) -> None:
    path = tmp_path / "log.txt"
    path.write_text("Freq [GHz]; lg I^2 [uA^2]\n100; -1,5\n500; 0,25\n", encoding="utf-8")
    _import_choosing(window, "HFSS", path, monkeypatch, 1, "µA² log")

    right = window._plot.getPlotItem().getAxis("right")
    assert right.isVisible() and not right.logMode and right.labelText == "lg(I² / µA²)"
    [hfss] = window._right_curve_items
    assert hfss.yData.tolist() == pytest.approx([-1.5, 0.25])  # WP-067: lg I² as it is in the file
    assert window._plot_y2_labels["y2_max"].text() == "Y2 max, lg µA²"
    assert window._plot_y2_inputs["y2_min"].value() < -1.5
    # Linear lg I² axis: the span is 10·(Y2 min − Y2 max).
    window._plot_y2_inputs["y2_min"].setValue(3.2)
    window._plot_y2_inputs["y2_max"].setValue(4.2)
    window._apply_plot_scale()
    assert window._plot_y2_span_label.text() == "ΔY2 = -10.0 dB"

    # The same file as dB: back on the S21 axis, the right axis goes away and the Y2 fields grey out.
    _import_choosing(window, "HFSS", path, monkeypatch, 1, "dB")
    assert window._right_curve_items == [] and not right.isVisible()
    assert _curves(window)["HFSS"].yData.tolist() == [-1.5, 0.25]
    assert not window._plot_y2_inputs["y2_max"].isEnabled() and window._plot_y2_inputs["y2_max"].text() == ""
    assert window._plot_y2_labels["y2_max"].text() == "Y2 max"
    assert not window._plot_y2_span_label.isEnabled() and window._plot_y2_span_label.text() == "ΔY2, dB"


@pytest.mark.parametrize("first, second", [(Theme.DARK, Theme.LIGHT), (Theme.LIGHT, Theme.DARK)])
def test_right_axis_label_follows_the_theme(window: MainWindow, tmp_path, monkeypatch, first, second) -> None:
    """BUG-028: the right axis label kept Qt's default black instead of the theme colour."""
    window.set_theme(first)
    _import_choosing(window, "HFSS", _origin_file(tmp_path), monkeypatch, 2, "A² log")
    plot_item = window._plot.getPlotItem()
    right, left = plot_item.getAxis("right"), plot_item.getAxis("left")

    def colour(axis) -> str:
        return QtGui.QColor(axis.labelStyle["color"]).name()

    assert right.isVisible() and right.labelText == "lg(I² / A²)"
    assert colour(right) == colour(left) == QtGui.QColor(THEME_COLORS[first].plot_foreground).name()
    assert right.labelStyle["color"] in right.label.toHtml()  # the drawn text, not only the style
    font_size = right.labelStyle["font-size"]

    window.set_theme(second)
    assert colour(right) == QtGui.QColor(THEME_COLORS[second].plot_foreground).name()
    # A new import of a current keeps the theme colour and the label size.
    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "A² log")
    assert colour(right) == QtGui.QColor(THEME_COLORS[second].plot_foreground).name()
    assert right.labelStyle["font-size"] == font_size


def _drawn_labels(axis) -> list[tuple[QtCore.QRectF, str]]:
    """Tick and edge texts exactly as the axis would draw them."""
    image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
    painter = QtGui.QPainter(image)
    try:
        specs = axis.generateDrawSpecs(painter)
    finally:
        painter.end()
    return [(rect, text) for rect, _flags, text in specs[2]]


def _assert_no_overlap(labels) -> None:
    for index, (rect, text) in enumerate(labels):
        for other, other_text in labels[index + 1 :]:
            assert not rect.intersects(other), f"{text!r} overlaps {other_text!r}"


def _edges(axis) -> tuple[str, str]:
    """(text at the minimum end, text at the maximum end) of a drawn axis."""
    labels = _drawn_labels(axis)
    _assert_no_overlap(labels)
    bounds = axis.mapRectFromParent(axis.geometry())
    if axis.orientation in ("left", "right"):
        low = [text for rect, text in labels if rect.bottom() == pytest.approx(bounds.bottom())]
        high = [text for rect, text in labels if rect.top() == pytest.approx(bounds.top())]
    else:
        low = [text for rect, text in labels if rect.left() == pytest.approx(bounds.left())]
        high = [text for rect, text in labels if rect.right() == pytest.approx(bounds.right())]
    assert len(low) == 1 and len(high) == 1, labels
    return low[0], high[0]


def test_axis_ends_show_the_visible_min_and_max(window: MainWindow) -> None:
    """WP-061 (GitHub #12): both ends of X and Y carry their exact values, as precise as the fields."""
    from smcapp.ui.app import trimmed_number

    assert [trimmed_number(-17.3, 2), trimmed_number(-20.0, 2), trimmed_number(103.0, 0)] == ["-17.3", "-20", "103"]
    assert trimmed_number(-0.001, 2) == "0"
    window.resize(1900, 1200)
    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    plot_item = window._plot.getPlotItem()
    bottom, left = plot_item.getAxis("bottom"), plot_item.getAxis("left")
    QtWidgets.QApplication.processEvents()
    assert _edges(bottom) == ("100", "900") and _edges(left) == ("-20", "0")

    # Typed limits, as the owner sets them under the plot.
    for name, value in (("x_min", 103.7), ("x_max", 893.2), ("y_min", -17.3), ("y_max", -1.2)):
        window._plot_scale_inputs[name].setValue(value)
    window._apply_plot_scale()
    QtWidgets.QApplication.processEvents()
    # Exactly the visible range, with the precision of the fields (X whole GHz, Y 0.01 dB), no trailing zeros.
    assert _edges(bottom) == ("104", "893") and _edges(left) == ("-17.3", "-1.2")

    # Wheel zoom to non-round values: the same field precision; Home (the typed limits) brings them back.
    plot_item.vb.scaleBy((0.37, 0.6))
    QtWidgets.QApplication.processEvents()
    x_range, y_range = plot_item.vb.viewRange()
    assert _edges(bottom) == tuple(trimmed_number(value, 0) for value in x_range)
    assert _edges(left) == tuple(trimmed_number(value, 2) for value in y_range)
    assert len(_edges(left)[0].split(".")[1]) == 2  # a non-round end keeps its hundredths
    window._restore_plot_scale()
    QtWidgets.QApplication.processEvents()
    assert _edges(bottom) == ("104", "893") and _edges(left) == ("-17.3", "-1.2")

    # WP-066: 200…1000 GHz (the owner's #12 screenshot) and beyond stay in GHz, like the X fields.
    plot_item.vb.setXRange(200.0, 1000.0, padding=0)
    QtWidgets.QApplication.processEvents()
    assert "GHz" in bottom.labelString() and "THz" not in bottom.labelString()
    assert _edges(bottom) == ("200", "1000")
    plot_item.vb.setXRange(203.4, 2000.0, padding=0)
    QtWidgets.QApplication.processEvents()
    assert _edges(bottom) == ("203", "2000") and "THz" not in bottom.labelString()
    assert all("." not in text for text in bottom.tickStrings([500.0, 1000.0, 1500.0], 1.0, 500.0))
    assert not bottom.autoSIPrefix


def test_edge_label_wins_over_a_tick_label_it_would_touch(window: MainWindow) -> None:
    """WP-061: a tick label next to an edge label is dropped (its tick line stays), the edge value is kept."""
    window.resize(1900, 1200)
    window._update_s21_plot(FREQUENCIES, [-10.0, -4.0, -2.0, -5.0, -12.0])
    plot_item = window._plot.getPlotItem()
    bottom = plot_item.getAxis("bottom")
    plot_item.vb.setXRange(100.0, 903.0, padding=0)
    QtWidgets.QApplication.processEvents()
    texts = [text for _rect, text in _drawn_labels(bottom)]
    assert _edges(bottom) == ("100", "903") and "900" not in texts and "800" in texts


def test_log_right_axis_ends_and_thinned_ticks(window: MainWindow, tmp_path, monkeypatch) -> None:
    """WP-061: I² ends in the log ticks' notation; crowded minor labels are thinned, none overlap."""
    from smcapp.ui.app import log_axis_edge_string

    assert log_axis_edge_string(math.log10(1500.0)) == "1.5·10³"
    assert log_axis_edge_string(4.0) == "10⁴"
    assert log_axis_edge_string(math.log10(151.3)) == "151"
    assert log_axis_edge_string(math.log10(1.5e-5)) == "1.5·10⁻⁵"

    window.resize(1900, 1200)
    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "µA")
    right = window._plot.getPlotItem().getAxis("right")
    window._plot_y2_inputs["y2_min"].setValue(1500.0)
    window._plot_y2_inputs["y2_max"].setValue(15000.0)
    window._apply_plot_scale()
    QtWidgets.QApplication.processEvents()
    assert _edges(right) == ("1.5·10³", "1.5·10⁴")
    texts = [text for _rect, text in _drawn_labels(right)]
    assert "10⁴" in texts  # the decade inside the range keeps its label
    # Without thinning all of 2·10³ … 9·10³ would be drawn on this short axis.
    minor = [text for text in texts if text.endswith("·10³") and text != "1.5·10³"]
    assert 0 < len(minor) < 8

    # The linear "Log" axis: ends like its ticks.
    _import_choosing(window, "Experiment", _origin_file(tmp_path), monkeypatch, 2, "µA² log")
    window._plot_y2_inputs["y2_min"].setValue(3.2)
    window._plot_y2_inputs["y2_max"].setValue(4.2)
    window._apply_plot_scale()
    QtWidgets.QApplication.processEvents()
    assert _edges(right) == ("3.2", "4.2")
