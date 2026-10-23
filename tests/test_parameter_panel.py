"""Integration checks for safe, collapsible and persistent parameters."""

from __future__ import annotations

import gc
from typing import cast
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.domain.s21_models import S21Config
from aocapp.domain.transformers import ELEMENT_NUMBERS, ELEMENT_ORDER, element_group
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow


@pytest.fixture
def parameter_window() -> MainWindow:
    # Collect cycles from the previous pyqtgraph window before constructing
    # new graphics items: a GC pass inside AxisItem.resizeEvent can otherwise
    # destroy wrappers from the preceding QtAds window reentrantly.
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(
        GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()),
        cast(CalculateS21UseCase, Mock()),
    )
    window.resize(1440, 920)
    window.show()
    app.processEvents()
    yield window
    # Persistence is covered by the dedicated dock-layout tests. Avoid asking
    # QtAds to serialize a window while deferred Qt objects are being torn down
    # repeatedly by this per-test fixture.
    window.save_settings = Mock()
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
    app.processEvents()


def _wheel_event(widget: QtWidgets.QWidget) -> QtGui.QWheelEvent:
    center = QtCore.QPointF(widget.rect().center())
    return QtGui.QWheelEvent(
        center,
        QtCore.QPointF(widget.mapToGlobal(widget.rect().center())),
        QtCore.QPoint(),
        QtCore.QPoint(0, 120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.ScrollUpdate,
        False,
    )


def test_wheel_requires_click_and_groups_collapse(parameter_window: MainWindow) -> None:
    app = QtWidgets.QApplication.instance()
    assert app is not None
    spin = parameter_window._config_inputs["l_slot_m"]
    original = spin.value()

    app.sendEvent(spin, _wheel_event(spin))
    assert spin.value() == original

    QTest.mouseClick(spin, QtCore.Qt.MouseButton.LeftButton, pos=spin.rect().center())
    app.sendEvent(spin, _wheel_event(spin))
    assert spin.value() == original + spin.singleStep()

    group = parameter_window._parameter_groups["Dielectrics"]
    assert group.toggle_button.arrowType() == QtCore.Qt.ArrowType.DownArrow
    group.setChecked(False)
    app.processEvents()
    assert not group.content.isVisible()
    assert group.toggle_button.arrowType() == QtCore.Qt.ArrowType.RightArrow
    assert not parameter_window.parameters_scroll.isAncestorOf(parameter_window.actions_box)


def test_greek_labels_fixed_orders_and_design_round_trip(parameter_window: MainWindow, tmp_path) -> None:
    labels = {label.text() for label in parameter_window.findChildren(QtWidgets.QLabel)}
    assert {"α EL1", "σ EL1", "ε₁₂"} <= labels

    order = parameter_window._engineering_orders["d_top_m"]
    assert isinstance(order, QtWidgets.QLabel)
    assert order.text() == "×10^-6 m"
    assert int(order.text().split("^")[1].split()[0]) % 3 == 0

    path = tmp_path / "round-trip.aocdesign"
    parameter_window._same_materials_checkbox.setChecked(False)
    parameter_window._config_inputs["tc_bot_k"].setValue(8.7)
    parameter_window._config_inputs["l_slot_m"].setValue(42.5)
    parameter_window.save_design_to_path(path)

    parameter_window._config_inputs["tc_bot_k"].setValue(7.0)
    parameter_window._config_inputs["l_slot_m"].setValue(10.0)
    loaded = parameter_window.load_design_from_path(path)

    assert loaded.tc_bot_k == pytest.approx(8.7)
    assert parameter_window._config_inputs["tc_bot_k"].value() == pytest.approx(8.7)
    assert parameter_window._config_inputs["l_slot_m"].value() == pytest.approx(42.5)
    assert not parameter_window._same_materials_checkbox.isChecked()
    assert "Block 1 / Block 2" not in parameter_window._parameter_groups
    assert "block_center_length_um" not in parameter_window._config_inputs


def test_issue_4_group_order_and_sis_capacitance_units(parameter_window: MainWindow) -> None:
    assert list(parameter_window._parameter_groups)[:3] == ["LO", "Backend Grid", "EL1 Material"]

    capacitance = parameter_window._config_inputs["sis_cap_f_per_um2"]
    assert capacitance.value() == pytest.approx(0.083)
    assert capacitance.suffix() == ""
    assert parameter_window._parameter_units["sis_cap_f_per_um2"].text() == "pF/µm²"
    assert parameter_window._build_config().sis_cap_f_per_um2 == pytest.approx(8.3e-14)


def test_preview_rejects_nonpositive_corrected_dc_slot(parameter_window: MainWindow) -> None:
    parameter_window._config_inputs["w_slot_m"].setValue(0.1)
    parameter_window._config_inputs["dw_m"].setValue(0.5)

    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        parameter_window._update_svg()

    warning.assert_called_once()
    assert "w_slot_m must be > dw_m" in warning.call_args.args[2]


def test_open_file_menu_imports_experiment_and_rejects_hfss(parameter_window: MainWindow, tmp_path) -> None:
    assert [action.text() for action in parameter_window.open_files_menu.actions()] == [
        "Параметры SMC_app",
        "Experiment",
    ]
    hint = parameter_window.findChild(QtWidgets.QLabel, "parameter_file_hint")
    load_button = parameter_window.findChild(QtWidgets.QPushButton, "load_parameters_button")
    save_button = parameter_window.findChild(QtWidgets.QPushButton, "save_parameters_button")
    assert hint is not None and "не файл Mathcad" in hint.text()
    assert load_button is not None and ".mcd/.mcdx не поддерживаются" in load_button.toolTip()
    assert save_button is not None and "кривая S21" in save_button.toolTip()
    hfss = tmp_path / "hfss.txt"
    experiment = tmp_path / "experiment.txt"
    hfss.write_text("100 -12\n110 -9\n", encoding="utf-8")
    experiment.write_text("100 -13\n110 -10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Неизвестный тип"):
        parameter_window.load_comparison_trace("HFSS", hfss)
    parameter_window.load_comparison_trace("Experiment", experiment)
    parameter_window._update_s21_plot([100.0, 110.0], [-11.5, -9.5])

    assert set(parameter_window._comparison_traces) == {"Experiment"}
    assert len(parameter_window._plot.listDataItems()) == 2
    legend_labels = {label.text for _, label in parameter_window._plot_legend.items}
    assert legend_labels == {"Theory", "Experiment"}


@pytest.mark.parametrize("name,value", [("x_min", 150), ("x_max", 800), ("y_min", -30), ("y_max", 5)])
@pytest.mark.parametrize("key", [QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter])
def test_enter_applies_plot_bounds(parameter_window: MainWindow, name, value, key) -> None:
    spin = parameter_window._plot_scale_inputs[name]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), str(value))
    QTest.keyClick(spin.lineEdit(), key)
    expected = {"x_min": 100, "x_max": 900, "y_min": -20, "y_max": 0}
    expected[name] = value
    ranges = parameter_window._plot.getPlotItem().vb.viewRange()
    assert ranges[0] == pytest.approx([expected["x_min"], expected["x_max"]])
    assert ranges[1] == pytest.approx([expected["y_min"], expected["y_max"]])


def test_enter_rejects_reversed_plot_bounds(parameter_window: MainWindow) -> None:
    spin = parameter_window._plot_scale_inputs["x_min"]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "950")
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    warning.assert_called_once()
    assert parameter_window._plot_initial_range == (100, 900, -20, 0)


def test_all_element_fields_have_matching_numbers_and_external_units(parameter_window: MainWindow) -> None:
    window = parameter_window
    groups = [name for name in window._parameter_groups if " · " in name]
    assert groups == [element_group(element) for element in ELEMENT_ORDER]
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    fields = S21Config.ui_fields()
    correction = next(info for info in fields if info.name == "dw_m")
    assert correction.element_id is None and correction.group == "Dielectrics"
    assert {info.element_id for info in fields if info.element_id} == set(ELEMENT_ORDER)
    for info in fields:
        spin = window._config_inputs[info.name]
        assert spin.suffix() == ""
        assert float(spin.lineEdit().text()) == pytest.approx(spin.value())
        if info.suffix:
            assert window._parameter_units[info.name].text()
        if info.element_id:
            assert f"{ELEMENT_NUMBERS[info.element_id]} · {info.label}" in labels
            assert window._parameter_groups[info.group].isAncestorOf(spin)


@pytest.mark.parametrize(
    "name",
    [
        "mex4_width_m",
        "mex4_len_m",
        "lso_m",
        "w_ms_m",
        "l_ms_m",
        "w_slot_m",
        "l_slot_m",
        "dc_gap_m",
        "radial_r_min_m",
        "radial_r_max_m",
        "radial_angle_deg",
        *(f"zrad{i}_{suffix}" for i in (1, 3, 4) for suffix in ("width_m", "len_m")),
        *(f"msl_{i}_{suffix}" for i in (4, 5, 6, 7, 8) for suffix in ("width_m", "len_m")),
    ],
)
def test_enter_updates_each_geometry_field(parameter_window: MainWindow, name) -> None:
    window = parameter_window
    original = window._use_case.execute(window._build_config(), show_details=False)
    spin = window._config_inputs[name]
    value = spin.value() + 1
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), str(value))
    with patch.object(window._view, "set_svg", wraps=window._view.set_svg) as displayed:
        QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    displayed.assert_called_once()
    assert displayed.call_args.args[0] != original
    assert getattr(window._build_config(), name) == pytest.approx(value / S21Config.field_scale(name))


@pytest.mark.parametrize("width", [0.1, 9, 500])
def test_sis_feed_width_enter_changes_actual_metal(parameter_window: MainWindow, width) -> None:
    spin = parameter_window._config_inputs["mex4_width_m"]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), str(width))
    QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    config = parameter_window._build_config()
    geometry = IntegratedStructureCalculator().calculate(config)
    feed = next(e for e in geometry.elements if e.element_id == "SIS-line")
    assert feed.bounds.height == pytest.approx((width + config.dw_m * 1e6) * 2)


def test_enter_invalid_geometry_retains_last_preview(parameter_window: MainWindow) -> None:
    spin = parameter_window._config_inputs["w_slot_m"]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "0.1")
    with patch.object(QtWidgets.QMessageBox, "warning") as warning, patch.object(
        parameter_window._view, "set_svg"
    ) as shown:
        QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    warning.assert_called_once()
    shown.assert_not_called()


def test_plot_home_hover_and_png_export(parameter_window: MainWindow, tmp_path) -> None:
    app = QtWidgets.QApplication.instance()
    assert app is not None
    assert parameter_window._plot_initial_range == (100.0, 900.0, -20.0, 0.0)
    assert parameter_window._plot_scale_inputs["x_min"].singleStep() == 10.0
    assert parameter_window._plot_scale_inputs["y_min"].singleStep() == 5.0
    initial_x_range, initial_y_range = parameter_window._plot.getPlotItem().vb.viewRange()
    assert initial_x_range == pytest.approx([100.0, 900.0])
    assert initial_y_range == pytest.approx([-20.0, 0.0])

    parameter_window._plot_scale_inputs["x_min"].setValue(95.0)
    parameter_window._plot_scale_inputs["x_max"].setValue(145.0)
    parameter_window._plot_scale_inputs["y_min"].setValue(-25.0)
    parameter_window._plot_scale_inputs["y_max"].setValue(0.0)
    parameter_window._apply_plot_scale()

    x_range, y_range = parameter_window._plot.getPlotItem().vb.viewRange()
    assert x_range == pytest.approx([95.0, 145.0])
    assert y_range == pytest.approx([-25.0, 0.0])

    view_box = parameter_window._plot.getPlotItem().vb
    scene_position = view_box.mapToScene(view_box.boundingRect().center())
    parameter_window._on_plot_mouse_moved(scene_position)
    assert parameter_window._plot_hover_label.isVisible()
    assert "GHz" in parameter_window._plot_hover_label.text()
    assert "S21" in parameter_window._plot_hover_label.text()
    assert "dB" in parameter_window._plot_hover_label.text()
    assert "f = 120." in parameter_window._plot_hover_label.text()

    parameter_window._plot_scale_inputs["x_min"].setValue(100.0)
    parameter_window._plot_scale_inputs["x_max"].setValue(1100.0)
    parameter_window._apply_plot_scale()
    app.processEvents()
    assert parameter_window._frequency_axis.labelUnits == "THz"
    assert parameter_window._frequency_axis.tickStrings([1000.0], 1.0, 100.0) == ["1.0"]

    destination = tmp_path / "plot.png"
    assert parameter_window.export_plot_to_path(destination) == destination
    assert destination.read_bytes().startswith(b"\x89PNG")


def test_successful_calculations_keep_only_one_owned_previous_trace(parameter_window: MainWindow, tmp_path) -> None:
    x, first = [100, 200], [-12, -8]
    parameter_window._update_s21_plot(x, first)
    assert parameter_window._previous_theory_trace is None
    first[0] = 999  # Samples must not change with the caller's mutable buffer.
    parameter_window._update_s21_plot([110, 210, 310], [-11, -7, -9])
    assert parameter_window._previous_theory_trace == ([100, 200], [-12, -8])
    curves = {item.name(): item for item in parameter_window._plot.listDataItems()}
    previous, current = curves["Previous theory"], curves["Theory"]
    assert previous.zValue() < current.zValue()
    assert previous.opts["pen"].color().alphaF() == pytest.approx(0.6)
    assert previous.opts["pen"].color().red() == 70
    assert previous.xData.tolist() == [100, 200]
    assert current.xData.tolist() == [110, 210, 310]
    parameter_window._redraw_plot()  # Import/redraw must not rotate history.
    assert parameter_window._previous_theory_trace == ([100, 200], [-12, -8])
    with patch.object(QtWidgets.QMessageBox, "critical"):
        parameter_window._on_s21_failed("test failure")
    assert parameter_window._previous_theory_trace == ([100, 200], [-12, -8])
    parameter_window._update_s21_plot([120, 220], [-10, -6])
    assert parameter_window._previous_theory_trace == ([110, 210, 310], [-11, -7, -9])
    assert len(parameter_window._plot.listDataItems()) == 2
    parameter_window.export_plot_to_path(tmp_path / "two-curves.png")


def test_y_threshold_survives_redraw_and_home_without_affecting_history(parameter_window: MainWindow) -> None:
    line = parameter_window._plot_threshold_line
    spin = parameter_window._plot_threshold_input
    assert line.value() == spin.value() == -5
    assert line.pen.color().name() == "#dc2626"
    assert line.pen.widthF() == 1
    spin.setValue(-7.5)
    parameter_window._update_s21_plot([100, 200], [-12, -8])
    parameter_window._restore_plot_scale()
    assert line.value() == -7.5
    assert line in parameter_window._plot.getPlotItem().items
    assert parameter_window._previous_theory_trace is None
    assert parameter_window._plot_initial_range == (100, 900, -20, 0)
    parameter_window._update_s21_plot([100, 200], [-10, -6])
    assert line.value() == -7.5


def test_starting_calculation_does_not_clear_successful_results(parameter_window: MainWindow) -> None:
    parameter_window._update_s21_plot([100, 200], [-12, -8])
    parameter_window._update_s21_plot([100, 200], [-10, -6])
    parameter_window._s21_output.clear()
    with patch("aocapp.ui.app.QThread"), patch("aocapp.ui.app.S21Worker"):
        parameter_window._run_s21()
        assert parameter_window._theory_trace == ([100, 200], [-10, -6])
        assert parameter_window._previous_theory_trace == ([100, 200], [-12, -8])
        assert len(parameter_window._plot.listDataItems()) == 2
        parameter_window._on_s21_thread_finished()


def test_issue_7_element_labels(parameter_window: MainWindow) -> None:
    assert "8 · DC block" in parameter_window._parameter_groups
    assert "DC Break" not in parameter_window._parameter_groups
    assert parameter_window._transformer_status[7].text().startswith("n=5;")
    parameter_window._config_inputs["transf_7_w_end_m"].setValue(15)
    assert " µm; ступеней" not in parameter_window._transformer_status[7].text()


def test_schematic_details_toggle_keeps_overview_large(parameter_window: MainWindow) -> None:
    app = QtWidgets.QApplication.instance()
    compact = parameter_window._view._svg_item.boundingRect()
    toggle = parameter_window.findChild(QtWidgets.QCheckBox, "schematic_details")
    assert toggle is not None and not toggle.isChecked()
    QTest.mouseClick(toggle, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, toggle.height() // 2))
    app.processEvents()
    detailed = parameter_window._view._svg_item.boundingRect()
    assert detailed.height() > compact.height() * 1.5
    view = parameter_window._view
    assert view._fit_width
    assert view.transform().mapRect(detailed).width() > view.viewport().width() * 0.9
    assert view.verticalScrollBar().maximum() > view.viewport().height()
    wheel = QtGui.QWheelEvent(
        QtCore.QPointF(view.viewport().rect().center()),
        QtCore.QPointF(view.mapToGlobal(view.rect().center())),
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.NoScrollPhase,
        False,
    )
    old_scale = view.transform().m11()
    QtWidgets.QApplication.sendEvent(view.viewport(), wheel)
    assert view.verticalScrollBar().value() > 0
    assert view.transform().m11() == old_scale
    view.reset_view()
    assert view.verticalScrollBar().value() == 0
    QTest.mouseClick(toggle, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, toggle.height() // 2))
    app.processEvents()
    assert parameter_window._view._svg_item.boundingRect() == compact
    assert not parameter_window._view._fit_width


def _enter_value(window: MainWindow, name: str, value: float) -> None:
    spin = window._config_inputs[name]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), f"{value:g}")
    QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    QtWidgets.QApplication.processEvents()


def _view_centre(view) -> QtCore.QPointF:
    return view._scene_to_svg(view.mapToScene(view.viewport().rect().center()))


def test_parameter_redraw_keeps_the_zoomed_element_in_view(parameter_window: MainWindow) -> None:
    view = parameter_window._view
    geometry = IntegratedStructureCalculator().calculate(parameter_window._build_config())
    dc = next(e for e in geometry.overview.elements if e.element_id == "DC")
    for _ in range(12):
        QtWidgets.QApplication.sendEvent(view.viewport(), _wheel_event(view.viewport()))
    view.centerOn(view._svg_to_scene(QtCore.QPointF(dc.bounds.x + dc.bounds.width / 2, dc.bounds.y)))
    QtWidgets.QApplication.processEvents()
    scale, centre = view.transform().m11(), _view_centre(view)
    old_box = view._renderer.viewBoxF()
    # A wider line 2 grows the drawing upwards and moves the viewBox origin.
    _enter_value(parameter_window, "msl_8_width_m", 90)
    assert view._renderer.viewBoxF().y() < old_box.y()
    assert view._zoom_level == 12
    assert view.transform().m11() == pytest.approx(scale)
    after = _view_centre(view)
    assert after.x() == pytest.approx(centre.x(), abs=1)
    assert after.y() == pytest.approx(centre.y(), abs=1)
    # Home still returns to the fitted overview.
    view.reset_view()
    assert view._zoom_level == 0
    assert view.transform().m11() < scale


def test_parameter_redraw_keeps_the_scrolled_dimension_card(parameter_window: MainWindow) -> None:
    view = parameter_window._view
    parameter_window._schematic_details.setChecked(True)
    QtWidgets.QApplication.processEvents()
    scroll = view.verticalScrollBar()
    scroll.setValue(scroll.maximum() // 2)
    QtWidgets.QApplication.processEvents()
    centre = _view_centre(view)
    _enter_value(parameter_window, "l_ms_m", 30)
    assert view._fit_width
    # Scroll bars and centerOn round to whole pixels: allow two.
    assert _view_centre(view).y() == pytest.approx(centre.y(), abs=2.01 / view.transform().m11())
    # Switching the mode is a new view and starts from the top again.
    parameter_window._schematic_details.setChecked(False)
    parameter_window._schematic_details.setChecked(True)
    QtWidgets.QApplication.processEvents()
    assert scroll.value() == 0


def test_issue_5_steps_and_sigma_keyboard_input(parameter_window: MainWindow) -> None:
    inputs = parameter_window._config_inputs
    for name, spin in inputs.items():
        if name.endswith("_ghz"):
            assert spin.singleStep() == (1.0 if "step" in name else 10.0)
    assert inputs["sis_rn_area_ohm_um2"].singleStep() == 0.5
    for name in ("w_slot_m", "l_slot_m", "sis_width_um", "radial_r_min_m", "transf_7_length_m", "msl_8_width_m"):
        assert inputs[name].singleStep() == 0.5
    sigma = inputs["sigma0_top"]
    assert sigma.value() == 18.0
    assert parameter_window._engineering_orders["sigma0_top"].text() == "×10^6 1/(Ω·m)"
    for text, expected in (("0,975", 975000), ("18.000001", 18000001), ("0.975000", 975000)):
        sigma.lineEdit().selectAll()
        QTest.keyClicks(sigma.lineEdit(), text)
        QTest.keyClick(sigma.lineEdit(), QtCore.Qt.Key_Return)
        config = parameter_window._build_config()
        assert config.sigma0_top == pytest.approx(expected)
        assert config.sigma0_bot == pytest.approx(expected)


def test_issue_6_order_conversion_and_invalid_length(parameter_window: MainWindow) -> None:
    groups = [name for name in parameter_window._parameter_groups if " · " in name]
    assert [int(name.split()[0]) for name in groups] == list(range(1, 20))
    inputs = parameter_window._config_inputs
    assert "transf_7_dwdl_um" not in inputs
    assert inputs["transf_7_w_end_m"].value() == 14  # W1 on the drawing's left
    assert inputs["transf_7_w_start_m"].value() == 49  # W2 on the right
    original = parameter_window._build_config()
    assert original.transf_7_dwdl_um == 5
    assert original.transf_7_dl_m == 1.2e-6

    inputs["transf_7_w_end_m"].setValue(18)
    inputs["transf_7_w_start_m"].setValue(6)
    inputs["transf_7_length_m"].setValue(7)
    converted = parameter_window._build_config()
    assert converted.transf_7_w_end_m == pytest.approx(18e-6)
    assert converted.transf_7_w_start_m == pytest.approx(6e-6)
    assert converted.transf_7_dwdl_um == 2
    assert converted.transf_7_dl_m == pytest.approx(1e-6)
    assert "ступеней: 7" in parameter_window._transformer_status[7].text()
    inputs["transf_7_length_m"].setValue(100)
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        parameter_window._update_svg()
    assert "Элемент 1" in warning.call_args.args[2]
    assert "нет целого n" in parameter_window._transformer_status[7].text()


def test_preview_button_uses_current_fields_for_dimensions(parameter_window: MainWindow) -> None:
    window = parameter_window
    window._schematic_details.setChecked(True)
    inputs = window._config_inputs
    for name, value in {
        "transf_1_w_end_m": 22,
        "transf_1_w_start_m": 8,
        "transf_1_length_m": 8,
        "mex4_len_m": 12,
        "mex4_width_m": 9,
        "dw_m": 0.75,
        "sis_width_um": 25,
    }.items():
        inputs[name].setValue(value)
    preview = next(b for b in window.findChildren(QtWidgets.QPushButton) if b.text() == "Update Preview")
    with patch.object(window._view, "set_svg", wraps=window._view.set_svg) as displayed:
        QTest.mouseClick(preview, QtCore.Qt.MouseButton.LeftButton)
    svg = displayed.call_args.args[0]
    for expected in (
        "W1=22 µm; W2=8 µm; L=8 µm",
        "W1эфф=22.75",
        "W2эфф=8.75",
        "W=9 µm; L=12 µm",
        "Wэфф=9.75",
        "W SIS (расч.)=25 µm",
    ):
        assert expected in svg
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    assert {"14 · Линия у SIS · L", "14 · Линия у SIS · W"} <= labels


def test_legacy_transformer_round_trip_preserves_discretization(parameter_window: MainWindow, tmp_path) -> None:
    from aocapp.domain.s21_models import S21Config

    legacy = S21Config(transf_7_dwdl_um=1.7, transf_7_dl_m=0.125e-6, transf_7_w_start_m=49.123456e-6)
    source = tmp_path / "legacy.aocdesign"
    destination = tmp_path / "saved.aocdesign"
    parameter_window._design_files.save(source, legacy)
    parameter_window.load_design_from_path(source)
    parameter_window.save_design_to_path(destination)
    saved = parameter_window._design_files.load(destination)
    for name, value in legacy.__dict__.items():
        if name.startswith("transf_"):
            assert getattr(saved, name) == value


def test_s21_output_filename_folder_and_worker(parameter_window: MainWindow, tmp_path) -> None:
    from aocapp.api.io import IOService
    from aocapp.domain.s21_models import S21Result
    from aocapp.ui.app import _default_s21_output_directory

    folder = tmp_path / "Папка результатов"
    folder.mkdir()
    picker = parameter_window.findChild(QtWidgets.QPushButton, "select_s21_directory")
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=str(folder)) as dialog:
        QTest.mouseClick(picker, QtCore.Qt.LeftButton)
    dialog.assert_called_once()
    assert parameter_window._s21_output_directory.isReadOnly()
    assert _default_s21_output_directory() == folder
    parameter_window._s21_output.setText("результат.tab")
    destination = folder / "результат.tab"

    def execute(config, output_path, progress_callback):
        config.validate()
        progress_callback("Проверка выбранной папки")
        assert output_path == str(destination)
        IOService().write(output_path, ([100, 110], [-12, -9]))
        return S21Result([100, 110], [-12, -9])

    parameter_window._s21_use_case.execute.side_effect = execute
    parameter_window._run_s21()
    for _ in range(100):
        QTest.qWait(10)
        if parameter_window._s21_thread is None:
            break
    assert parameter_window._s21_thread is None
    assert destination.read_text() == "100\t-12\n110\t-9\n"
    assert parameter_window._s21_output.text() == "результат.tab"
    assert str(destination) in parameter_window._s21_status.text()
    with patch.object(QtWidgets.QFileDialog, "getExistingDirectory", return_value=""):
        parameter_window._select_s21_output_directory()
    assert parameter_window._s21_output_directory.text() == str(folder)
    for invalid in ("../escape.tab", "/tmp/escape.tab", "C:\\escape.tab", "..", "CON.tab"):
        parameter_window._s21_output.setText(invalid)
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            parameter_window._run_s21()
        warning.assert_called_once()
        assert parameter_window._s21_thread is None
    parameter_window._s21_output.clear()
    assert parameter_window._s21_result_path() is None


def test_png_write_failure_is_reported_without_changing_plot(parameter_window: MainWindow, tmp_path) -> None:
    plot = parameter_window._plot.getPlotItem()
    original_range = plot.vb.viewRange()
    directory = tmp_path / "directory.png"
    directory.mkdir()
    with pytest.raises(OSError, match="Не удалось сохранить PNG"):
        parameter_window.export_plot_to_path(directory)
    assert plot.vb.viewRange() == original_range
    destination = tmp_path / "valid.png"
    parameter_window.export_plot_to_path(destination)
    assert destination.read_bytes().startswith(b"\x89PNG")


def test_s21_cleanup_waits_for_native_worker_destruction(parameter_window: MainWindow) -> None:
    worker = Mock()
    thread = Mock()

    def finish_native_cleanup():
        # Qt's finished signal can reach the GUI before worker deferred
        # deletion completes. Neither wrapper may be released in that phase.
        assert parameter_window._s21_worker is worker
        assert parameter_window._s21_thread is thread
        return True

    thread.wait.side_effect = finish_native_cleanup
    parameter_window._s21_worker = worker
    parameter_window._s21_thread = thread
    parameter_window._on_s21_thread_finished()
    thread.wait.assert_called_once_with()
    assert parameter_window._s21_worker is None
    assert parameter_window._s21_thread is None
    assert parameter_window._run_s21_button.isEnabled()
