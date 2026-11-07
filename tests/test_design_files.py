"""Design persistence tests independent of the file dialog."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.design_files import DESIGN_FORMAT, DESIGN_VERSION, DesignFileService


def test_design_file_round_trip_keeps_backend_units(tmp_path) -> None:
    service = DesignFileService()
    original = S21Config(block_center_length_um=42.5, d_top_m=0.725e-6, tc_bot_k=8.7)
    path = tmp_path / "mixer.smcdesign"

    assert service.save(path, original) == path
    assert service.load(path) == original

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == DESIGN_FORMAT
    assert payload["format"] == "SMCapp Design"
    assert payload["version"] == DESIGN_VERSION
    assert payload["parameters"]["d_top_m"] == pytest.approx(0.725e-6)


@pytest.mark.parametrize("suffix", [".aocdesign", ".aocapp", ".json"])
def test_legacy_design_loads_and_saves_as_new_format(tmp_path, suffix) -> None:
    original = S21Config(d_top_m=0.725e-6, tc_bot_k=8.7, transf_7_dl_m=0.125e-6)
    source = tmp_path / f"legacy{suffix}"
    payload = {"format": "AOCapp Design", "version": 1, "parameters": asdict(original)}
    source.write_text(json.dumps(payload), encoding="utf-8")
    service = DesignFileService()
    loaded = service.load(source)
    assert loaded == original
    destination = service.save(tmp_path / "converted.smcdesign", loaded)
    assert service.load(destination) == original
    assert json.loads(destination.read_text())["format"] == "SMCapp Design"
    assert json.loads(source.read_text()) == payload


@pytest.mark.parametrize("format_name", ["SMCapp Design", "AOCapp Design"])
def test_both_formats_reject_unsupported_version_and_unknown_parameters(tmp_path, format_name) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps({"format": format_name, "version": 2, "parameters": {}}))
    with pytest.raises(ValueError, match="не поддерживается"):
        DesignFileService().load(source)
    source.write_text(json.dumps({"format": format_name, "version": 1, "parameters": {"unknown": 2}}))
    with pytest.raises(ValueError, match="Неизвестные параметры"):
        DesignFileService().load(source)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"format": "something else", "version": DESIGN_VERSION}, "не является дизайном"),
        ({"format": DESIGN_FORMAT, "version": 999, "parameters": {}}, "не поддерживается"),
        ({"format": DESIGN_FORMAT, "version": DESIGN_VERSION}, "parameters"),
        (
            {"format": DESIGN_FORMAT, "version": DESIGN_VERSION, "parameters": {"temperature_k": "warm"}},
            "должны быть числами",
        ),
    ],
)
def test_design_file_rejects_wrong_schema(tmp_path, payload, message) -> None:
    path = tmp_path / "broken.smcdesign"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        DesignFileService().load(path)
