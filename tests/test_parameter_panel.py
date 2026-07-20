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
