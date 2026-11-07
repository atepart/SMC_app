"""Preference migration preserves both old layout data and new user choices."""

from PySide6.QtCore import QByteArray, QSettings

from smcapp.infrastructure.settings import migrate_legacy_settings


def test_migration_copies_missing_settings_once_without_overwriting(tmp_path) -> None:
    legacy = QSettings(str(tmp_path / "old.ini"), QSettings.IniFormat)
    current = QSettings(str(tmp_path / "new.ini"), QSettings.IniFormat)
    legacy.setValue("Theme/name", "dark")
    legacy.setValue("DockManager/state", QByteArray(b"saved-layout"))
    legacy.setValue("Files/last_directory", "/old/designs")
    current.setValue("Theme/name", "light")

    migrate_legacy_settings(legacy, current)
    assert current.value("Theme/name") == "light"
    assert current.value("DockManager/state") == QByteArray(b"saved-layout")
    assert current.value("Files/last_directory") == "/old/designs"
    assert legacy.value("Theme/name") == "dark"

    current.remove("Files/last_directory")
    migrate_legacy_settings(legacy, current)
    assert not current.contains("Files/last_directory")
