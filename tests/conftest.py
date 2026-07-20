"""Shared test environment configuration."""

from __future__ import annotations

import importlib
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = importlib.import_module("PySide6.QtCore")
_SETTINGS_DIRECTORY = tempfile.TemporaryDirectory()
QtCore.QCoreApplication.setOrganizationName("AOCappTests")
QtCore.QCoreApplication.setApplicationName("AOCappTests")
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(
    QtCore.QSettings.Format.IniFormat,
    QtCore.QSettings.Scope.UserScope,
    _SETTINGS_DIRECTORY.name,
)
