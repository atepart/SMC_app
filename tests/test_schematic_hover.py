"""GitHub #10 (WP-038): the number of the element under the cursor is highlighted."""

from __future__ import annotations

import gc
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from aocapp.application.s21_use_case import CalculateS21UseCase
from aocapp.application.use_cases import GenerateStructureUseCase
from aocapp.domain.models import Point, StructureGeometry
from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.geometry import IntegratedStructureCalculator
from aocapp.infrastructure.hover import ElementHitMap
from aocapp.infrastructure.svg_renderer import SvgRendererImpl
from aocapp.ui.app import MainWindow
from aocapp.ui.theme import THEME_COLORS, Theme


def _overview(config: S21Config | None = None) -> StructureGeometry:
    geometry = IntegratedStructureCalculator().calculate(config or S21Config())
    assert geometry.overview is not None
    return geometry.overview


def _element(geometry: StructureGeometry, element_id: str):
    return next(element for element in geometry.elements if element.element_id == element_id)


def _inside(geometry: StructureGeometry, element_id: str) -> Point:
    """A point well inside the element's metal, away from the SIS symbol."""
    element = _element(geometry, element_id)
    if element_id == "Radial":
        # On the axis of the upper fan, halfway up.
        return Point(element.bounds.x + element.bounds.width / 2, element.bounds.y + element.bounds.height / 4)
    if element_id in {"DC", "SIS-line"}:
        # First stub of the DC block; the left end of the first part of 14.
        polygon = element.polygon[:4]
        xs, ys = [p.x for p in polygon], [p.y for p in polygon]
        if element_id == "SIS-line":
            return Point(min(xs) + 0.5, (min(ys) + max(ys)) / 2)
        return Point((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    # The vertex average lies inside these convex contours.
    polygon = element.polygon
    return Point(sum(p.x for p in polygon) / len(polygon), sum(p.y for p in polygon) / len(polygon))


@pytest.mark.parametrize(
    ("element_id", "number"), [("T4", "7"), ("DC", "8"), ("SIS-line", "14"), ("Radial", "17"), ("SIS", "15")]
)
def test_hit_test_finds_the_element_and_its_number(element_id, number) -> None:
    geometry = _overview()
    hit_map = ElementHitMap.from_geometry(geometry)
    point = _inside(geometry, element_id) if element_id != "SIS" else _centre(_element(geometry, "SIS").bounds)
    assert hit_map.element_at(point) == element_id
    mark = hit_map.mark_at(point)
    assert mark is not None and mark.text == number
    callout = next(c for c in geometry.callouts if c.label.text == number)
    assert mark.box.contains(Point(callout.label.position.x, callout.label.position.y - 1))
    assert mark.arrow == callout.arrow


def _centre(rect) -> Point:
    return Point(rect.x + rect.width / 2, rect.y + rect.height / 2)


def test_hit_test_ignores_empty_places_and_the_port() -> None:
    geometry = _overview()
    hit_map = ElementHitMap.from_geometry(geometry)
    line_4 = _element(geometry, "MSL7").bounds
    # Below line 4 (no metal), far outside the drawing, inside the DC-block U
    # between its stubs, and on the 50 Ω port.
    stub_left, stub_right = _element(geometry, "DC").polygon[:4], _element(geometry, "DC").polygon[4:8]
    between = Point((max(p.x for p in stub_left) + min(p.x for p in stub_right)) / 2, 30)
    port = Point(geometry.bounds.x + geometry.bounds.width - 40, 0)
    for point in (Point(_centre(line_4).x, line_4.bottom + 15), Point(-500, -500), between, port):
        assert hit_map.element_at(point) is None
        assert hit_map.mark_at(point) is None


def test_hit_test_tolerance_catches_thin_lines_and_labels_count() -> None:
    geometry = _overview()
    hit_map = ElementHitMap.from_geometry(geometry)
    line_6 = _element(geometry, "MSL6").bounds
    above = Point(_centre(line_6).x, line_6.y - 2)
    assert hit_map.element_at(above) is None
    assert hit_map.element_at(above, tolerance=3) == "MSL6"
    # The number label itself and the "SIS" label count as their elements.
    eight = next(c for c in geometry.callouts if c.label.text == "8").label.position
    assert hit_map.element_at(Point(eight.x, eight.y - 2)) == "DC"
    sis = next(c for c in geometry.callouts if c.label.text == "SIS").label.position
    mark = hit_map.mark_at(Point(sis.x, sis.y - 2))
    assert mark is not None and mark.text == "15"


def test_hit_areas_cover_every_numbered_element() -> None:
    geometry = _overview()
    owners = {element_id for element_id, _points in geometry.hit_areas}
    assert owners == {element.element_id for element in geometry.elements}
    full = IntegratedStructureCalculator().calculate(S21Config())
    assert full.hit_areas == geometry.hit_areas


@pytest.fixture
def window() -> MainWindow:
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
    app.processEvents()


def _move(view, svg_point: Point) -> QtCore.QPointF:
    position = QtCore.QPointF(view.mapFromScene(view._svg_to_scene(QtCore.QPointF(svg_point.x, svg_point.y))))
    assert view.viewport().rect().contains(position.toPoint())
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        position,
        QtCore.QPointF(view.viewport().mapToGlobal(position.toPoint())),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(view.viewport(), event)
    return position


def _plate_centre(view) -> QtCore.QPointF:
    plate, _arrow = view.highlight_items
    return view._scene_to_svg(plate.sceneBoundingRect().center())


def _assert_highlight_at(view, geometry: StructureGeometry, number: str) -> None:
    plate, arrow = view.highlight_items
    assert plate.isVisible() and arrow.isVisible()
    label = next(c for c in geometry.callouts if c.label.text == number).label
    centre = _plate_centre(view)
    # The plate is centred on the number (cap-height box above the baseline).
    assert centre.x() == pytest.approx(label.position.x, abs=1.0)
    assert centre.y() == pytest.approx(label.position.y - 0.36 * label.font_size, abs=1.0)
    assert plate.zValue() > 0 and arrow.zValue() > 0


def _enter_value(window: MainWindow, name: str, value: float) -> None:
    spin = window._config_inputs[name]
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), f"{value:g}")
    QTest.keyClick(spin.lineEdit(), QtCore.Qt.Key_Return)
    QtWidgets.QApplication.processEvents()


def test_mouse_move_highlights_the_number_and_leave_hides_it(window: MainWindow) -> None:
    view = window._view
    geometry = _overview(window._build_config())
    plate, arrow = view.highlight_items
    assert not plate.isVisible() and not arrow.isVisible()
    _move(view, _inside(geometry, "T4"))
    assert view.hovered_element == "T4"
    _assert_highlight_at(view, geometry, "7")
    assert plate.brush().color().name() == THEME_COLORS[window.theme].schematic_highlight
    _move(view, _inside(geometry, "Radial"))
    assert view.hovered_element == "Radial"
    _assert_highlight_at(view, geometry, "17")
    # Away from every element: no highlight.
    line_4 = _element(geometry, "MSL7").bounds
    _move(view, Point(_centre(line_4).x, line_4.bottom + 15))
    assert view.hovered_element is None
    assert not plate.isVisible() and not arrow.isVisible()
    _move(view, _inside(geometry, "DC"))
    _assert_highlight_at(view, geometry, "8")
    QtWidgets.QApplication.sendEvent(view.viewport(), QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert view.hovered_element is None
    assert not plate.isVisible() and not arrow.isVisible()


def test_highlight_survives_redraw_theme_and_explanations(window: MainWindow) -> None:
    view = window._view
    wheel = QtGui.QWheelEvent(
        QtCore.QPointF(view.viewport().rect().center()),
        QtCore.QPointF(view.mapToGlobal(view.rect().center())),
        QtCore.QPoint(),
        QtCore.QPoint(0, 120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    for _ in range(10):
        QtWidgets.QApplication.sendEvent(view.viewport(), wheel)
    geometry = _overview(window._build_config())
    target = _inside(geometry, "SIS-line")
    view.centerOn(view._svg_to_scene(QtCore.QPointF(target.x, target.y)))
    QtWidgets.QApplication.processEvents()
    _move(view, target)
    assert view.hovered_element == "SIS-line"
    _assert_highlight_at(view, geometry, "14")
    old_plate = view.highlight_items[0]
    # A longer output line redraws the sheet; the zoomed SIS stays under the
    # still cursor and keeps its highlight on the new overlay items.
    _enter_value(window, "zrad1_len_m", 80)
    geometry = _overview(window._build_config())
    assert view.highlight_items[0] is not old_plate
    assert view.hovered_element == "SIS-line"
    _assert_highlight_at(view, geometry, "14")
    window.set_theme(Theme.DARK)
    QtWidgets.QApplication.processEvents()
    assert view.hovered_element == "SIS-line"
    _assert_highlight_at(view, geometry, "14")
    assert view.highlight_items[0].brush().color().name() == THEME_COLORS[Theme.DARK].schematic_highlight
    # «Пояснения» show the same numbers above the dimension cards.
    toggle = window.findChild(QtWidgets.QCheckBox, "schematic_details")
    toggle.setChecked(True)
    QtWidgets.QApplication.processEvents()
    full = IntegratedStructureCalculator().calculate(window._build_config())
    _move(view, _inside(full, "T4"))
    assert view.hovered_element == "T4"
    _assert_highlight_at(view, full, "7")
    QtWidgets.QApplication.sendEvent(view.viewport(), QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert not view.highlight_items[0].isVisible()
