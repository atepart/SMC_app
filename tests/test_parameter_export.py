"""«Экспорт → Параметры HFSS»: readable parameter list (WP-058, GitHub #12)."""

from __future__ import annotations

import gc
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtWidgets

from smcapp.application.use_cases import GenerateStructureUseCase
from smcapp.application.version import __version__
from smcapp.domain.circuit import insert_after, remove_element
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.geometry import IntegratedStructureCalculator
from smcapp.infrastructure.parameter_export import field_unit, hfss_parameters_text, write_hfss_parameters
from smcapp.infrastructure.svg_renderer import SvgRendererImpl
from smcapp.ui.app import MainWindow
from smcapp.ui.theme import Theme, apply_application_theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _groups(text: str) -> dict[str, list[str]]:
    """Title line → its lines; groups are separated by blank lines."""
    groups: dict[str, list[str]] = {}
    for block in text.strip().split("\n\n")[1:]:
        title, *lines = block.split("\n")
        groups[title] = lines
    return groups


def test_default_text_follows_panel_groups_with_units() -> None:
    config = S21Config()
    text = hfss_parameters_text(config, same_material=True, version="011")
    assert text.startswith("# Параметры структуры SMC_app 011\n\nGeneral\nSweep start = 100 GHz\n")
    groups = _groups(text)
    expected_order = [group for group in config.group_order() if group in groups]
    assert list(groups) == expected_order
    assert list(groups)[:5] == ["General", "Backend Grid", "EL1 Material", "EL2 Material", "Dielectrics"]
    assert list(groups)[5] == "1 · Трансформатор"
    assert list(groups)[-1] == f"{len(config.element_slots())} · Выходная линия"

    general = groups["General"]
    assert "Z FFO = 0.15 Ω" in general
    assert "dW = 0.50 µm" in general
    assert "T env = 4.2 K" in general
    assert "h sub = 350 µm" in general
    assert "σ EL1 = 18.000 1/(Ω·µm)" in groups["EL1 Material"]
    assert "d EL1 = 350 nm" in groups["EL1 Material"]
    assert groups["EL2 Material"][-1] == "Материал как у EL1 (Tc, α, σ) = да"
    assert "C0 = 0.083 pF/µm²" in groups["15 · SIS"]
    assert "RnS = 32.0 Ω·µm²" in groups["15 · SIS"]
    assert "Angle = 113°" in groups["17 · Radial Stub"]


def test_hidden_fields_are_left_out() -> None:
    text = hfss_parameters_text(S21Config())
    assert "Δ₀" not in text
    assert "Материал как у EL1" not in text  # unknown without the panel
    assert text.startswith("# Параметры структуры SMC_app\n")


def test_transformer_slicing_and_dielectric_stack_lines() -> None:
    groups = _groups(hfss_parameters_text(S21Config()))
    assert groups["1 · Трансформатор"] == ["W1 = 14.0 µm", "W2 = 49.0 µm", "L = 9.6 µm", "dw=5 µm; n=8; dl=1.2 µm"]
    assert groups["2 · Линия"] == ["W = 50.0 µm", "L = 13.0 µm"]
    assert groups["Dielectrics"] == [
        "h1 = 150 nm",
        "h2 = 250 nm",
        "V anod = 10.0 V",
        "ε i = 4.200",
        "ε Al = 9.800",
        "H1 = h1 + Ha = 165.7290 nm; ε₁ = 4.44084",
        "H12 = h1 + h2 + Ha = 415.7290 nm; ε₁₂ = 4.29281",
    ]


def test_numbering_follows_composition() -> None:
    config = S21Config()
    count = len(config.element_slots())
    removed = _groups(hfss_parameters_text(remove_element(config, "MSL1.2")))
    assert "2 · Трансформатор" in removed  # former 3 moved up
    assert f"{count - 1} · Выходная линия" in removed
    assert f"{count} · Выходная линия" not in removed

    added = _groups(hfss_parameters_text(insert_after(config, "MSL1.2")))
    assert added["3 · Трансформатор"][-1].startswith("dw=")  # a new transformer after line 2
    assert "4 · Линия" in added
    assert f"{count + 2} · Выходная линия" in added


def test_units_of_every_visible_field_are_readable() -> None:
    for info in S21Config().ui_fields():
        unit = field_unit(info)
        assert "um" not in unit and "Ohm" not in unit and "*" not in unit and "^" not in unit, (info.name, unit)


def test_write_adds_txt_and_uses_utf8(tmp_path: Path) -> None:
    destination = write_hfss_parameters(tmp_path / "design", "ε₁₂ = 4.29281\n")
    assert destination == tmp_path / "design.txt"
    assert destination.read_bytes() == "ε₁₂ = 4.29281\n".encode("utf-8")


@pytest.fixture
def window():
    gc.collect()
    QtCore.QSettings().clear()
    app = QtWidgets.QApplication.instance()
    window = MainWindow(GenerateStructureUseCase(IntegratedStructureCalculator(), SvgRendererImpl()), Mock())
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


def _toolbar_texts(window: MainWindow) -> list[str]:
    toolbar = window.findChild(QtWidgets.QToolBar, "workspace_toolbar")
    texts = []
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if isinstance(widget, QtWidgets.QToolButton) and widget.text():
            texts.append(widget.text())
    return texts


def test_export_menu_sits_after_buffer(window: MainWindow) -> None:
    texts = _toolbar_texts(window)
    assert texts.index("Экспорт") == texts.index("Буфер") + 1
    assert [action.text() for action in window.export_menu.actions()] == ["Параметры HFSS…"]


def test_export_writes_applied_values(window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "hd35"
    window._config_inputs["z_ffo_ohm"].setValue(0.25)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    window.export_hfss_action.trigger()
    text = (tmp_path / "hd35.txt").read_text(encoding="utf-8")
    assert "Z FFO = 0.25 Ω" in text
    assert text == hfss_parameters_text(window._build_config(), same_material=True, version=__version__)
    assert "Параметры HFSS сохранены" in window._s21_status.text()


def test_export_cancel_writes_nothing(window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))
    critical = Mock()
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", critical)
    monkeypatch.chdir(tmp_path)
    window.export_hfss_action.trigger()
    assert list(tmp_path.iterdir()) == []
    critical.assert_not_called()


def test_export_write_error_shows_message(window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "missing" / "parameters.txt"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(missing), ""))
    critical = Mock()
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", critical)
    window.export_hfss_action.trigger()
    critical.assert_called_once()
    assert critical.call_args.args[1] == "Ошибка экспорта параметров"
    assert not missing.exists()


def test_export_invalid_input_is_reported_before_the_dialog(window: MainWindow, monkeypatch) -> None:
    window._config_inputs["temperature_k"].setValue(12.0)  # above Tc of both electrodes
    dialog = Mock(return_value=("", ""))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", dialog)
    warning = Mock()
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", warning)
    window.export_hfss_action.trigger()
    warning.assert_called_once()
    assert "Tc" in warning.call_args.args[2]
    dialog.assert_not_called()
