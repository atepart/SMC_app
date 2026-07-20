"""Integration checks for safe, collapsible and persistent parameters."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow


@pytest.fixture
def parameter_window() -> MainWindow:
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
    spin = parameter_window._config_inputs["block_center_length_um"]
    original = spin.value()

    app.sendEvent(spin, _wheel_event(spin))
    assert spin.value() == original

    QTest.mouseClick(spin, QtCore.Qt.MouseButton.LeftButton, pos=spin.rect().center())
    app.sendEvent(spin, _wheel_event(spin))
    assert spin.value() == original + spin.singleStep()

    group = parameter_window._parameter_groups["Dielectrics"]
    group.setChecked(False)
    app.processEvents()
    assert not group.content.isVisible()
    assert not parameter_window.parameters_scroll.isAncestorOf(parameter_window.actions_box)


def test_greek_labels_fixed_orders_and_design_round_trip(parameter_window: MainWindow, tmp_path) -> None:
    labels = {label.text() for label in parameter_window.findChildren(QtWidgets.QLabel)}
    assert {"α EL1", "σ EL1", "ε₁₂"} <= labels

    order = parameter_window._engineering_orders["d_top_m"]
    assert order.isReadOnly()
    assert order.text() == "×10^-6 m"
    assert int(order.text().split("^")[1].split()[0]) % 3 == 0

    path = tmp_path / "round-trip.aocdesign"
    parameter_window._same_materials_checkbox.setChecked(False)
    parameter_window._config_inputs["tc_bot_k"].setValue(8.7)
    parameter_window._config_inputs["block_center_length_um"].setValue(42.5)
    parameter_window.save_design_to_path(path)

    parameter_window._config_inputs["tc_bot_k"].setValue(7.0)
    parameter_window._config_inputs["block_center_length_um"].setValue(10.0)
    loaded = parameter_window.load_design_from_path(path)

    assert loaded.tc_bot_k == pytest.approx(8.7)
    assert parameter_window._config_inputs["tc_bot_k"].value() == pytest.approx(8.7)
    assert parameter_window._config_inputs["block_center_length_um"].value() == pytest.approx(42.5)
    assert not parameter_window._same_materials_checkbox.isChecked()


def test_open_file_menu_imports_both_comparison_traces(parameter_window: MainWindow, tmp_path) -> None:
    assert [action.text() for action in parameter_window.open_files_menu.actions()] == [
        "Дизайн",
        "HFSS",
        "Experiment",
    ]
    hfss = tmp_path / "hfss.txt"
    experiment = tmp_path / "experiment.txt"
    hfss.write_text("100 -12\n110 -9\n", encoding="utf-8")
    experiment.write_text("100 -13\n110 -10\n", encoding="utf-8")

    parameter_window.load_comparison_trace("HFSS", hfss)
    parameter_window.load_comparison_trace("Experiment", experiment)
    parameter_window._update_s21_plot([100.0, 110.0], [-11.5, -9.5])

    assert set(parameter_window._comparison_traces) == {"HFSS", "Experiment"}
    assert len(parameter_window._plot.listDataItems()) == 3
    legend_labels = {label.text for _, label in parameter_window._plot_legend.items}
    assert legend_labels == {"Theory", "HFSS", "Experiment"}


def test_plot_home_hover_and_png_export(parameter_window: MainWindow, tmp_path) -> None:
    parameter_window._plot_scale_inputs["x_min"].setValue(95.0)
    parameter_window._plot_scale_inputs["x_max"].setValue(145.0)
    parameter_window._plot_scale_inputs["y_min"].setValue(-25.0)
    parameter_window._plot_scale_inputs["y_max"].setValue(0.0)
    parameter_window._apply_plot_scale()

    x_range, y_range = parameter_window._plot.getPlotItem().vb.viewRange()
    assert x_range == pytest.approx([95.0, 145.0])
    assert y_range == pytest.approx([-25.0, 0.0])

    scene_position = parameter_window._plot.getPlotItem().vb.sceneBoundingRect().center()
    parameter_window._on_plot_mouse_moved(scene_position)
    assert parameter_window._plot_hover_label.isVisible()
    assert "GHz" in parameter_window._plot_hover_label.text()

    destination = tmp_path / "plot.png"
    assert parameter_window.export_plot_to_path(destination) == destination
    assert destination.read_bytes().startswith(b"\x89PNG")
