"""Versioned persistence for editable AOCapp design parameters."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from aocapp.domain.s21_models import S21Config

DESIGN_FORMAT = "AOCapp Design"
DESIGN_VERSION = 1


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
            "parameters": asdict(config),
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

        if not isinstance(payload, dict) or payload.get("format") != DESIGN_FORMAT:
            raise ValueError("Выбранный файл не является дизайном AOCapp.")
        if payload.get("version") != DESIGN_VERSION:
            raise ValueError(f"Версия дизайна не поддерживается: {payload.get('version')!r}.")

        parameters = payload.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("В файле дизайна отсутствует объект parameters.")

        expected = {item.name for item in fields(S21Config)}
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
            config = S21Config(**parameters)
            config.validate()
            return config
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Параметры дизайна некорректны: {exc}") from exc
