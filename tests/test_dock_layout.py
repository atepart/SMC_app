"""QtAds workspace regression tests modelled after RnSApp."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtWidgets
from PySide6QtAds import CDockWidget

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import CURRENT_DOCK_LAYOUT_VERSION, MainWindow


def _make_window() -> MainWindow:
    use_case = GenerateStructureUseCase(
        calculator=IntegratedStructureCalculator(),
        renderer=SvgRendererImpl(),
    )
    return MainWindow(
        use_case=use_case,
        s21_use_case=cast(CalculateS21UseCase, Mock()),
    )


@pytest.fixture
def dock_window() -> MainWindow:
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = _make_window()
    window.resize(1440, 920)
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
    app.processEvents()


def test_default_workspace_has_expected_panels_and_splitter_ratio(dock_window: MainWindow) -> None:
    assert [dock.windowTitle() for dock in dock_window.dock_widgets] == [
        "Параметры",
        "Схема",
        "График",
        "Лог расчёта",
    ]
    for dock in dock_window.dock_widgets:
        assert dock.features() & CDockWidget.DockWidgetFeature.DockWidgetClosable
        assert not dock.features() & CDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert not dock.features() & CDockWidget.DockWidgetFeature.DockWidgetPinnable

    root_sizes = dock_window.dock_manager.dockContainers()[0].rootSplitter().sizes()
    assert len(root_sizes) == 2
    assert root_sizes[1] > root_sizes[0]

    item = dock_window._view._svg_item
    assert item is not None
    visible_drawing = dock_window._view.transform().mapRect(item.boundingRect())
    assert visible_drawing.width() > dock_window._view.viewport().width() * 0.5


def test_widget_menu_and_restore_reopen_closed_panel(dock_window: MainWindow) -> None:
    app = QtWidgets.QApplication.instance()
    assert app is not None
    dock_window.plot_dock.toggleView(False)
    app.processEvents()
    assert dock_window.plot_dock.isClosed()

    dock_window._refresh_dock_widgets_menu()
    actions = {action.text(): action for action in dock_window.dock_widgets_menu.actions()}
    assert not actions["График"].isChecked()
    assert actions["Схема"].isChecked()

    dock_window.restore_default_layout()
    app.processEvents()
    assert not dock_window.plot_dock.isClosed()


def test_current_layout_is_persisted_and_stale_version_is_ignored(dock_window: MainWindow) -> None:
    app = QtWidgets.QApplication.instance()
    assert app is not None
    dock_window.log_dock.toggleView(False)
    dock_window.save_settings()

    settings = QtCore.QSettings()
    settings.beginGroup("DockManager")
    assert settings.value("layout_version", type=int) == CURRENT_DOCK_LAYOUT_VERSION
    assert settings.value("state")
    settings.endGroup()

    # Re-open the panel without saving the new state, then prove that the
    # persisted layout can be applied to the already constructed workspace.
    # Keeping one QtAds manager per test also mirrors the real application
    # lifecycle and avoids double-destruction of native dock containers.
    dock_window.log_dock.toggleView(True)
    app.processEvents()
    assert not dock_window.log_dock.isClosed()
    assert dock_window.restore_settings()
    app.processEvents()
    assert dock_window.log_dock.isClosed()

    settings.beginGroup("DockManager")
    settings.setValue("layout_version", CURRENT_DOCK_LAYOUT_VERSION - 1)
    settings.endGroup()
    dock_window.log_dock.toggleView(True)
    app.processEvents()
    assert not dock_window.restore_settings()
    assert not dock_window.log_dock.isClosed()
