"""Shared test environment configuration."""

from __future__ import annotations

import importlib
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = importlib.import_module("PySide6.QtCore")
QtWidgets = importlib.import_module("PySide6.QtWidgets")
Shiboken = importlib.import_module("shiboken6")
_SETTINGS_DIRECTORY = tempfile.TemporaryDirectory()
# Keep the native QApplication wrapper alive for the whole test session.
# Individual QtAds windows schedule deferred child deletion; allowing the last
# local ``app`` variable to be collected between fixtures can otherwise abort
# the process after all assertions have already passed.
_TEST_APPLICATION = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
QtCore.QCoreApplication.setOrganizationName("AOCappTests")
QtCore.QCoreApplication.setApplicationName("AOCappTests")
QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
QtCore.QSettings.setPath(
    QtCore.QSettings.Format.IniFormat,
    QtCore.QSettings.Scope.UserScope,
    _SETTINGS_DIRECTORY.name,
)


def pytest_sessionfinish(session, exitstatus) -> None:
    """Destroy deferred QtAds objects before QApplication itself.

    PySide's interpreter-shutdown order is otherwise undefined, and QtAds or
    pyqtgraph children may receive destruction callbacks after their native
    application has already gone away.  The explicit order keeps a successful
    test session from ending in ``SIGABRT``.
    """
    del session, exitstatus
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
    _TEST_APPLICATION.processEvents()
    _TEST_APPLICATION.quit()
    Shiboken.delete(_TEST_APPLICATION)
