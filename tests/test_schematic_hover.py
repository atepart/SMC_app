"""GitHub #10 (WP-038): the number of the element under the cursor is highlighted."""

from __future__ import annotations

import contextlib
import gc
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from smcapp.application.s21_use_case import CalculateS21UseCase
from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.domain.models import Point, StructureGeometry
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.hover import ElementHitMap
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow
from smcapp.ui.theme import THEME_COLORS, Theme


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
            # Halfway between the line's left end and the SIS circle: a theme
            # switch may move the view by a few pixels (scroll bars, borders).
            sis = _element(geometry, "SIS").bounds
            return Point((min(xs) + sis.x) / 2, (min(ys) + max(ys)) / 2)
        return Point((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    # The vertex average lies inside these convex contours.
    polygon = element.polygon
    return Point(sum(p.x for p in polygon) / len(polygon), sum(p.y for p in polygon) / len(polygon))


@pytest.mark.parametrize(
    ("element_id", "number"), [("T2.C", "7"), ("DC", "8"), ("SIS-line", "14"), ("Radial", "17"), ("SIS", "15")]
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
    line_4 = _element(geometry, "MSL2.1").bounds
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
    line_6 = _element(geometry, "MSL2.3").bounds
    above = Point(_centre(line_6).x, line_6.y - 2)
    assert hit_map.element_at(above) is None
    assert hit_map.element_at(above, tolerance=3) == "MSL2.3"
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
    _move(view, _inside(geometry, "T2.C"))
    assert view.hovered_element == "T2.C"
    _assert_highlight_at(view, geometry, "7")
    assert plate.brush().color().name() == THEME_COLORS[window.theme].schematic_highlight
    _move(view, _inside(geometry, "Radial"))
    assert view.hovered_element == "Radial"
    _assert_highlight_at(view, geometry, "17")
    # Away from every element: no highlight.
    line_4 = _element(geometry, "MSL2.1").bounds
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
    _move(view, _inside(full, "T2.C"))
    assert view.hovered_element == "T2.C"
    _assert_highlight_at(view, full, "7")
    QtWidgets.QApplication.sendEvent(view.viewport(), QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert not view.highlight_items[0].isVisible()


# WP-062: a click on an element opens its parameter group --------------------


def _click(view, svg_point: Point, drag_px: float = 0.0) -> None:
    """Press on *svg_point* and release *drag_px* to the right of it."""
    press = _move(view, svg_point)
    release = press + QtCore.QPointF(drag_px, 0)
    for kind, position in (
        (QtCore.QEvent.Type.MouseButtonPress, press),
        (QtCore.QEvent.Type.MouseButtonRelease, release),
    ):
        event = QtGui.QMouseEvent(
            kind,
            position,
            QtCore.QPointF(view.viewport().mapToGlobal(position.toPoint())),
            QtCore.Qt.MouseButton.LeftButton,
            (
                QtCore.Qt.MouseButton.LeftButton
                if kind == QtCore.QEvent.Type.MouseButtonPress
                else QtCore.Qt.MouseButton.NoButton
            ),
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(view.viewport(), event)
    QtWidgets.QApplication.processEvents()


def _target(geometry: StructureGeometry, element_id: str) -> Point:
    """A point the hit test gives to *element_id*: its metal, else a grid point of its contours."""
    hit_map = ElementHitMap.from_geometry(geometry)
    with contextlib.suppress(ZeroDivisionError, StopIteration):
        point = _inside(geometry, element_id)
        if hit_map.element_at(point) == element_id:
            return point
    for owner, points in geometry.hit_areas:
        if owner != element_id:
            continue
        xs, ys = [p.x for p in points], [p.y for p in points]
        for i in range(1, 20):
            for j in range(1, 20):
                point = Point(min(xs) + (max(xs) - min(xs)) * i / 20, min(ys) + (max(ys) - min(ys)) * j / 20)
                if hit_map.element_at(point) == element_id:
                    return point
    raise AssertionError(f"no point of {element_id}")


def _group_of(window: MainWindow, element_id: str):
    return next(box for box in window._parameter_groups.values() if box.element_id == element_id)


def _first_field(window: MainWindow, box):
    return next(spins for current, spins in window._parameter_blocks() if current is box)[0]


def _assert_opened(window: MainWindow, element_id: str) -> None:
    box = _group_of(window, element_id)
    assert box.isChecked()
    spin = _first_field(window, box)
    focused = QtWidgets.QApplication.focusWidget()
    assert focused in (spin, spin.lineEdit()), f"{element_id}: focus on {focused!r}"
    assert spin.lineEdit().selectedText() == spin.text()
    # The group header is in the visible part of the panel.
    scroll = window.parameters_scroll
    header = box.toggle_button.mapTo(scroll.viewport(), QtCore.QPoint(0, 0))
    assert 0 <= header.y() < scroll.viewport().height()
    assert window._view.selected_element == element_id


def test_click_on_every_element_opens_its_group_at_the_first_field(window: MainWindow) -> None:
    view = window._view
    window._set_all_groups_expanded(False)
    geometry = _overview(window._build_config())
    hit_map = ElementHitMap.from_geometry(geometry)
    slots = window._build_config().element_slots()
    assert len(slots) == 18
    for slot in slots:
        point = _target(geometry, slot.element_id)
        assert hit_map.element_at(point) == slot.element_id
        _click(view, point)
        _assert_opened(window, slot.element_id)
        assert _group_of(window, slot.element_id).toggle_button.text() == slot.group
    # The clicked element stays highlighted after the cursor leaves the drawing.
    QtWidgets.QApplication.sendEvent(view.viewport(), QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert view.hovered_element is None
    _assert_highlight_at(view, geometry, "18")


def test_click_on_a_number_label_opens_the_element(window: MainWindow) -> None:
    geometry = _overview(window._build_config())
    six = next(c for c in geometry.callouts if c.label.text == "6").label.position
    _click(window._view, Point(six.x, six.y - 2))
    _assert_opened(window, "MSL2.3")


def test_drag_and_background_click_do_not_open_groups(window: MainWindow) -> None:
    view = window._view
    window._set_all_groups_expanded(False)
    geometry = _overview(window._build_config())
    # A hand-drag pan that starts on element 6 is not a click.
    _click(view, _inside(geometry, "MSL2.3"), drag_px=QtWidgets.QApplication.startDragDistance() + 5)
    assert not any(box.isChecked() for box in window._parameter_groups.values())
    assert view.selected_element is None
    # A click on element 6, then on an empty place: nothing opens, the highlight goes.
    _click(view, _inside(geometry, "MSL2.3"))
    _assert_opened(window, "MSL2.3")
    line_4 = _element(geometry, "MSL2.1").bounds
    window._set_all_groups_expanded(False)
    _click(view, Point(_centre(line_4).x, line_4.bottom + 15))
    assert not any(box.isChecked() for box in window._parameter_groups.values())
    assert view.selected_element is None
    QtWidgets.QApplication.sendEvent(view.viewport(), QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert not view.highlight_items[0].isVisible()


def test_typed_value_is_applied_before_the_jump_and_ctrl_down_continues(window: MainWindow) -> None:
    view = window._view
    # The drawing on screen, before the typed value lengthens element 4.
    geometry = _overview(window._build_config())
    spin = window._config_inputs["mex02_1_length_m"]  # element 4
    window._focus_field(spin)
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "37")
    with pytest.MonkeyPatch.context() as patch:
        drawn = []
        patch.setattr(view, "set_svg", lambda *args, **kwargs: drawn.append(kwargs))
        _click(view, _inside(geometry, "MSL2.3"))
    assert len(drawn) == 1  # the typed 37 was applied, as Enter would
    assert window._build_config().mex02[0].length_m == pytest.approx(37e-6)
    _assert_opened(window, "MSL2.3")
    width = window._config_inputs["mex02_3_width_m"]
    QTest.keyClick(width.lineEdit(), QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.ControlModifier)
    QtWidgets.QApplication.processEvents()
    length = window._config_inputs["mex02_3_length_m"]
    assert QtWidgets.QApplication.focusWidget() in (length, length.lineEdit())
    assert view.selected_element == "MSL2.3"  # still inside the clicked element's group
    QTest.keyClick(length.lineEdit(), QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.ControlModifier)
    QtWidgets.QApplication.processEvents()
    assert view.selected_element is None  # left for element 7


def test_click_after_removing_an_element_follows_the_new_numbers(window: MainWindow) -> None:
    window._view.set_selected_element("MSL2.3")
    window.remove_element("MSL1.2")  # element 2
    QtWidgets.QApplication.processEvents()
    assert window._view.selected_element is None
    geometry = _overview(window._build_config())
    slots = {slot.element_id: slot for slot in window._build_config().element_slots()}
    # The former 6 is now 5; clicking it opens «5 · Линия».
    six = next(slot for slot in slots.values() if slot.kind == "line" and slot.number == 5)
    _click(window._view, _inside(geometry, six.element_id))
    _assert_opened(window, six.element_id)
    assert _group_of(window, six.element_id).toggle_button.text() == "5 · Линия"
