"""Versioned persistence for editable smcapp design parameters."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

from smcapp.domain.circuit import CORNERS, SECTIONS, LineSection, TransformerSection, composition
from smcapp.domain.s21_models import S21Config

DESIGN_FORMAT = "SMCapp Design"
LEGACY_DESIGN_FORMAT = "AOCapp Design"
DESIGN_VERSION = 1
# Parameters that older files may still contain but that no longer influence
# the calculation.  They are accepted on load and dropped; saving never writes
# them again.  ``f0_ghz``: Mex04 now uses the sweep frequency (WP-046, BUG-023 D2).
RETIRED_PARAMETERS = frozenset({"f0_ghz"})

# Version 1 stored every element as fixed fields: transformers ``transf_1..7``
# (Wstart on the SIS side, Wend on the FFO side, dwdl, dl) and lines
# ``msl_4..8`` (width, len). Their places in drawing order:
LEGACY_LAYOUT = {
    "mex01": ("transf_7", "msl_8", "transf_6"),
    "mex02": ("msl_7", "transf_5", "msl_6"),
    "corner_left": "transf_4",
    "corner_right": "transf_3",
    "mex03": ("msl_5", "transf_2", "msl_4", "transf_1"),
}
LEGACY_SUFFIXES = {
    "transf": ("w_start_m", "w_end_m", "dwdl_um", "dl_m"),
    "msl": ("width_m", "len_m"),
}


def legacy_field_names() -> frozenset[str]:
    names = set()
    for value in LEGACY_LAYOUT.values():
        for prefix in (value,) if isinstance(value, str) else value:
            names.update(f"{prefix}_{suffix}" for suffix in LEGACY_SUFFIXES[prefix.split("_")[0]])
    return frozenset(names)


def _legacy_element(default, prefix: str, values: dict):
    """One element from version-1 fields; a missing field keeps *default*."""
    if prefix.startswith("transf_"):
        mapping = {"w2_m": "w_start_m", "w1_m": "w_end_m", "n_um": "dwdl_um", "dl_m": "dl_m"}
    else:
        mapping = {"width_m": "width_m", "length_m": "len_m"}
    changes = {attr: values[f"{prefix}_{suffix}"] for attr, suffix in mapping.items() if f"{prefix}_{suffix}" in values}
    return replace(default, **changes)


def from_legacy_parameters(parameters: dict) -> dict:
    """Turn version-1 ``transf_*``/``msl_*`` fields into Mex lists and corners."""
    defaults = S21Config()
    result = {name: value for name, value in parameters.items() if name not in legacy_field_names()}
    for target, layout in LEGACY_LAYOUT.items():
        if isinstance(layout, str):
            result[target] = _legacy_element(getattr(defaults, target), layout, parameters)
        else:
            result[target] = tuple(
                _legacy_element(default, prefix, parameters)
                for default, prefix in zip(getattr(defaults, target), layout)
            )
    return result


def to_legacy_parameters(config: S21Config) -> dict:
    """Version-1 fields of *config*; only the default composition fits them."""
    if composition(config) != composition(S21Config()):
        raise ValueError("Состав элементов отличается от исходного: формат файла версии 1 его не поддерживает.")
    result = {}
    for item in fields(config):
        if item.name in SECTIONS or item.name in CORNERS:
            continue
        result[item.name] = getattr(config, item.name)
    for target, layout in LEGACY_LAYOUT.items():
        elements = (getattr(config, target),) if isinstance(layout, str) else getattr(config, target)
        prefixes = (layout,) if isinstance(layout, str) else layout
        for element, prefix in zip(elements, prefixes):
            if isinstance(element, TransformerSection):
                values = (element.w2_m, element.w1_m, element.n_um, element.dl_m)
            else:
                assert isinstance(element, LineSection)
                values = (element.width_m, element.length_m)
            for suffix, value in zip(LEGACY_SUFFIXES[prefix.split("_")[0]], values):
                result[f"{prefix}_{suffix}"] = value
    return result


class DesignFileService:
    """Serialize a complete :class:`S21Config` without UI-specific state.

    The explicit format marker and version keep design files distinguishable
    from HFSS/experiment tables and give future migrations a stable boundary.
    Values are stored in backend SI units; presentation scales such as µm are
    applied only by the UI.
    """

    def save(self, path: str | Path, config: S21Config) -> Path:
        """Write *config* atomically enough for a normal desktop save."""
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": DESIGN_FORMAT,
            "version": DESIGN_VERSION,
            "parameters": to_legacy_parameters(config),
        }
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load(self, path: str | Path) -> S21Config:
        """Read and validate one versioned design file.

        A malformed document is reported as ``ValueError`` with a concise
        message suitable for a GUI dialog; filesystem failures stay ``OSError``.
        """
        source = Path(path).expanduser()
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Файл дизайна содержит некорректный JSON: {exc.msg}") from exc

        if not isinstance(payload, dict) or payload.get("format") not in (DESIGN_FORMAT, LEGACY_DESIGN_FORMAT):
            raise ValueError("Выбранный файл не является дизайном smcapp.")
        if payload.get("version") != DESIGN_VERSION:
            raise ValueError(f"Версия дизайна не поддерживается: {payload.get('version')!r}.")

        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("В файле дизайна отсутствует объект parameters.")

        parameters = {name: value for name, value in parameters.items() if name not in RETIRED_PARAMETERS}
        expected = {item.name for item in fields(S21Config) if item.name not in SECTIONS and item.name not in CORNERS}
        expected |= legacy_field_names()
        unknown = set(parameters) - expected
        if unknown:
            raise ValueError(f"Неизвестные параметры дизайна: {', '.join(sorted(unknown))}.")
        invalid_types = [
            name
            for name, value in parameters.items()
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)))
        ]
        if invalid_types:
            raise ValueError(f"Параметры должны быть числами: {', '.join(sorted(invalid_types))}.")
        try:
            config = S21Config(**from_legacy_parameters(parameters))
            config.validate()
            return config
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Параметры дизайна некорректны: {exc}") from exc
