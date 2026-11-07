"""Preserve desktop preferences when upgrading from AOCapp to smcapp."""

from PySide6.QtCore import QSettings


def migrate_legacy_settings(legacy: QSettings, current: QSettings) -> None:
    """Copy missing preferences once, without replacing newer user choices."""
    marker = "Migration/aocapp_imported"
    if current.contains(marker):
        return
    for key in legacy.allKeys():
        if not current.contains(key):
            current.setValue(key, legacy.value(key))
    current.setValue(marker, True)
    current.sync()
