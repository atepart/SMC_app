"""«Буфер» on the workspace toolbar: store/restore parameters and the buff curve (WP-041, GitHub #11)."""

from __future__ import annotations

import gc
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.domain.s21_models import S21Config, S21Result
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow
from smcapp.ui.plot_legend import CheckableItemSample
from smcapp.ui.theme import Theme, apply_application_theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FREQUENCIES = [100.0, 300.0, 500.0, 700.0, 900.0]
# Fields edited between «Записать» and «Восстановить»: a line, a dielectric, a
# material (synced EL1 → EL2) and a transformer (its n/dl are derived).
EDITS = {"mex4_width_m": 3.5, "e_sub": 11.9, "tc_top_k": 8.7, "mex02_2_w1_m": 16.0}


class FakeS21UseCase:
    """A quick stand-in for the backend: S21 depends on a few parameters."""

    def execute(self, config: S21Config, output_path=None, progress_callback=None) -> S21Result:
        shift = config.mex4_width_m * 1e6 + config.e_sub + config.tc_top_k
        return S21Result(FREQUENCIES, [-(frequency / 100.0) - shift for frequency in FREQUENCIES], ["fake S21"])


@pytest.fixture
def window():
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance()
    window = MainWindow(
        GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()),
        FakeS21UseCase(),
    )
    window._s21_output.setText("")  # no S21 table on disk
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


def _run_s21(window: MainWindow) -> list[float]:
    """Press Run S21 and wait for the worker thread like the user would."""
    QTest.mouseClick(window._run_s21_button, QtCore.Qt.MouseButton.LeftButton)
    deadline = time.monotonic() + 10
    while window._s21_thread is not None:
        assert time.monotonic() < deadline, "S21 worker did not finish"
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    return _curve(window, "SMC").yData.tolist()


def _curve(window: MainWindow, name: str):
    return next(item for item in window._plot.listDataItems() if item.name() == name)


def _curve_names(window: MainWindow) -> list[str]:
    return [label.text for _sample, label in window._plot_legend.items]


def _menu_action(window: MainWindow, text: str):
    return next(action for action in window.buffer_menu.actions() if action.text() == text)


def _store(window: MainWindow) -> None:
    _menu_action(window, "Записать").trigger()
    QtWidgets.QApplication.processEvents()


def _restore(window: MainWindow) -> None:
    _menu_action(window, "Восстановить").trigger()
    QtWidgets.QApplication.processEvents()


def _edit(window: MainWindow, values: dict[str, float]) -> None:
    for name, value in values.items():
        window._config_inputs[name].setValue(value)
    QtWidgets.QApplication.processEvents()


def test_buffer_button_is_right_of_theme_with_store_and_restore(window: MainWindow) -> None:
    toolbar = window.findChild(QtWidgets.QToolBar, "workspace_toolbar")
    widgets = [toolbar.widgetForAction(action) for action in toolbar.actions()]
    names = [widget.objectName() if widget is not None else "" for widget in widgets]
    assert names.index("buffer_button") == names.index("theme_button") + 1
    button = widgets[names.index("buffer_button")]
    assert button.text() == "Буфер"
    assert button.menu() is window.buffer_menu
    assert button.popupMode() == QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
    assert [action.text() for action in window.buffer_menu.actions()] == ["Записать", "Восстановить"]


def test_empty_buffer_cannot_be_restored(window: MainWindow) -> None:
    restore = _menu_action(window, "Восстановить")
    assert not restore.isEnabled()
    before = window._build_config()
    _edit(window, {"mex4_width_m": 3.5})

    assert window.restore_buffer() is None  # even a direct call does nothing
    assert window._config_inputs["mex4_width_m"].value() == 3.5
    assert window._build_config() != before
    assert window.parameter_buffer is None
    assert "buff" not in _curve_names(window)


def test_store_freezes_buff_while_parameters_and_s21_change(window: MainWindow) -> None:
    first = _run_s21(window)
    _store(window)

    buffer = window.parameter_buffer
    assert buffer is not None and buffer.same_material
    assert buffer.config == window._build_config()
    assert _curve(window, "buff").yData.tolist() == first
    assert _curve_names(window) == ["SMC", "buff"]
    assert _menu_action(window, "Восстановить").isEnabled()
    assert window._s21_status.text() == "Буфер: параметры и кривая buff (5 точек) записаны."

    _edit(window, EDITS)
    second = _run_s21(window)

    assert second != first
    assert _curve(window, "buff").yData.tolist() == first
    assert _curve(window, "prev").yData.tolist() == first
    assert _curve_names(window) == ["SMC", "prev", "buff"]
    assert window.parameter_buffer is buffer  # nothing in the buffer followed the edits
    _run_s21(window)
    assert _curve(window, "buff").yData.tolist() == first


def test_restore_returns_every_field_and_material_flag_and_keeps_buff(window: MainWindow) -> None:
    first = _run_s21(window)
    _store(window)
    stored = window.parameter_buffer.config
    stored_values = {name: spin.value() for name, spin in window._config_inputs.items()}

    window._same_materials_checkbox.setChecked(False)
    _edit(window, {**EDITS, "tc_bot_k": 7.1, "d_bot_m": 250.0})
    second = _run_s21(window)
    assert window._build_config() != stored

    _restore(window)

    assert window._build_config() == stored
    assert {name: spin.value() for name, spin in window._config_inputs.items()} == stored_values
    assert window._same_materials_checkbox.isChecked()
    assert not window._config_inputs["tc_bot_k"].isEnabled()
    assert window._s21_status.text() == "Буфер: параметры восстановлены; кривая buff не изменена."
    # Restoring neither recalculates nor touches the curves.
    assert _curve(window, "buff").yData.tolist() == first
    assert _curve(window, "SMC").yData.tolist() == second
    assert window.parameter_buffer.config == stored

    assert _run_s21(window) == first  # the restored parameters reproduce buff
    assert _curve(window, "buff").yData.tolist() == first


def test_restore_keeps_separate_materials_when_stored_that_way(window: MainWindow) -> None:
    window._same_materials_checkbox.setChecked(False)
    _edit(window, {"tc_bot_k": 7.1})
    _store(window)
    assert not window.parameter_buffer.same_material

    window._same_materials_checkbox.setChecked(True)
    assert window._config_inputs["tc_bot_k"].value() == 9.5
    _restore(window)

    assert not window._same_materials_checkbox.isChecked()
    assert window._config_inputs["tc_bot_k"].isEnabled()
    assert window._config_inputs["tc_bot_k"].value() == 7.1
    assert window._build_config().tc_bot_k == pytest.approx(7.1)


def test_restore_redraws_the_schematic(window: MainWindow, monkeypatch) -> None:
    _store(window)
    _edit(window, {"mex4_width_m": 3.5})
    drawn: list[float] = []
    original = window._use_case

    class RecordingUseCase:
        def draw(self, config, **kwargs):
            drawn.append(config.mex4_width_m)
            return original.draw(config, **kwargs)

    monkeypatch.setattr(window, "_use_case", RecordingUseCase())
    _restore(window)
    assert drawn == [pytest.approx(6e-6)]


def test_store_before_any_calculation_keeps_parameters_only(window: MainWindow) -> None:
    _store(window)

    assert window.parameter_buffer is not None
    assert window.parameter_buffer.trace is None
    assert window._plot.listDataItems() == []
    assert "кривой buff нет" in window._s21_status.text()
    assert _menu_action(window, "Восстановить").isEnabled()

    _run_s21(window)
    assert _curve_names(window) == ["SMC"]  # a later calculation does not fill the buffer


def test_store_again_replaces_buffer_and_curve(window: MainWindow) -> None:
    first = _run_s21(window)
    _store(window)
    _edit(window, EDITS)
    second = _run_s21(window)
    _store(window)

    assert window.parameter_buffer.config == window._build_config()
    assert window.parameter_buffer.config.mex4_width_m == pytest.approx(3.5e-6)
    assert _curve(window, "buff").yData.tolist() == second != first
    assert [name for name in _curve_names(window) if name == "buff"] == ["buff"]


def test_store_mentions_parameters_edited_after_the_calculation(window: MainWindow) -> None:
    _run_s21(window)
    _edit(window, {"mex4_width_m": 3.5})
    _store(window)
    assert "изменены после последнего расчёта" in window._s21_status.text()


def test_invalid_parameters_show_dialog_and_keep_the_buffer(window: MainWindow, monkeypatch) -> None:
    first = _run_s21(window)
    _store(window)
    buffer = window.parameter_buffer
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda _parent, title, text: shown.append((title, text)))

    _edit(window, {"s21_freq_start_ghz": 900.0, "s21_freq_stop_ghz": 100.0})
    _store(window)

    assert len(shown) == 1 and shown[0][0] == "Ошибка записи в буфер"
    assert window.parameter_buffer is buffer
    assert _curve(window, "buff").yData.tolist() == first


def test_invalid_parameters_before_first_store_leave_restore_disabled(window: MainWindow, monkeypatch) -> None:
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *_args: None)
    _edit(window, {"s21_freq_start_ghz": 900.0, "s21_freq_stop_ghz": 100.0})
    _store(window)
    assert window.parameter_buffer is None
    assert not _menu_action(window, "Восстановить").isEnabled()


def test_buff_check_box_hides_curve_through_calculation_and_restore(window: MainWindow) -> None:
    first = _run_s21(window)
    _store(window)
    sample = next(sample for sample, label in window._plot_legend.items if label.text == "buff")
    assert isinstance(sample, CheckableItemSample) and sample.checked

    view_point = window._plot.mapFromScene(sample.mapToScene(QtCore.QPointF(6, 10)))
    QTest.mouseClick(window._plot.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=view_point)
    QtWidgets.QApplication.processEvents()
    assert not _curve(window, "buff").isVisible()
    assert _curve(window, "SMC").isVisible()

    _edit(window, EDITS)
    _run_s21(window)
    _restore(window)
    buff = _curve(window, "buff")
    assert not buff.isVisible() and buff.yData.tolist() == first

    window.set_curve_visible("buff", True)
    assert _curve(window, "buff").isVisible()
