"""«Удалить» / «Добавить» on element group titles (WP-044, GitHub #11)."""

from __future__ import annotations

import gc
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.domain.circuit import element_numbers
from smcapp.domain.s21_models import S21Config, S21Result
from smcapp.infrastructure.design_files import DesignFileService
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow
from smcapp.ui.theme import Theme, apply_application_theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class RecordingS21UseCase:
    """Stand-in backend that remembers the configuration it was given."""

    def __init__(self) -> None:
        self.configs: list[S21Config] = []

    def execute(self, config: S21Config, output_path=None, progress_callback=None) -> S21Result:
        self.configs.append(config)
        return S21Result([100.0, 500.0, 900.0], [-3.0, -1.0, -5.0], ["fake S21"])


@pytest.fixture
def window():
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance()
    window = MainWindow(
        GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()), RecordingS21UseCase()
    )
    window._s21_output.setText("")
    window.resize(1440, 920)
    window.show()
    app.processEvents()
    yield window
    window.save_settings = Mock()
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
    apply_application_theme(app, Theme.DEFAULT, ASSETS)
    QtCore.QSettings().clear()
    app.processEvents()


def _group(window: MainWindow, number: int):
    return next(box for name, box in window._parameter_groups.items() if name.startswith(f"{number} · "))


def _menu_texts(window: MainWindow, number: int) -> list[tuple[str, bool]] | None:
    menu = window._element_menu(_group(window, number))
    return None if menu is None else [(action.text(), action.isEnabled()) for action in menu.actions()]


def _trigger(window: MainWindow, number: int, text: str) -> None:
    menu = window._element_menu(_group(window, number))
    next(action for action in menu.actions() if action.text() == text).trigger()
    QtWidgets.QApplication.processEvents()


def _element_groups(window: MainWindow) -> list[str]:
    return [name for name in window._parameter_groups if " · " in name]


def _run_s21(window: MainWindow) -> S21Config:
    QTest.mouseClick(window._run_s21_button, QtCore.Qt.MouseButton.LeftButton)
    deadline = time.monotonic() + 10
    while window._s21_thread is not None:
        assert time.monotonic() < deadline
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    return window._s21_use_case.configs[-1]


def test_menu_only_on_transformers_and_lines_of_mex_sections(window) -> None:
    for number in (1, 2, 3, 4, 5, 6, 10, 11, 12, 13):
        assert _menu_texts(window, number) == [("Удалить", True), ("Добавить", True)]
        assert _group(window, number).toggle_button.contextMenuPolicy() == QtCore.Qt.ContextMenuPolicy.CustomContextMenu
    for number in (7, 8, 9, 14, 15, 16, 17, 18):
        assert _menu_texts(window, number) is None
    assert window._parameter_groups["General"].element_id is None


def test_right_click_on_the_title_opens_the_menu(window) -> None:
    button = _group(window, 2).toggle_button
    shown = []
    with patch.object(
        window, "_exec_element_menu", lambda menu, _position: shown.append([a.text() for a in menu.actions()])
    ):
        # What Qt sends to the title on a right click.
        QtWidgets.QApplication.sendEvent(
            button,
            QtGui.QContextMenuEvent(
                QtGui.QContextMenuEvent.Reason.Mouse, QtCore.QPoint(5, 5), button.mapToGlobal(QtCore.QPoint(5, 5))
            ),
        )
        corner = _group(window, 8).toggle_button
        QtWidgets.QApplication.sendEvent(
            corner,
            QtGui.QContextMenuEvent(
                QtGui.QContextMenuEvent.Reason.Mouse, QtCore.QPoint(5, 5), corner.mapToGlobal(QtCore.QPoint(5, 5))
            ),
        )
    assert shown and all(texts == ["Удалить", "Добавить"] for texts in shown)
    assert _group(window, 2).isChecked()  # a right click does not collapse the group


def test_remove_2_renumbers_panel_schematic_and_calculation(window) -> None:
    window._config_inputs["mex01_3_w1_m"].setValue(30)  # unsaved edit of the former 3 survives
    window._config_inputs["e_sub"].setValue(11.5)
    with patch.object(window._view, "set_svg", wraps=window._view.set_svg) as displayed:
        _trigger(window, 2, "Удалить")
    groups = _element_groups(window)
    assert [int(name.split()[0]) for name in groups] == list(range(1, 18))
    assert groups[:3] == ["1 · Трансформатор", "2 · Трансформатор", "3 · Линия"]
    assert "7 · DC block" in groups and "13 · Линия SIS" in groups
    assert window._config_inputs["mex01_2_w1_m"].value() == 30
    assert window._config_inputs["e_sub"].value() == 11.5
    assert "mex01_3_w1_m" not in window._config_inputs
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel) if label.isVisible()}
    assert "2 · W1" in labels and "13 · L1 · L4/2" in labels
    assert "Элемент 2 удалён" in window._s21_status.text()

    geometry = displayed.call_args.kwargs["hit_map"]
    drawing = window._use_case.calculator.calculate(window._build_config())
    assert [e.number for e in drawing.elements] == list(range(1, 18))
    assert {area.element_id for area in geometry.areas} == set(element_numbers(window._build_config()))

    config = _run_s21(window)
    assert len(config.mex01) == 2 and config.mex01[1].w1_m == pytest.approx(30e-6)
    assert config.e_sub == 11.5


def test_add_to_line_4_gives_transformer_5_and_line_6(window) -> None:
    _trigger(window, 4, "Добавить")
    groups = _element_groups(window)
    assert groups[3:7] == ["4 · Линия", "5 · Трансформатор", "6 · Линия", "7 · Трансформатор"]
    assert "10 · DC block" in groups and "20 · Выходная линия" in groups
    inputs = window._config_inputs
    # First width = last width of 4 (18), last width = first width of the old 5 (18): rectangular.
    assert (inputs["mex02_2_w1_m"].value(), inputs["mex02_2_w2_m"].value(), inputs["mex02_2_length_m"].value()) == (
        18,
        18,
        4,
    )
    assert (inputs["mex02_3_width_m"].value(), inputs["mex02_3_length_m"].value()) == (18, 20)
    status = window._transformer_status["mex02_2"].text()
    assert status.startswith("dw=1 µm; n=1; dl=4 µm") and "считается как есть" in status
    assert "добавлены трансформатор 5 и линия 6" in window._s21_status.text()
    config = _run_s21(window)  # a rectangular transformer is calculated as one slice
    assert len(config.mex02) == 5


def test_add_to_transformer_and_widths_at_the_section_ends(window) -> None:
    _trigger(window, 13, "Добавить")  # end of Mex03: before «Линия SIS» (W1 = 6)
    inputs = window._config_inputs
    assert (inputs["mex03_5_width_m"].value(), inputs["mex03_5_length_m"].value()) == (6, 20)
    assert (inputs["mex03_6_w1_m"].value(), inputs["mex03_6_w2_m"].value()) == (6, 6)
    assert "16 · Линия SIS" in window._parameter_groups
    _trigger(window, 6, "Добавить")  # end of Mex02: line 6 (4) before corner 7 (W1 = 6)
    assert (inputs := window._config_inputs)["mex02_4_w1_m"].value() == 4
    assert inputs["mex02_4_w2_m"].value() == 6
    assert window._transformer_status["mex02_4"].text() == "dw=1 µm; n=3; dl=1.33333 µm (из файла/исходных параметров)"
    assert "9 · Трансформатор" in window._parameter_groups  # corner, now 9


def test_last_element_of_a_section_cannot_be_removed(window) -> None:
    _trigger(window, 1, "Удалить")
    _trigger(window, 1, "Удалить")
    assert _menu_texts(window, 1) == [("Удалить", False), ("Добавить", True)]
    assert "Последний элемент Mex01" in window._element_menu(_group(window, 1)).actions()[0].toolTip()
    _trigger(window, 1, "Добавить")
    assert _element_groups(window)[:3] == ["1 · Трансформатор", "2 · Линия", "3 · Трансформатор"]


def test_unfinished_transformer_edit_blocks_adding_but_not_its_removal(window) -> None:
    window._config_inputs["mex01_3_length_m"].setValue(100)  # no valid n/dl
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        _trigger(window, 4, "Добавить")
    assert "Элемент 3" in warning.call_args.args[2]
    assert len(_element_groups(window)) == 18
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        _trigger(window, 3, "Удалить")
    warning.assert_not_called()
    assert len(_element_groups(window)) == 17


def test_expanded_groups_and_scroll_survive_the_rebuild(window) -> None:
    _group(window, 12).setChecked(False)
    _group(window, 1).setChecked(False)
    window._parameter_groups["General"].setChecked(False)
    bar = window.parameters_scroll.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    position = bar.value()
    _trigger(window, 4, "Удалить")
    assert not window._parameter_groups["General"].isChecked()
    assert not _group(window, 1).isChecked()
    assert not _group(window, 11).isChecked()  # the former 12
    assert all(_group(window, n).isChecked() for n in (2, 3, 4, 5, 10, 12))
    assert bar.value() == position
    _trigger(window, 3, "Добавить")
    assert not _group(window, 13).isChecked()  # the former 12 again
    assert _group(window, 4).isChecked() and _group(window, 5).isChecked()  # new groups open


def test_buffer_and_files_restore_another_composition(window, tmp_path) -> None:
    window._config_inputs["mex03_3_length_m"].setValue(33)
    window.store_buffer()
    saved = window.save_design_to_path(tmp_path / "default.smcdesign")
    _trigger(window, 12, "Удалить")
    _trigger(window, 2, "Добавить")
    assert len(_element_groups(window)) == 19
    window.restore_buffer()
    assert len(_element_groups(window)) == 18
    assert window._config_inputs["mex03_3_length_m"].value() == 33
    assert window._build_config() == window.parameter_buffer.config

    _trigger(window, 11, "Удалить")
    changed = window.save_design_to_path(tmp_path / "changed.smcdesign")
    window.load_design_from_path(saved)
    assert len(_element_groups(window)) == 18
    window.load_design_from_path(changed)
    assert len(_element_groups(window)) == 17
    assert window._build_config() == DesignFileService().load(changed)
    assert "11 · Линия" in window._parameter_groups  # former 12 after removing 11


def test_transformer_n_dl_follow_the_new_composition(window) -> None:
    _trigger(window, 1, "Удалить")  # former 3 becomes 2
    inputs = window._config_inputs
    inputs["mex01_2_w1_m"].setValue(8)
    inputs["mex01_2_w2_m"].setValue(10)
    inputs["mex01_2_length_m"].setValue(4.5)
    assert window._transformer_status["mex01_2"].text() == "dw=1 µm; n=3; dl=1.5 µm"
    element = window._build_config().element("mex01_2")
    assert (element.n_um, element.dl_m) == (1, pytest.approx(1.5e-6))
    inputs["mex01_2_length_m"].setValue(100)
    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
        window._update_svg()
    assert "Элемент 2" in warning.call_args.args[2]
