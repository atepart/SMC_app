"""Design persistence tests independent of the file dialog."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from smcapp.domain.circuit import LineSection, TransformerSection, insert_after, remove_element
from smcapp.domain.s21_models import S21Config
from smcapp.infrastructure.design_files import DESIGN_FORMAT, DESIGN_VERSION, DesignFileService

DATA = Path(__file__).parent / "data"
# Saved by the calculator with fixed transf_*/msl_* fields (commit ccad0c9) as
# an "AOCapp Design" version 1 file, with the retired f0_ghz added by hand.
LEGACY_FILE = DATA / "design_v1_variant.aocdesign"


def _variant() -> S21Config:
    """The configuration of ``LEGACY_FILE`` in the list model (see test_s21_regression)."""
    config = S21Config(s21_freq_start_ghz=200.0, s21_freq_stop_ghz=800.0, s21_freq_step_ghz=50.0)
    t1, line2, t3 = config.mex01
    line4, t5, line6 = config.mex02
    line10, t11, line12, t13 = config.mex03
    return replace(
        config,
        mex01=(t1, replace(line2, length_m=31e-6), replace(t3, w1_m=20e-6)),
        mex02=(replace(line4, width_m=9e-6), replace(t5, dl_m=0.7e-6), line6),
        mex03=(line10, replace(t11, w2_m=19e-6), replace(line12, length_m=22e-6), t13),
    )


def test_design_file_round_trip_keeps_backend_units(tmp_path) -> None:
    service = DesignFileService()
    original = S21Config(block_center_length_um=42.5, d_top_m=0.725e-6, tc_bot_k=8.7)
    path = tmp_path / "mixer.smcdesign"

    assert service.save(path, original) == path
    assert service.load(path) == original

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == DESIGN_FORMAT
    assert payload["format"] == "SMCapp Design"
    assert payload["version"] == DESIGN_VERSION == 2
    assert payload["parameters"]["d_top_m"] == pytest.approx(0.725e-6)


def test_version_2_stores_the_element_lists_in_drawing_order(tmp_path) -> None:
    path = DesignFileService().save(tmp_path / "lists.smcdesign", S21Config())
    parameters = json.loads(path.read_text())["parameters"]
    assert [item["type"] for item in parameters["mex01"]] == ["transformer", "line", "transformer"]
    assert parameters["mex01"][0] == {"type": "transformer", "w1_m": 14e-6, "w2_m": 49e-6, "n_um": 5.0, "dl_m": 1.2e-6}
    assert parameters["mex01"][1] == {"type": "line", "width_m": 50e-6, "length_m": 13e-6}
    assert [item["type"] for item in parameters["mex02"]] == ["line", "transformer", "line"]
    assert [item["type"] for item in parameters["mex03"]] == ["line", "transformer", "line", "transformer"]
    assert parameters["corner_left"] == {"w1_m": 6e-6, "w2_m": 10e-6, "n_um": 1.0, "dl_m": 1.2e-6}
    assert parameters["corner_right"] == {"w1_m": 10e-6, "w2_m": 6e-6, "n_um": 1.0, "dl_m": 1.2e-6}
    assert not any(name.startswith(("transf_", "msl_")) for name in parameters)


def test_changed_composition_round_trips(tmp_path) -> None:
    config = insert_after(remove_element(S21Config(), "MSL3.3"), "MSL1.2")
    config = insert_after(config, "T3.3")  # the former 13, now last of Mex03
    service = DesignFileService()
    loaded = service.load(service.save(tmp_path / "changed.smcdesign", config))
    assert loaded == config
    assert len(loaded.mex01) == 5 and len(loaded.mex03) == 5
    assert [slot.number for slot in loaded.element_slots()][-1] == 21


def test_version_1_file_of_the_former_layout_is_read(tmp_path) -> None:
    payload = json.loads(LEGACY_FILE.read_text())
    assert payload["version"] == 1 and "transf_6_w_end_m" in payload["parameters"]
    assert "f0_ghz" in payload["parameters"]
    service = DesignFileService()

    loaded = service.load(LEGACY_FILE)

    assert loaded == _variant()
    assert loaded.mex01[2] == TransformerSection(20e-6, 18e-6, 3.0, 1.2e-6)  # former T6, Wend = W1
    assert loaded.mex03[1] == TransformerSection(4e-6, 19e-6, 2.0, 0.9e-6)  # former T2, Wstart = W2
    assert loaded.mex02[0] == LineSection(9e-6, 24e-6)  # former MSL7
    saved = json.loads(service.save(tmp_path / "converted.smcdesign", loaded).read_text())
    assert saved["format"] == "SMCapp Design" and saved["version"] == 2
    assert "f0_ghz" not in saved["parameters"]
    assert not any(name.startswith(("transf_", "msl_")) for name in saved["parameters"])
    assert service.load(tmp_path / "converted.smcdesign") == loaded


@pytest.mark.parametrize("suffix", [".aocdesign", ".aocapp", ".json", ".smcdesign"])
def test_legacy_design_loads_with_any_extension_and_marker(tmp_path, suffix) -> None:
    payload = json.loads(LEGACY_FILE.read_text())
    payload["format"] = "SMCapp Design" if suffix == ".smcdesign" else "AOCapp Design"
    # A version-1 file may lack fields added later: the defaults fill them.
    del payload["parameters"]["msl_5_len_m"]
    source = tmp_path / f"legacy{suffix}"
    source.write_text(json.dumps(payload), encoding="utf-8")
    loaded = DesignFileService().load(source)
    assert loaded == _variant()
    assert json.loads(source.read_text()) == payload


@pytest.mark.parametrize("format_name", ["SMCapp Design", "AOCapp Design"])
def test_both_formats_reject_unsupported_version_and_unknown_parameters(tmp_path, format_name) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps({"format": format_name, "version": 3, "parameters": {}}))
    with pytest.raises(ValueError, match="не поддерживается"):
        DesignFileService().load(source)
    source.write_text(json.dumps({"format": format_name, "version": 1, "parameters": {"unknown": 2}}))
    with pytest.raises(ValueError, match="Неизвестные параметры"):
        DesignFileService().load(source)
    # Fixed fields of version 1 are not part of version 2 and vice versa.
    source.write_text(json.dumps({"format": format_name, "version": 1, "parameters": {"mex01": []}}))
    with pytest.raises(ValueError, match="Неизвестные параметры дизайна: mex01"):
        DesignFileService().load(source)


def _v2(tmp_path, **changes):
    path = DesignFileService().save(tmp_path / "base.smcdesign", S21Config())
    payload = json.loads(path.read_text())
    payload["parameters"].update(changes)
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"transf_1_dl_m": 1e-6}, "Неизвестные параметры дизайна: transf_1_dl_m"),
        ({"mex01": []}, "mex01: ожидается непустой список"),
        ({"mex02": {"type": "line"}}, "mex02: ожидается непустой список"),
        ({"mex03": [{"type": "stub", "width_m": 1e-6}]}, "Mex03, позиция 1: тип элемента"),
        (
            {"mex03": [{"type": "line", "width_m": 1e-6}]},
            "некорректны: Mex03, позиция 1: линия задаётся полями width_m, length_m",
        ),
        ({"mex01": [{"type": "line", "width_m": "wide", "length_m": 1e-6}]}, "Mex01, позиция 1, width_m: значение"),
        ({"mex01": [{"type": "transformer", "w1_m": 1e-6, "w2_m": 2e-6}]}, "Mex01, позиция 1: трансформатор задаётся"),
        ({"corner_left": {"width_m": 1e-6, "length_m": 1e-6}}, "corner_left: трансформатор задаётся"),
        ({"mex01": [{"type": "line", "width_m": -1e-6, "length_m": 1e-6}]}, "element 1: sizes must be positive"),
    ],
)
def test_version_2_rejects_broken_element_lists(tmp_path, changes, message) -> None:
    with pytest.raises(ValueError, match=message):
        DesignFileService().load(_v2(tmp_path, **changes))


def test_version_2_without_a_section_is_rejected(tmp_path) -> None:
    path = _v2(tmp_path)
    payload = json.loads(path.read_text())
    del payload["parameters"]["mex02"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="нет списка mex02"):
        DesignFileService().load(path)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"format": "something else", "version": DESIGN_VERSION}, "не является дизайном"),
        ({"format": DESIGN_FORMAT, "version": 999, "parameters": {}}, "не поддерживается"),
        ({"format": DESIGN_FORMAT, "version": True, "parameters": {}}, "не поддерживается"),
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
