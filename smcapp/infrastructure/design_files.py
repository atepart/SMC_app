"""Versioned persistence for editable smcapp design parameters."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

from smcapp.domain.circuit import CORNERS, SECTION_TITLES, SECTIONS, LineSection, TransformerSection
from smcapp.domain.dielectrics import (
    LEGACY_ANOD_VOLTAGE_V,
    LEGACY_EPS_ANOD,
    LEGACY_EPS_INS,
    dielectric_stack,
    layers_from_legacy_stack,
)
from smcapp.domain.s21_models import S21Config

DESIGN_FORMAT = "SMCapp Design"
LEGACY_DESIGN_FORMAT = "AOCapp Design"
# Version 2 (WP-044): Mex01/Mex02/Mex03 are lists of elements, the corner
# transformers separate objects. Version 1 (fixed transf_*/msl_* fields) is
# still read.  Version 3 (WP-057, BUG-023 D1): the insulator stack is stored as
# the layers h1, h2, V_anod, ε_i, ε_Al instead of H12/E12/H1/E1; versions 1
# and 2 are converted on load.  Saving always writes version 3.
DESIGN_VERSION = 3
LIST_DESIGN_VERSION = 2
LEGACY_DESIGN_VERSION = 1
SUPPORTED_VERSIONS = (LEGACY_DESIGN_VERSION, LIST_DESIGN_VERSION, DESIGN_VERSION)
# H12/E12/H1/E1 as stored by versions 1 and 2, with the defaults those versions
# used when a file omitted them (h1 = 0.15 µm, h2 = 0.30 µm at 10 V).
DIRECT_DIELECTRIC_DEFAULTS = {"h12_m": 0.465729e-6, "e12": 4.28265, "h1_m": 1.65729e-7, "e1": 4.44084}
# A stored permittivity farther than this from the one rebuilt from the layers is reported.
PERMITTIVITY_TOLERANCE = 1e-4
# Parameters that older files may still contain but that no longer influence
# the calculation.  They are accepted on load and dropped; saving never writes
# them again.  ``f0_ghz``: Mex04 now uses the sweep frequency (WP-046, BUG-023 D2).
RETIRED_PARAMETERS = frozenset({"f0_ghz"})

TRANSFORMER_TYPE, LINE_TYPE = "transformer", "line"
TRANSFORMER_KEYS = ("w1_m", "w2_m", "n_um", "dl_m")
LINE_KEYS = ("width_m", "length_m")

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


def _element_payload(element: TransformerSection | LineSection, *, typed: bool = True) -> dict:
    if isinstance(element, TransformerSection):
        values = {key: getattr(element, key) for key in TRANSFORMER_KEYS}
        return {"type": TRANSFORMER_TYPE, **values} if typed else values
    return {"type": LINE_TYPE, **{key: getattr(element, key) for key in LINE_KEYS}}


def _number(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: значение должно быть числом.")
    return value


def _transformer(payload, where: str, *, typed: bool) -> TransformerSection:
    allowed = {"type", *TRANSFORMER_KEYS} if typed else set(TRANSFORMER_KEYS)
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError(f"{where}: трансформатор задаётся полями {', '.join(TRANSFORMER_KEYS)}.")
    return TransformerSection(*(_number(payload[key], f"{where}, {key}") for key in TRANSFORMER_KEYS))


def _section_element(payload, where: str) -> TransformerSection | LineSection:
    kind = payload.get("type") if isinstance(payload, dict) else None
    if kind == TRANSFORMER_TYPE:
        return _transformer(payload, where, typed=True)
    if kind == LINE_TYPE:
        if set(payload) != {"type", *LINE_KEYS}:
            raise ValueError(f"{where}: линия задаётся полями {', '.join(LINE_KEYS)}.")
        return LineSection(*(_number(payload[key], f"{where}, {key}") for key in LINE_KEYS))
    raise ValueError(f"{where}: тип элемента должен быть {TRANSFORMER_TYPE!r} или {LINE_TYPE!r}.")


def from_v2_parameters(parameters: dict) -> dict:
    """Element lists and corners of a version-2 file as domain objects."""
    result = dict(parameters)
    for section in SECTIONS:
        if section not in parameters:
            raise ValueError(f"В файле дизайна нет списка {section}.")
        items = parameters[section]
        if not isinstance(items, list) or not items:
            raise ValueError(f"{section}: ожидается непустой список элементов.")
        result[section] = tuple(
            _section_element(item, f"{SECTION_TITLES[section]}, позиция {index + 1}")
            for index, item in enumerate(items)
        )
    for corner in CORNERS:
        if corner not in parameters:
            raise ValueError(f"В файле дизайна нет углового трансформатора {corner}.")
        result[corner] = _transformer(parameters[corner], corner, typed=False)
    return result


def from_direct_dielectrics(parameters: dict) -> tuple[dict, list[str]]:
    """Rebuild the insulator layers of a version-1/2 file from its H12/E12/H1/E1.

    ``h1 = H1 − Ha`` and ``h2 = H12 − H1`` at the anodization of those files
    (10 V, ε_i = 4.2, ε_Al = 9.8), so the thicknesses are kept exactly.  The
    permittivities are then rebuilt by the worksheet formula; when a stored one
    differs by more than :data:`PERMITTIVITY_TOLERANCE` the returned notes say
    which values change.
    """
    result = {name: value for name, value in parameters.items() if name not in DIRECT_DIELECTRIC_DEFAULTS}
    stored = {name: parameters.get(name, default) for name, default in DIRECT_DIELECTRIC_DEFAULTS.items()}
    h1, h2 = layers_from_legacy_stack(stored["h1_m"], stored["h12_m"])
    if h1 <= 0 or h2 <= 0:
        raise ValueError(
            f"h1 = {stored['h1_m'] * 1e9:g} nm и h12 = {stored['h12_m'] * 1e9:g} nm из файла старого формата"
            " не раскладываются на слои h1, h2 > 0 при анодировании 10 V."
        )
    result.update(
        ins_h1_m=h1, ins_h2_m=h2, anod_voltage_v=LEGACY_ANOD_VOLTAGE_V, eps_ins=LEGACY_EPS_INS, eps_anod=LEGACY_EPS_ANOD
    )
    stack = dielectric_stack(h1, h2, LEGACY_ANOD_VOLTAGE_V, LEGACY_EPS_INS, LEGACY_EPS_ANOD)
    notes = []
    for name, label, rebuilt in (("e12", "ε₁₂", stack.e12), ("e1", "ε₁", stack.e1)):
        if abs(stored[name] - rebuilt) > PERMITTIVITY_TOLERANCE:
            notes.append(f"{label}: в файле {stored[name]:.5f}, по слоям {rebuilt:.5f}")
    if notes:
        notes.insert(
            0,
            "Файл старого формата хранил H12/ε₁₂/H1/ε₁ напрямую; теперь они считаются из слоёв, как в листе Mathcad: "
            f"h1 = {h1 * 1e9:.4g} nm, h2 = {h2 * 1e9:.4g} nm, V anod = {LEGACY_ANOD_VOLTAGE_V:g} V, "
            f"ε i = {LEGACY_EPS_INS:g}, ε Al = {LEGACY_EPS_ANOD:g}. Изменились проницаемости:",
        )
    return result, notes


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
        parameters = {}
        for item in fields(config):
            value = getattr(config, item.name)
            if item.name in SECTIONS:
                value = [_element_payload(element) for element in value]
            elif item.name in CORNERS:
                value = _element_payload(value, typed=False)
            parameters[item.name] = value
        payload = {"format": DESIGN_FORMAT, "version": DESIGN_VERSION, "parameters": parameters}
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load(self, path: str | Path) -> S21Config:
        """Read and validate one versioned design file.

        A malformed document is reported as ``ValueError`` with a concise
        message suitable for a GUI dialog; filesystem failures stay ``OSError``.
        """
        return self.load_with_notes(path)[0]

    def load_with_notes(self, path: str | Path) -> tuple[S21Config, tuple[str, ...]]:
        """Like :meth:`load`, plus messages about values changed by a format migration."""
        source = Path(path).expanduser()
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Файл дизайна содержит некорректный JSON: {exc.msg}") from exc

        if not isinstance(payload, dict) or payload.get("format") not in (DESIGN_FORMAT, LEGACY_DESIGN_FORMAT):
            raise ValueError("Выбранный файл не является дизайном smcapp.")
        version = payload.get("version")
        if isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
            raise ValueError(f"Версия дизайна не поддерживается: {version!r}.")

        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("В файле дизайна отсутствует объект parameters.")

        parameters = {name: value for name, value in parameters.items() if name not in RETIRED_PARAMETERS}
        plain = {item.name for item in fields(S21Config) if item.name not in SECTIONS and item.name not in CORNERS}
        structured = set(SECTIONS) | set(CORNERS)
        expected = plain | (legacy_field_names() if version == LEGACY_DESIGN_VERSION else structured)
        if version < DESIGN_VERSION:
            # Older files carry H12/E12/H1/E1 instead of the insulator layers.
            layers = {"ins_h1_m", "ins_h2_m", "anod_voltage_v", "eps_ins", "eps_anod"}
            expected = (expected - layers) | set(DIRECT_DIELECTRIC_DEFAULTS)
        unknown = set(parameters) - expected
        if unknown:
            raise ValueError(f"Неизвестные параметры дизайна: {', '.join(sorted(unknown))}.")
        invalid_types = [
            name
            for name, value in parameters.items()
            if name not in structured
            and value is not None
            and (isinstance(value, bool) or not isinstance(value, (int, float)))
        ]
        if invalid_types:
            raise ValueError(f"Параметры должны быть числами: {', '.join(sorted(invalid_types))}.")
        notes: list[str] = []
        try:
            if version < DESIGN_VERSION:
                parameters, notes = from_direct_dielectrics(parameters)
            if version == LEGACY_DESIGN_VERSION:
                parameters = from_legacy_parameters(parameters)
            else:
                parameters = from_v2_parameters(parameters)
            config = S21Config(**parameters)
            config.validate()
            return config, tuple(notes)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Параметры дизайна некорректны: {exc}") from exc
