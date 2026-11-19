"""Interface scale presets and per-area factors (WP-065, GitHub #13)."""

from __future__ import annotations

import gc
import re
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from smcapp.application.s21_use_case import CalculateS21UseCase
from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.infrastructure.trace_files import ComparisonTrace
from smcapp.ui.app import PARAMETERS_WIDTH_RESERVE, PLOT_DATA_MIN_HEIGHT, MainWindow
from smcapp.ui.theme import Theme, apply_application_theme
from smcapp.ui.ui_scale import (
    AREA_SCALE_STEPS,
    UI_SCALE_PRESETS,
    UiScale,
    apply_application_font,
    base_class_point_sizes,
    base_point_size,
    load_ui_scale,
    save_ui_scale,
)

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _new_window() -> MainWindow:
    window = MainWindow(
        GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()),
        cast(CalculateS21UseCase, Mock()),
    )
    window.resize(1440, 920)
    window.show()
    QtWidgets.QApplication.processEvents()
    return window


def _close(window: MainWindow) -> None:
    window.save_settings = Mock()
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)


@pytest.fixture
def window():
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance()
    window = _new_window()
    yield window
    _close(window)
    apply_application_theme(app, Theme.DEFAULT, ASSETS)
    QtCore.QSettings().clear()
    apply_application_font(UiScale())  # later tests start from the platform font
    app.processEvents()


def _points(css_size: str) -> float:
    match = re.fullmatch(r"([\d.]+)pt", css_size)
    assert match, css_size
    return float(match.group(1))


def _sizes(window: MainWindow) -> dict[str, float]:
    """Point sizes of the scaled texts in every area."""
    QtWidgets.QApplication.processEvents()  # widgets take a new application font from a posted event
    plot_item = window._plot.getPlotItem()
    group = next(iter(window._parameter_groups.values()))
    field = next(widget for widget in group.content.findChildren(QtWidgets.QLabel))
    return {
        "app": QtWidgets.QApplication.font().pointSizeF(),
        "menu": window.menuBar().font().pointSizeF(),
        "log": window._log_view.font().pointSizeF(),
        "group": group.toggle_button.font().pointSizeF(),
        "field": field.font().pointSizeF(),
        "run": window._run_s21_button.font().pointSizeF(),
        "collapse": window.collapse_all_button.font().pointSizeF(),
        "title": _points(plot_item.titleLabel.opts["size"]),
        "axis": _points(plot_item.getAxis("bottom").labelStyle["font-size"]),
        "tick": plot_item.getAxis("left").style["tickFont"].pointSizeF(),
        "legend": _points(window._plot_legend.opts["labelTextSize"]),
        "hover": window._plot_hover_label.font().pointSizeF(),
    }


PARAMETER_TEXTS = ("group", "field", "run", "collapse")
PLOT_TEXTS = ("title", "axis", "tick", "legend", "hover")


def _number_font_sizes(svg: str) -> set[float]:
    """Font sizes of the bold element numbers on the schematic."""
    return {float(size) for size in re.findall(r'font-size="([\d.]+)"[^>]*font-weight="bold"', svg)}


def test_presets_and_steps() -> None:
    assert [title for title, _factor in UI_SCALE_PRESETS.values()] == ["Мелкий", "Обычный", "Крупный", "Максимальный"]
    assert UiScale().preset == "normal" and UiScale().factor == 1.0
    assert UiScale().stepped(1).preset == "large" and UiScale().stepped(-1).preset == "small"
    # The ends stay where they are.
    assert UiScale("max").stepped(1).preset == "max" and UiScale("small").stepped(-1).preset == "small"
    scale = UiScale().with_area("plot", 2.0)
    assert (
        scale.area("plot") == 2.0 and scale.area("parameters") == 1.0 and scale.with_preset("max").area("plot") == 2.0
    )
    with pytest.raises(ValueError, match="Неизвестный масштаб"):
        UiScale().with_preset("huge")
    with pytest.raises(ValueError, match="Неизвестная область"):
        UiScale().with_area("log", 1.5)
    with pytest.raises(ValueError, match="одним из"):
        UiScale().with_area("plot", 3.0)


def test_saved_scale_round_trips_and_garbage_falls_back(tmp_path) -> None:
    settings = QtCore.QSettings(str(tmp_path / "scale.ini"), QtCore.QSettings.Format.IniFormat)
    assert load_ui_scale(settings) == UiScale()
    save_ui_scale(UiScale("large").with_area("schematic", 1.75), settings)
    assert load_ui_scale(settings) == UiScale("large").with_area("schematic", 1.75)
    settings.setValue("View/ui_scale", "huge")
    settings.setValue("View/area_scale/plot", "abc")
    settings.setValue("View/area_scale/parameters", 3.0)
    assert load_ui_scale(settings) == UiScale().with_area("schematic", 1.75)


def test_label_scale_enlarges_the_schematic_numbers() -> None:
    calculator = IntegratedStructureCalculator()
    for scale in AREA_SCALE_STEPS:
        geometry = calculator.calculate(S21Config(), label_scale=scale)
        sizes = {label.text: label.font_size for label in geometry.labels if label.text in {"1", "SIS", "50 Ω"}}
        assert sizes == {"1": 10.0 * scale, "SIS": 11.0 * scale, "50 Ω": 11.0 * scale}
    with pytest.raises(ValueError, match="положительным"):
        calculator.calculate(S21Config(), label_scale=0.0)


@pytest.mark.parametrize("preset", ["small", "large", "max"])
def test_preset_scales_every_text_at_once_and_back(window: MainWindow, preset: str) -> None:
    normal = _sizes(window)
    assert normal["app"] == pytest.approx(base_point_size())
    window.set_ui_scale(preset)
    QtWidgets.QApplication.processEvents()
    factor = UI_SCALE_PRESETS[preset][1]
    scaled = _sizes(window)
    for name, size in normal.items():
        # Sizes are rounded to 0.1 pt.
        assert scaled[name] == pytest.approx(size * factor, abs=0.15), name
    assert window.ui_scale.preset == preset and window._ui_scale_actions[preset].isChecked()
    assert QtCore.QSettings().value("View/ui_scale") == preset
    # Fields under the plot widen with the text.
    assert window._plot_scale_inputs["x_min"].width() == round(90 * factor)
    window.set_ui_scale("normal")
    QtWidgets.QApplication.processEvents()
    assert _sizes(window) == normal


def test_area_factor_enlarges_only_its_area(window: MainWindow) -> None:
    normal = _sizes(window)
    window.set_area_scale("plot", 2.0)
    plot = _sizes(window)
    for name in PLOT_TEXTS:
        assert plot[name] == pytest.approx(normal[name] * 2.0, abs=0.15), name
    for name in ("app", "menu", "log", *PARAMETER_TEXTS):
        assert plot[name] == normal[name], name

    window.set_area_scale("parameters", 1.5)
    both = _sizes(window)
    for name in PARAMETER_TEXTS:
        assert both[name] == pytest.approx(normal[name] * 1.5, abs=0.15), name
    assert both["legend"] == plot["legend"] and both["app"] == normal["app"]
    # The preset multiplies on top of an area factor.
    window.set_ui_scale("large")
    large = _sizes(window)
    assert large["legend"] == pytest.approx(normal["legend"] * 2.0 * 1.25, abs=0.15)
    assert large["group"] == pytest.approx(normal["group"] * 1.5 * 1.25, abs=0.15)
    assert window._area_scale_actions[("plot", 2.0)].isChecked()
    assert window._area_scale_actions[("parameters", 1.5)].isChecked()


def test_schematic_factor_redraws_the_numbers_larger(window: MainWindow, monkeypatch) -> None:
    drawn: list[str] = []
    original = window._view.set_svg
    monkeypatch.setattr(window._view, "set_svg", lambda svg, **kwargs: (drawn.append(svg), original(svg, **kwargs)))
    window.set_area_scale("schematic", 2.0)
    assert drawn and _number_font_sizes(drawn[-1]) == {20.0}
    window.set_area_scale("plot", 1.25)  # another area: the schematic is not redrawn
    assert len(drawn) == 1
    window.set_area_scale("schematic", 1.0)
    assert _number_font_sizes(drawn[-1]) == {10.0}


def test_scale_survives_a_restart(window: MainWindow) -> None:
    window.set_ui_scale("max")
    window.set_area_scale("schematic", 1.5)
    sizes = _sizes(window)
    apply_application_font(UiScale())  # as at a new start: the platform font
    reopened = _new_window()
    try:
        assert reopened.ui_scale == UiScale("max").with_area("schematic", 1.5)
        assert reopened._ui_scale_actions["max"].isChecked()
        assert reopened._area_scale_actions[("schematic", 1.5)].isChecked()
        assert _sizes(reopened) == sizes
    finally:
        _close(reopened)


def test_menu_shortcuts_and_toolbar_button(window: MainWindow) -> None:
    actions = {action.text(): action for action in window.scale_menu.actions()}
    assert [action.toString() for action in actions["Крупнее"].shortcuts()] == ["Ctrl+=", "Ctrl++"]
    assert [action.toString() for action in actions["Мельче"].shortcuts()] == ["Ctrl+-"]
    assert [action.toString() for action in actions["Обычный размер"].shortcuts()] == ["Ctrl+0"]
    assert [area.title() for area in window.scale_menu.findChildren(QtWidgets.QMenu)] == [
        "Панель параметров",
        "График",
        "Номера на схеме",
    ]
    actions["Крупнее"].trigger()
    actions["Крупнее"].trigger()
    assert window.ui_scale.preset == "max"
    actions["Крупнее"].trigger()  # already the largest
    assert window.ui_scale.preset == "max"
    actions["Мельче"].trigger()
    assert window.ui_scale.preset == "large"
    actions["Обычный размер"].trigger()
    assert window.ui_scale.preset == "normal"

    # Real key presses through the window, as from the keyboard (also with a field focused).
    window.activateWindow()
    next(iter(window._config_inputs.values())).setFocus()
    control = QtCore.Qt.KeyboardModifier.ControlModifier
    for key, expected in (
        (QtCore.Qt.Key.Key_Equal, "large"),
        (QtCore.Qt.Key.Key_Plus, "max"),
        (QtCore.Qt.Key.Key_Minus, "large"),
        (QtCore.Qt.Key.Key_0, "normal"),
    ):
        QtTest.QTest.keyClick(window.windowHandle(), key, control)
        QtWidgets.QApplication.processEvents()
        assert window.ui_scale.preset == expected, key

    toolbar = window.findChild(QtWidgets.QToolBar, "workspace_toolbar")
    names = [
        toolbar.widgetForAction(action).objectName() for action in toolbar.actions() if toolbar.widgetForAction(action)
    ]
    assert names.index("scale_button") + 1 == names.index("theme_button")  # «Буфер» stays right of «Тема»
    assert window.findChild(QtWidgets.QToolButton, "scale_button").menu() is window.scale_menu


@pytest.mark.parametrize("theme", list(Theme))
def test_largest_scale_cuts_nothing_off(window: MainWindow, theme: Theme) -> None:
    window.set_theme(theme)
    window.set_ui_scale("max")
    window.set_area_scale("parameters", 2.0)
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    splitter = window.dock_manager.dockContainers()[0].rootSplitter()
    splitter.setSizes([0, sum(splitter.sizes())])
    app.processEvents()

    panel = window.parameters_dock.widget()
    assert panel.width() >= panel.minimumSizeHint().width()
    inner = window.parameters_scroll.widget()
    assert inner.width() >= inner.minimumSizeHint().width()
    assert not window.parameters_scroll.horizontalScrollBar().isVisible()
    for button in window.actions_box.findChildren(QtWidgets.QPushButton):
        assert button.width() >= button.sizeHint().width(), button.text()
    for group in window._parameter_groups.values():
        assert group.toggle_button.width() >= group.toggle_button.sizeHint().width()
        for label in group.content.findChildren(QtWidgets.QLabel):
            if label.isVisible() and not label.wordWrap():
                assert label.width() >= label.minimumSizeHint().width(), label.text()
    # The fields under the plot hold their numbers.
    for spin in window._plot_scale_inputs.values():
        text_width = spin.fontMetrics().horizontalAdvance(spin.text())
        assert spin.lineEdit().width() >= text_width, spin.text()
    for label in window._plot_y2_labels.values():
        assert label.minimumWidth() >= label.fontMetrics().horizontalAdvance("Y2 max, lg (I/I_g)²")


def test_class_fonts_buttons_and_labels_follow_the_preset_and_a_theme_change(window: MainWindow) -> None:
    """On macOS QPushButton/QToolButton… have their own platform font and docked widgets do not
    inherit the application font under the style sheets: all of them must still grow."""
    classes = base_class_point_sizes()
    assert {"QPushButton", "QToolButton", "QLabel", "QMenu"} <= set(classes)
    home = next(button for button in window.findChildren(QtWidgets.QPushButton) if button.text() == "Задать Home")
    theme_button = window.findChild(QtWidgets.QToolButton, "theme_button")
    x_label = window._plot_scale_labels["x_min"]
    for theme in (None, Theme.DARK, Theme.LIGHT):
        if theme is not None:
            window.set_theme(theme)  # QApplication.setStyle restores the platform class fonts
        window.set_ui_scale("max" if theme is None else window.ui_scale.preset)
        QtWidgets.QApplication.processEvents()
        for name, size in classes.items():
            assert QtWidgets.QApplication.font(name).pointSizeF() == pytest.approx(size * 1.5, abs=0.05), (theme, name)
        assert home.font().pointSizeF() == pytest.approx(classes["QPushButton"] * 1.5, abs=0.05)
        assert theme_button.font().pointSizeF() == pytest.approx(classes["QToolButton"] * 1.5, abs=0.05)
        assert x_label.font().pointSizeF() == pytest.approx(classes["QLabel"] * 1.5, abs=0.05)
    window.set_ui_scale("normal")
    QtWidgets.QApplication.processEvents()
    for name, size in classes.items():
        assert QtWidgets.QApplication.font(name).pointSizeF() == pytest.approx(size, abs=0.05), name
    assert home.font().pointSizeF() == pytest.approx(classes["QPushButton"], abs=0.05)


def _plot_controls(window: MainWindow) -> list[QtWidgets.QWidget]:
    return [
        *window._plot_scale_labels.values(),
        *window._plot_scale_inputs.values(),
        window._plot_threshold_label,
        window._plot_threshold_input,
        window._plot_apply_scale_button,
        window._plot_home_button,
        window._plot_export_button,
        *window._plot_y2_labels.values(),
        *window._plot_y2_inputs.values(),
        window._plot_y2_span_label,
    ]


def _row(window: MainWindow, widget: QtWidgets.QWidget) -> int:
    return window._plot_controls.getItemPosition(window._plot_controls.indexOf(widget))[0]


def _assert_plot_controls_fit(window: MainWindow) -> None:
    panel = window.plot_dock.widget()
    scroll = panel.parentWidget()
    while scroll is not None and not isinstance(scroll, QtWidgets.QScrollArea):
        scroll = scroll.parentWidget()
    if scroll is not None:
        assert not scroll.horizontalScrollBar().isVisible()
        visible_width = scroll.viewport().width()
    else:
        visible_width = panel.width()
    assert panel.width() <= visible_width
    controls = window._plot_controls_widget
    assert controls.width() >= controls.minimumWidth()
    for widget in _plot_controls(window):
        if not widget.isVisible():
            continue
        name = widget.text() if hasattr(widget, "text") else widget.objectName()
        left = widget.mapTo(panel, QtCore.QPoint(0, 0)).x()
        assert left >= 0 and left + widget.width() <= visible_width, name
        if isinstance(widget, QtWidgets.QPushButton | QtWidgets.QLabel):
            assert widget.width() >= widget.minimumSizeHint().width(), name


def test_plot_controls_fold_into_compact_rows_at_the_largest_scale(window: MainWindow) -> None:
    """WP-065: at «Максимальный» in 1440×920 the fields under the plot take two-field rows, no scrolling."""
    app = QtWidgets.QApplication.instance()
    normal_width = window.parameters_dock.widget().width()
    window.set_ui_scale("max")
    app.processEvents()
    assert window.parameters_dock.widget().width() >= normal_width  # the parameter panel keeps its default width
    assert window._plot_controls_mode == "compact"
    inputs = window._plot_scale_inputs
    assert [_row(window, inputs[name]) for name in ("x_min", "x_max", "y_min", "y_max")] == [0, 0, 1, 1]
    assert _row(window, window._plot_threshold_input) == _row(window, window._plot_export_button) == 2
    assert not window._plot_y2_inputs["y2_min"].isVisible()  # no row of greyed-out Y2 fields
    _assert_plot_controls_fit(window)

    # A current on the right axis: Y2 in a row of its own, still inside the panel.
    window._set_plot_y2_fields_enabled(True, "lg (I/I_g)²")
    app.processEvents()
    assert window._plot_y2_inputs["y2_max"].isVisible()
    assert _row(window, window._plot_y2_inputs["y2_max"]) == 3
    _assert_plot_controls_fit(window)
    window._set_plot_y2_fields_enabled(False)

    window.set_ui_scale("normal")
    app.processEvents()
    assert window._plot_controls_mode != "compact"
    assert {_row(window, inputs[name]) for name in ("x_min", "x_max", "y_min", "y_max")} == {0}
    assert _row(window, window._plot_threshold_input) == 1
    _assert_plot_controls_fit(window)


FREQUENCIES = tuple(100.0 + 5 * index for index in range(161))


def _settle() -> None:
    """Let the deferred minimum widths, refolded fields and dock sizes (WP-068) take effect."""
    for _ in range(8):
        QtWidgets.QApplication.processEvents()


def _show_curves(window: MainWindow, current: bool) -> None:
    """SMC, its previous run and HFSS (three legend rows); with *current* also exp on the right axis."""
    window._update_s21_plot(list(FREQUENCIES), [-4.0 - 6.0 * (index % 40) / 40 for index in range(161)])
    window._update_s21_plot(list(FREQUENCIES), [-5.0 - 6.0 * (index % 40) / 40 for index in range(161)])
    window.add_comparison_trace("HFSS", ComparisonTrace(FREQUENCIES, (-6.0,) * 161, Path("hfss.tab")))
    if current:
        trace = ComparisonTrace(
            FREQUENCIES, tuple(0.01 + 0.002 * (i % 20) for i in range(161)), Path("exp.txt"), quantity="mA"
        )
        window.add_comparison_trace("Experiment", trace)
    _settle()


def _assert_plot_usable(window: MainWindow) -> None:
    """The data area keeps its WP-068 minimum and holds the whole legend above the X axis."""
    plot_item = window._plot.getPlotItem()
    view = plot_item.vb.sceneBoundingRect()
    factor = window.ui_scale.factor
    assert view.height() >= PLOT_DATA_MIN_HEIGHT * factor - 1
    legend = window._plot_legend.sceneBoundingRect()
    axis = plot_item.getAxis("bottom")
    axis_rect = axis.mapRectToScene(QtCore.QRectF(QtCore.QPointF(0, 0), axis.size()))
    assert not legend.intersects(axis_rect)
    assert legend.bottom() <= view.bottom()
    assert window.plot_height_shortfall() <= 0


@pytest.mark.parametrize("current", [False, True], ids=["three-curves", "with-current"])
@pytest.mark.parametrize("preset", list(UI_SCALE_PRESETS))
def test_plot_keeps_a_usable_data_area_at_every_preset(window: MainWindow, preset: str, current: bool) -> None:
    """WP-068: at «Максимальный» in 1440×920 the plot was 169 px high (133 px with a current), the legend over the X axis."""
    _show_curves(window, current)
    window.set_ui_scale(preset)
    _settle()
    _assert_plot_usable(window)
    _assert_plot_controls_fit(window)
    if preset == "max":
        # Title, axes and three legend rows at 150 % still leave room for the curves.
        assert window._plot.height() >= 250
    # «Восстановить виджеты» gives the default docks, again with room for the plot.
    window.restore_default_layout()
    _settle()
    _assert_plot_usable(window)


def test_largest_scale_with_a_larger_parameter_panel_needs_no_horizontal_scroll(window: MainWindow) -> None:
    """WP-068: «Максимальный» + parameters 150 % left the plot dock narrower than its compact fields."""
    _show_curves(window, current=True)
    one_line = window._same_materials_checkbox.text()
    window.set_ui_scale("max")
    _settle()
    assert window._same_materials_checkbox.text() == one_line  # parameters at 100 %: one line as before
    window.set_area_scale("parameters", 1.5)
    _settle()
    checkbox = window._same_materials_checkbox
    assert checkbox.text() == "Use the same material\nas EL1 (Tc, α, σ)"
    assert checkbox.width() >= checkbox.sizeHint().width() and checkbox.height() >= checkbox.sizeHint().height()
    panel = window.parameters_dock.widget()
    assert panel.width() >= panel.minimumSizeHint().width()
    assert window._plot_y2_inputs["y2_max"].isVisible()
    _assert_plot_controls_fit(window)
    _assert_plot_usable(window)
    for _ in range(2):  # from the default docks too
        window.restore_default_layout()
        _settle()
        _assert_plot_controls_fit(window)
        _assert_plot_usable(window)
        assert panel.width() >= panel.minimumSizeHint().width()
    window.set_area_scale("parameters", 1.0)
    _settle()
    assert window._same_materials_checkbox.text() == one_line


def test_normal_layout_is_unchanged(window: MainWindow) -> None:
    """WP-068 must not move the docks of the default «Обычный» 1440×920 layout."""
    _settle()
    root = window.dock_manager.dockContainers()[0].rootSplitter()
    right = window.schematic_dock.dockAreaWidget().parentSplitter()
    root_sizes, right_sizes = root.sizes(), right.sizes()
    total = sum(right_sizes)
    # The original 50/38/12 split of the right column and the parameter panel width.
    for size, percent in zip(right_sizes, (50, 38, 12)):
        assert size == pytest.approx(total * percent / 100, abs=2)
    minimum = window.parameters_dock.widget().minimumSizeHint().width() + PARAMETERS_WIDTH_RESERVE
    assert root_sizes[0] == pytest.approx(max(280, sum(root_sizes) // 4, minimum), abs=2)
    assert window.plot_height_shortfall() <= 0
    window._ensure_plot_room()
    _settle()
    assert (root.sizes(), right.sizes()) == (root_sizes, right_sizes)
    assert "\n" not in window._same_materials_checkbox.text()
