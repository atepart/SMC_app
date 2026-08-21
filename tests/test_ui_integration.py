"""Integration checks for the real Qt main window."""

from __future__ import annotations

import os
from pathlib import Path
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
    window._update_s21_plot([100.0, 300.0, 500.0, 700.0, 900.0], [-18.0, -8.0, -4.0, -7.0, -15.0])
    window._parameter_groups["LO"].setChecked(False)
    window._parameter_groups["Backend Grid"].setChecked(False)
    view_box = window._plot.getPlotItem().vb
    scene_position = view_box.mapToScene(view_box.boundingRect().center())
    window._on_plot_mouse_moved(scene_position)
    app.processEvents()

    artifact_dir = os.environ.get("AOC_UI_ARTIFACT_DIR")
    if artifact_dir:
        screenshot_dir = Path(artifact_dir)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / "issue-4-interface.png"
    else:
        screenshot_path = tmp_path / "main-window.png"
    assert window.grab().save(str(screenshot_path))
    assert screenshot_path.stat().st_size > 0

    window.close()
