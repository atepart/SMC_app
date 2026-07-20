"""Integration checks for the real Qt main window."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow


def test_main_window_supports_material_toggle_and_preview_refresh(tmp_path) -> None:
    QSettings().clear()
    app = QApplication.instance() or QApplication([])
    use_case = GenerateStructureUseCase(
        calculator=IntegratedStructureCalculator(),
        renderer=SvgRendererImpl(),
    )
    window = MainWindow(
        use_case=use_case,
        s21_use_case=cast(CalculateS21UseCase, Mock()),
    )
    window.resize(1440, 920)
    window.show()
    app.processEvents()

    checkbox = window._same_materials_checkbox
    assert checkbox is not None
    assert checkbox.isChecked()
    assert not window._config_inputs["tc_bot_k"].isEnabled()

    QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(8, checkbox.rect().center().y()))

    assert not checkbox.isChecked()
    assert window._config_inputs["tc_bot_k"].isEnabled()

    preview_button = next(button for button in window.findChildren(QPushButton) if button.text() == "Update Preview")
    scroll = window.parameters_dock.findChild(QScrollArea)
    assert scroll is not None
    scroll.ensureWidgetVisible(preview_button)
    app.processEvents()
    QTest.mouseClick(preview_button, Qt.LeftButton, pos=preview_button.rect().center())
    app.processEvents()

    assert window._view._svg_item is not None
    screenshot_path = tmp_path / "main-window.png"
    assert window.grab().save(str(screenshot_path))
    assert screenshot_path.stat().st_size > 0

    window.close()
