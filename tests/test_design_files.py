"""Design persistence tests independent of the file dialog."""

from __future__ import annotations

import json

import pytest

from aocapp.domain.s21_models import S21Config
from aocapp.infrastructure.design_files import DESIGN_FORMAT, DESIGN_VERSION, DesignFileService


def test_design_file_round_trip_keeps_backend_units(tmp_path) -> None:
    service = DesignFileService()
    original = S21Config(block_center_length_um=42.5, d_top_m=0.725e-6, tc_bot_k=8.7)
    path = tmp_path / "mixer.aocdesign"

    assert service.save(path, original) == path
    assert service.load(path) == original

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == DESIGN_FORMAT
    assert payload["version"] == DESIGN_VERSION
    assert payload["parameters"]["d_top_m"] == pytest.approx(0.725e-6)


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
    path = tmp_path / "broken.aocdesign"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        DesignFileService().load(path)
