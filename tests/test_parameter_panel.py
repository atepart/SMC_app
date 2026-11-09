"""Integration checks for safe, collapsible and persistent parameters."""

from __future__ import annotations

import gc
import json
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from smcapp.application.s21_use_case import CalculateS21UseCase
from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.domain.circuit import element_numbers, element_order
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.design_files import DesignFileService
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow, SafeDoubleSpinBox
from smcapp.ui.theme import THEME_COLORS


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


def test_wheel_does_not_take_focus(parameter_window: MainWindow) -> None:
    """Scrolling the form over the fields must not make each passed field active.

    Qt gives focus on a real (spontaneous) wheel to widgets with ``WheelFocus``,
    the default of spin boxes; a test cannot send a spontaneous wheel, so the
    policy itself is checked on every field of the window.
    """
    spins = parameter_window.findChildren(SafeDoubleSpinBox)
    assert len(spins) > 50
    for spin in spins:
        assert spin.focusPolicy() == QtCore.Qt.FocusPolicy.StrongFocus
        assert spin.focusPolicy() & QtCore.Qt.FocusPolicy.WheelFocus != QtCore.Qt.FocusPolicy.WheelFocus
    spin = parameter_window._config_inputs["l_slot_m"]
    QTest.mouseClick(spin, QtCore.Qt.MouseButton.LeftButton, pos=spin.rect().center())
    assert spin.hasFocus()  # a click still activates the field


def _typed(value: float, decimals: int, cursor: int, keys: str, maximum: float = 1000.0) -> tuple[str, int]:
    spin = SafeDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setRange(0.1, maximum)
    spin.setValue(value)
    spin.lineEdit().deselect()
    spin.lineEdit().setCursorPosition(cursor)
    QTest.keyClicks(spin, keys)
    return spin.lineEdit().text(), spin.lineEdit().cursorPosition()


@pytest.mark.parametrize(
    "value,decimals,cursor,keys,expected",
    [
        (7.0, 1, 2, "5", ("7.5", 3)),  # a digit that does not fit pushes the last one out
        (0.8, 2, 2, "3", ("0.38", 3)),
        (3.0, 3, 0, "1", ("13.000", 1)),  # fits as typed: ordinary insertion
        (7.0, 1, 3, "5", ("7.0", 3)),  # typed at the very end: nothing changes
        (12.5, 2, 1, ".", ("1.25", 2)),  # a point first removes the existing point
        (12.5, 2, 1, ",", ("1,25", 2)),
        (0.38, 2, 1, ".", ("0.38", 2)),  # Qt alone would accept "0..38"
        (12.5, 1, 1, ".", ("1.2", 2)),  # …then decimals that no longer fit are cut
        (123.0, 0, 1, "4", ("142", 2)),  # no point to remove: the last character goes
        (999.0, 1, 0, "5", ("999.0", 0)),  # above the maximum even after pushing out
        (7.0, 1, 2, "a", ("7.0", 2)),
    ],
)
def test_typing_into_a_full_field_pushes_out_a_character(value, decimals, cursor, keys, expected) -> None:
    assert QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert _typed(value, decimals, cursor, keys) == expected


def test_pushed_out_value_is_applied_and_undoable(parameter_window: MainWindow) -> None:
    spin = parameter_window._config_inputs["sis_area_um2"]
    spin.setValue(0.8)
    spin.setFocus()
    edit = spin.lineEdit()
    edit.deselect()
    edit.setCursorPosition(2)
    QTest.keyClicks(spin, "3")
    assert edit.text() == "0.38" and spin.value() == pytest.approx(0.8)  # applied on Enter, as before
    edit.undo()
    assert edit.text() == "0.80"
    edit.redo()
    QTest.keyClick(spin, QtCore.Qt.Key.Key_Return)
    assert spin.value() == pytest.approx(0.38)
    assert parameter_window._build_config().sis_area_um2 == pytest.approx(0.38)


def test_greek_labels_fixed_orders_and_design_round_trip(parameter_window: MainWindow, tmp_path) -> None:
    labels = {label.text() for label in parameter_window.findChildren(QtWidgets.QLabel)}
    assert {"α EL1", "σ EL1", "ε₁₂"} <= labels

    order = parameter_window._engineering_orders["d_top_m"]
    assert isinstance(order, QtWidgets.QLabel)
    assert order.text() == "×10^-9 m"  # thicknesses in nm (GitHub #10)
    assert int(order.text().split("^")[1].split()[0]) % 3 == 0

    path = tmp_path / "round-trip.smcdesign"
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
    assert list(parameter_window._parameter_groups)[:3] == ["General", "Backend Grid", "EL1 Material"]

    capacitance = parameter_window._config_inputs["sis_cap_f_per_um2"]
    assert capacitance.value() == pytest.approx(0.083)
    assert capacitance.suffix() == ""
    assert parameter_window._parameter_units["sis_cap_f_per_um2"].text() == "pF/µm²"
    assert parameter_window._build_config().sis_cap_f_per_um2 == pytest.approx(8.3e-14)


def test_issue_10_field_precision_and_general_block(parameter_window: MainWindow) -> None:
    """GitHub #10: editors show the requested precision instead of long zero tails."""
    window, inputs = parameter_window, parameter_window._config_inputs
    shown = {name: spin.text() for name, spin in inputs.items()}
    assert shown["mex02_3_length_m"] == "25.0" and shown["mex02_3_width_m"] == "4.0"
    assert shown["mex01_1_length_m"] == "9.6"
    assert shown["lso_m"] == "8.0" and shown["dc_gap_m"] == "4.0" and shown["mex4_len_m"] == "3.0"
    assert shown["dw_m"] == "0.50"
    assert "f0_ghz" not in shown  # WP-046: Mex04 uses the sweep frequency
    assert shown["s21_freq_step_ghz"] == "5" and shown["film_freq_stop_ghz"] == "1110"
    assert shown["z_ffo_ohm"] == "0.15"
    assert shown["temperature_k"] == "4.2" and shown["tc_top_k"] == "9.5"
    assert shown["alpha_top"] == "3.54"
    assert shown["sigma0_top"] == "18.000"
    assert shown["h12_m"] == "466" and shown["h1_m"] == "166" and shown["d_top_m"] == "350"
    assert window._parameter_units["h12_m"].text() == "×10^-9 m"
    assert shown["h_sub_m"] == "350"
    assert shown["sis_area_um2"] == "0.80" and shown["sis_rn_area_ohm_um2"] == "32.0"
    assert shown["sis_cap_f_per_um2"] == "0.083"
    assert shown["sis_width_um"] == "4.0"
    assert shown["zrad0_ohm"] == "50" and shown["radial_angle_deg"] == "113"
    assert window._plot_scale_inputs["x_min"].text() == "100"

    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    assert {"dW", "15 · Wb"} <= labels and "DW" not in labels and "15 · W SIS" not in labels
    general = window._parameter_groups["General"].form_layout
    names = [
        name
        for name in inputs
        if inputs[name].parentWidget() and window._parameter_groups["General"].isAncestorOf(inputs[name])
    ]
    assert names == [
        "s21_freq_start_ghz",
        "s21_freq_stop_ghz",
        "s21_freq_step_ghz",
        "z_ffo_ohm",
        "dw_m",
        "temperature_k",
        "e_sub",
        "h_sub_m",
    ]
    assert general.rowCount() == len(names)
    assert "LO" not in window._parameter_groups

    # Rounded display, exact calculation: untouched editors keep the loaded value.
    config = window._build_config()
    assert config.h12_m == 0.465729e-6 and config.h1_m == 1.65729e-7
    _enter_value(window, "h12_m", 470)
    assert window._build_config().h12_m == pytest.approx(470e-9)
    _enter_value(window, "mex02_3_width_m", 4.26)  # a digit beyond 0.1 µm is not accepted
    assert inputs["mex02_3_width_m"].text() == "4.2"
    assert window._build_config().mex02[2].width_m == pytest.approx(4.2e-6)


def test_issue_10_radial_stub_line_and_output_line_names(parameter_window: MainWindow) -> None:
    """GitHub #10: 16 «Radial Stub line» L3/W3, 18 «Выходная линия» L1/W1, without the small w."""
    window = parameter_window
    assert {"16 · Radial Stub line", "18 · Выходная линия"} <= set(window._parameter_groups)
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    assert {"16 · L3", "16 · W3", "18 · L1", "18 · W1"} <= labels
    assert not {label for label in labels if "Lw" in label or "Ww" in label}
    geometry = window._use_case.calculator.calculate(window._build_config())
    elements = {e.element_id: e for e in geometry.elements}
    assert elements["Ww3"].title == "16 · Radial Stub line"
    assert [p.label for p in elements["Ww3"].parameters] == ["W3", "L3"]
    assert elements["Ww1"].title == "18 · Выходная линия"
    assert [p.label for p in elements["Ww1"].parameters] == ["W1", "L1"]


@pytest.mark.parametrize(
    "ctrl",
    # Windows Ctrl, and macOS Control which Qt reports as Meta.
    [QtCore.Qt.KeyboardModifier.ControlModifier, QtCore.Qt.KeyboardModifier.MetaModifier],
)
def test_issue_10_keyboard_moves_between_fields_and_blocks(parameter_window: MainWindow, ctrl) -> None:
    """GitHub #10: Ctrl+↓/↑ next/previous field, Ctrl+Tab next block, Alt+↑/↓ coarse step."""
    window, inputs = parameter_window, parameter_window._config_inputs
    alt = QtCore.Qt.KeyboardModifier.AltModifier
    focused = QtWidgets.QApplication.focusWidget

    def press(spin, key, modifiers=QtCore.Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(spin.lineEdit(), key, modifiers)
        QtWidgets.QApplication.processEvents()

    def field_name():
        widget = focused()
        return next(name for name, spin in inputs.items() if widget in (spin, spin.lineEdit()))

    start = inputs["mex02_3_width_m"]
    window._focus_field(start)
    press(start, QtCore.Qt.Key.Key_Down, ctrl)
    assert field_name() == "mex02_3_length_m"
    press(inputs["mex02_3_length_m"], QtCore.Qt.Key.Key_Down, ctrl)
    assert field_name() == "corner_left_w1_m"  # into the next block, like Tab
    press(inputs["corner_left_w1_m"], QtCore.Qt.Key.Key_Up, ctrl)
    assert field_name() == "mex02_3_length_m"
    assert inputs["mex02_3_length_m"].lineEdit().selectedText() == inputs["mex02_3_length_m"].text()

    # Ctrl+Tab: the first field of the next block; Ctrl+Shift+Tab: previous block.
    press(inputs["mex02_3_length_m"], QtCore.Qt.Key.Key_Tab, ctrl)
    assert field_name() == "corner_left_w1_m"
    press(inputs["corner_left_w1_m"], QtCore.Qt.Key.Key_Tab, ctrl)
    assert field_name() == "w_slot_m"
    press(inputs["w_slot_m"], QtCore.Qt.Key.Key_Backtab, ctrl | QtCore.Qt.KeyboardModifier.ShiftModifier)
    assert field_name() == "corner_left_w1_m"
    # A collapsed block opens when it is reached.
    window._parameter_groups["8 · DC block"].setChecked(False)
    press(inputs["corner_left_w1_m"], QtCore.Qt.Key.Key_Tab, ctrl)
    assert field_name() == "w_slot_m" and window._parameter_groups["8 · DC block"].isChecked()

    # Plain arrows keep the fine step; Alt gives the coarse ×10 step.
    spin = inputs["w_slot_m"]
    before = spin.value()
    press(spin, QtCore.Qt.Key.Key_Up)
    assert spin.value() == pytest.approx(before + spin.singleStep())
    press(spin, QtCore.Qt.Key.Key_Up, alt)
    assert spin.value() == pytest.approx(before + 11 * spin.singleStep())
    press(spin, QtCore.Qt.Key.Key_Down, alt)
    assert spin.value() == pytest.approx(before + spin.singleStep())
    assert field_name() == "w_slot_m"  # Alt never moves the focus


def test_preview_rejects_nonpositive_corrected_dc_slot(parameter_window: MainWindow) -> None:
    parameter_window._config_inputs["w_slot_m"].setValue(0.1)
    parameter_window._config_inputs["dw_m"].setValue(0.5)

    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        parameter_window._update_svg()

    warning.assert_called_once()
    assert "w_slot_m must be > dw_m" in warning.call_args.args[2]


def test_open_file_menu_imports_hfss_and_experiment(parameter_window: MainWindow, tmp_path) -> None:
    assert [action.text() for action in parameter_window.open_files_menu.actions()] == [
        "Параметры smcapp",
        "HFSS",
        "Experiment",
    ]
    hint = parameter_window.findChild(QtWidgets.QLabel, "parameter_file_hint")
    load_button = parameter_window.findChild(QtWidgets.QPushButton, "load_parameters_button")
    save_button = parameter_window.findChild(QtWidgets.QPushButton, "save_parameters_button")
    assert hint is not None and "не файл Mathcad" in hint.text()
    assert load_button is not None and ".mcd/.mcdx не поддерживаются" in load_button.toolTip()
    assert save_button is not None and "кривая S21" in save_button.toolTip()
    hfss = tmp_path / "hfss.tab"
    experiment = tmp_path / "experiment.txt"
    hfss.write_text('"Freq [THz]"\t"dB(S(2,1)) []"\n0.1\t-12\n0.11\t-9\n', encoding="utf-8")
    experiment.write_text("100 -13\n110 -10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Неизвестный тип"):
        parameter_window.load_comparison_trace("Touchstone", hfss)
    parameter_window.load_comparison_trace("HFSS", hfss)
    parameter_window.load_comparison_trace("Experiment", experiment)
    parameter_window._update_s21_plot([100.0, 110.0], [-11.5, -9.5])

    assert set(parameter_window._comparison_traces) == {"HFSS", "Experiment"}
    # GitHub #11 (WP-040): HFSS frequencies arrive in THz and are shown in GHz.
    assert parameter_window._comparison_traces["HFSS"].frequencies == pytest.approx((100.0, 110.0))
    assert len(parameter_window._plot.listDataItems()) == 3
    legend_labels = {label.text for _, label in parameter_window._plot_legend.items}
    # GitHub #11: the current calculation is "SMC", the experiment "exp".
    assert legend_labels == {"SMC", "HFSS", "exp"}


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
    config = S21Config()
    assert groups == [slot.group for slot in config.element_slots()]
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    fields = config.ui_fields()
    correction = next(info for info in fields if info.name == "dw_m")
    assert correction.element_id is None and correction.group == "General"
    assert {info.element_id for info in fields if info.element_id} == set(element_order(config))
    for info in fields:
        spin = window._config_inputs[info.name]
        assert spin.suffix() == ""
        assert float(spin.lineEdit().text()) == pytest.approx(spin.value())
        if info.suffix:
            assert window._parameter_units[info.name].text()
        if info.element_id:
            assert info.number == element_numbers(config)[info.element_id]
            assert f"{info.number} · {info.label}" in labels
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
        *(
            f"{prefix}_{suffix}"
            for prefix in ("mex01_2", "mex02_1", "mex02_3", "mex03_1", "mex03_3")
            for suffix in ("width_m", "length_m")
        ),
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
    assert window._build_config().ui_value(name) == pytest.approx(value)


@pytest.mark.parametrize("width", [0.1, 9, 500])
def test_sis_feed_width_enter_changes_actual_metal(parameter_window: MainWindow, width) -> None:
    spin = parameter_window._config_inputs["mex4_width_m"]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), str(width))
    QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    config = parameter_window._build_config()
    geometry = IntegratedStructureCalculator().calculate(config)
    feed = next(e for e in geometry.elements if e.element_id == "SIS-line")
    assert feed.auxiliary_rects[0].height == pytest.approx((width + config.dw_m * 1e6) * 2)


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
    assert "f = 120 GHz; S21 = " in parameter_window._plot_hover_label.text()

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
    previous, current = curves["prev"], curves["SMC"]
    assert previous.zValue() < current.zValue()
    assert previous.opts["pen"].color().name() == THEME_COLORS[parameter_window.theme].prev_curve
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
    assert line.pen.color().name() == THEME_COLORS[parameter_window.theme].threshold_line
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
    with patch("smcapp.ui.app.QThread"), patch("smcapp.ui.app.S21Worker"):
        parameter_window._run_s21()
        assert parameter_window._theory_trace == ([100, 200], [-10, -6])
        assert parameter_window._previous_theory_trace == ([100, 200], [-12, -8])
        assert len(parameter_window._plot.listDataItems()) == 2
        parameter_window._on_s21_thread_finished()


def test_issue_7_element_labels(parameter_window: MainWindow) -> None:
    assert "8 · DC block" in parameter_window._parameter_groups
    assert "DC Break" not in parameter_window._parameter_groups
    # dw — width step in µm (the issue's "n"), n — number of slices (owner's request).
    assert parameter_window._transformer_status["mex01_1"].text().startswith("dw=5 µm; n=8; dl=1.2 µm")
    parameter_window._config_inputs["mex01_1_w1_m"].setValue(15)
    assert "ступеней" not in parameter_window._transformer_status["mex01_1"].text()


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


def test_explanations_toggle_adds_only_the_dimension_cards(parameter_window: MainWindow) -> None:
    """GitHub #10: «Пояснения»; numbers, SIS and 50 Ω stay on the drawing either way."""
    toggle = parameter_window.findChild(QtWidgets.QCheckBox, "schematic_details")
    assert toggle is not None and toggle.text() == "Пояснения"
    assert "Номера элементов" in toggle.toolTip()
    view, shown = parameter_window._view, []
    set_svg = view.set_svg

    def record(svg: str, **kwargs) -> None:
        shown.append(svg)
        set_svg(svg, **kwargs)

    with patch.object(view, "set_svg", side_effect=record):
        QTest.mouseClick(toggle, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, toggle.height() // 2))
        QTest.mouseClick(toggle, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, toggle.height() // 2))
    detailed, plain = shown
    for svg in (plain, detailed):
        for text in [str(number) for number in range(1, 19)] + ["SIS", "50 Ω"]:
            assert f">{text}</text>" in svg
        assert svg.count('marker-end="url(#leader-arrow)"') == 19
    assert "Размеры элементов" in detailed and "Размеры элементов" not in plain


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
    _enter_value(parameter_window, "mex01_2_width_m", 90)
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


def test_issue_10_zoomed_drawing_does_not_creep_when_values_toggle(parameter_window: MainWindow) -> None:
    """GitHub #10: 9 → 10 → 9 … must not move the drawing; the signal input stays put."""
    from smcapp.infrastructure.geometry import SIGNAL_INPUT

    window, view = parameter_window, parameter_window._view
    _enter_value(window, "corner_left_w1_m", 2)
    _enter_value(window, "corner_left_w2_m", 9)
    _enter_value(window, "corner_left_length_m", 12)
    for _ in range(20):
        QtWidgets.QApplication.sendEvent(view.viewport(), _wheel_event(view.viewport()))
    t4 = next(
        e for e in window._use_case.calculator.calculate(window._build_config()).elements if e.element_id == "T2.C"
    )
    corner = QtCore.QPointF(t4.bounds.x, t4.bounds.y)
    view.centerOn(view._svg_to_scene(corner))
    QtWidgets.QApplication.processEvents()
    anchor = QtCore.QPointF(SIGNAL_INPUT.x, SIGNAL_INPUT.y)

    def pixel(point: QtCore.QPointF) -> tuple[int, int]:
        position = view.mapFromScene(view._svg_to_scene(point))
        return position.x(), position.y()

    start = pixel(anchor), pixel(corner)
    for value in (10, 9) * 6:
        _enter_value(window, "corner_left_w2_m", value)
        assert pixel(anchor) == start[0]
    assert pixel(corner) == start[1]

    # A pan by the user is kept: the new place is the one held from then on.
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() - 37)
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 11)
    panned = pixel(anchor)
    assert panned != start[0]
    for value in (10, 9) * 3:
        _enter_value(window, "corner_left_w2_m", value)
        assert pixel(anchor) == panned


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
    for name in ("w_slot_m", "l_slot_m", "sis_width_um", "radial_r_min_m", "mex01_1_length_m", "mex01_2_width_m"):
        assert inputs[name].singleStep() == 0.5
    sigma = inputs["sigma0_top"]
    assert sigma.value() == 18.0
    assert parameter_window._engineering_orders["sigma0_top"].text() == "1/(Ω·µm)"
    for text, expected in (("0,975", 975000), ("18.125", 18125000), ("0.975000", 975000)):
        sigma.lineEdit().selectAll()
        QTest.keyClicks(sigma.lineEdit(), text)
        QTest.keyClick(sigma.lineEdit(), QtCore.Qt.Key_Return)
        config = parameter_window._build_config()
        assert config.sigma0_top == pytest.approx(expected)
        assert config.sigma0_bot == pytest.approx(expected)


def test_issue_6_order_conversion_and_invalid_length(parameter_window: MainWindow) -> None:
    groups = [name for name in parameter_window._parameter_groups if " · " in name]
    assert [int(name.split()[0]) for name in groups] == list(range(1, 19))
    inputs = parameter_window._config_inputs
    assert "mex01_1_n_um" not in inputs
    assert inputs["mex01_1_w1_m"].value() == 14  # W1 on the drawing's left
    assert inputs["mex01_1_w2_m"].value() == 49  # W2 on the right
    original = parameter_window._build_config().element("mex01_1")
    assert original.n_um == 5
    assert original.dl_m == 1.2e-6

    inputs["mex01_1_w1_m"].setValue(18)
    inputs["mex01_1_w2_m"].setValue(6)
    inputs["mex01_1_length_m"].setValue(7)
    converted = parameter_window._build_config().element("mex01_1")
    assert converted.w1_m == pytest.approx(18e-6)
    assert converted.w2_m == pytest.approx(6e-6)
    assert converted.n_um == 2
    assert converted.dl_m == pytest.approx(1e-6)
    assert parameter_window._transformer_status["mex01_1"].text() == "dw=2 µm; n=7; dl=1 µm"
    inputs["mex01_1_length_m"].setValue(100)
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        parameter_window._update_svg()
    assert "Элемент 1" in warning.call_args.args[2]
    assert "нет целого dw" in parameter_window._transformer_status["mex01_1"].text()


def test_issue_10_corner_transformers_accept_dl_up_to_3_um(parameter_window: MainWindow) -> None:
    """GitHub #10: 7 and 9 choose dl in 0.5…3 µm, the other transformers keep 1.5 µm."""
    inputs = parameter_window._config_inputs
    status = parameter_window._transformer_status
    for prefix in ("corner_left", "corner_right", "mex02_2"):  # elements 7, 9 and, for comparison, 5
        inputs[f"{prefix}_w1_m"].setValue(8)
        inputs[f"{prefix}_w2_m"].setValue(10)
        inputs[f"{prefix}_length_m"].setValue(4.5)
    config = parameter_window._build_config()
    for prefix in ("corner_left", "corner_right"):
        assert status[prefix].text() == "dw=2 µm; n=2; dl=2.25 µm"
        assert config.element(prefix).n_um == 2
        assert config.element(prefix).dl_m == pytest.approx(2.25e-6)
    assert status["mex02_2"].text() == "dw=1 µm; n=3; dl=1.5 µm"

    inputs["mex02_2_length_m"].setValue(9)
    assert "dl от 0.5 до 1.5 µm" in status["mex02_2"].text()
    inputs["mex02_2_length_m"].setValue(4.5)
    inputs["corner_left_length_m"].setValue(12)
    assert "dl от 0.5 до 3 µm" in status["corner_left"].text()
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        parameter_window._update_svg()
    assert "Элемент 7" in warning.call_args.args[2]


def test_preview_button_uses_current_fields_for_dimensions(parameter_window: MainWindow) -> None:
    window = parameter_window
    window._schematic_details.setChecked(True)
    inputs = window._config_inputs
    for name, value in {
        "mex03_4_w1_m": 22,
        "mex03_4_w2_m": 8,
        "mex03_4_length_m": 8,
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
        "L1=12 µm; W1=9 µm; L2=3 µm; W2=6 µm",
        "W1эфф=9.75",
        "Wb (расч.)=25 µm",
    ):
        assert expected in svg
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    # One element of the Mathcad sheet (L4, W4) split by the SIS into two halves.
    assert {"14 · L1 · L4/2", "14 · W1 · W4", "14 · L2 · L4/2", "14 · W2 · W4"} <= labels
    assert "14 · Линия SIS" in window._parameter_groups


def test_legacy_transformer_round_trip_preserves_discretization(parameter_window: MainWindow, tmp_path) -> None:
    from smcapp.domain.s21_models import S21Config

    legacy = S21Config().with_values(mex01_1_n_um=1.7, mex01_1_dl_m=0.125e-6, mex01_1_w2_m=49.123456e-6)
    source = tmp_path / "legacy.smcdesign"
    destination = tmp_path / "saved.smcdesign"
    parameter_window._design_files.save(source, legacy)
    parameter_window.load_design_from_path(source)
    parameter_window.save_design_to_path(destination)
    saved = parameter_window._design_files.load(destination)
    for prefix in saved.element_prefixes():
        assert saved.element(prefix) == legacy.element(prefix)


def test_s21_output_filename_folder_and_worker(parameter_window: MainWindow, tmp_path) -> None:
    from smcapp.api.io import IOService
    from smcapp.domain.s21_models import S21Result
    from smcapp.ui.app import _default_s21_output_directory

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


@pytest.mark.parametrize(
    "selected_filter, suffix", [("Параметры smcapp (*.smcdesign)", ".smcdesign"), ("JSON (*.json)", ".json")]
)
def test_save_dialog_uses_new_format_and_selected_extension(
    parameter_window, tmp_path, selected_filter, suffix
) -> None:
    target = tmp_path / "parameters"
    button = parameter_window.findChild(QtWidgets.QPushButton, "save_parameters_button")
    with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(target), selected_filter)) as dialog:
        QTest.mouseClick(button, QtCore.Qt.LeftButton)
    assert dialog.call_args.args[2].endswith("parameters.smcdesign")
    assert "*.aocdesign" not in dialog.call_args.args[3]
    payload = json.loads(target.with_suffix(suffix).read_text())
    assert payload["format"] == "SMCapp Design"
    assert payload["version"] == 2
    assert DesignFileService().load(target.with_suffix(suffix)) == parameter_window._build_config()
    assert parameter_window.windowTitle().startswith("smcapp ")


@pytest.mark.parametrize("suffix", [".aocdesign", ".aocapp", ".json", ".smcdesign"])
def test_open_dialog_accepts_legacy_and_new_files(parameter_window, tmp_path, suffix) -> None:
    target = tmp_path / f"parameters{suffix}"
    if suffix == ".smcdesign":  # the current version 2
        payload = json.loads(DesignFileService().save(target, S21Config()).read_text())
    else:  # a version-1 file of the former transf_*/msl_* layout
        payload = json.loads((Path(__file__).parent / "data" / "design_v1_variant.aocdesign").read_text())
    payload["parameters"]["tc_bot_k"] = 8.7
    target.write_text(json.dumps(payload))
    with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(target), "")) as dialog:
        parameter_window.open_files_menu.actions()[0].trigger()
    assert f"*{suffix}" in dialog.call_args.args[3]
    assert parameter_window._build_config().tc_bot_k == 8.7


def test_invalid_design_dialog_preserves_parameters(parameter_window, tmp_path) -> None:
    target = tmp_path / "broken.smcdesign"
    target.write_text("{ broken JSON")
    original = parameter_window._build_config()
    with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(target), "")), patch.object(
        QtWidgets.QMessageBox, "critical"
    ) as error:
        parameter_window._load_design_dialog()
    assert "некорректный JSON" in error.call_args.args[2]
    assert parameter_window._build_config() == original
