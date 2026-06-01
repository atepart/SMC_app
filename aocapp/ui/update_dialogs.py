"""Dialogs and worker for GitHub release selection."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from aocapp.infrastructure.updater import list_releases


class FetchReleasesWorker(QtCore.QObject):
    finished = QtCore.Signal(list)
    error = QtCore.Signal(str)
    status = QtCore.Signal(str)

    def __init__(self, repo_slug: str, limit: int = 10) -> None:
        super().__init__()
        self._repo_slug = repo_slug
        self._limit = limit

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.status.emit("Подключение к GitHub API...")
            releases = list_releases(self._repo_slug, self._limit)
            if not releases:
                self.error.emit("Не удалось получить список релизов")
                return
            available = sum(
                1 for release in releases if getattr(release, "asset", None) and release.asset.download_url
            )
            self.status.emit(f"Получено релизов: {len(releases)}; для вашей системы: {available}")
            self.finished.emit(releases)
        except Exception as exc:
            self.error.emit(str(exc))


class ReleaseDetailDialog(QtWidgets.QDialog):
    def __init__(self, release, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Релиз {release.tag}")
        self.resize(660, 430)

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel()
        parts = [f"<b>{release.tag}</b>"]
        if getattr(release, "published_at", None):
            parts.append(f"от {release.published_at}")
        if getattr(release, "prerelease", False):
            parts.append("(pre-release)")
        if getattr(release, "asset", None):
            parts.append(f"<br>Файл: {release.asset.name}")
        header.setText(" ".join(parts))
        layout.addWidget(header)

        description = QtWidgets.QTextEdit()
        description.setReadOnly(True)
        description.setPlainText(release.body or "Описание отсутствует.")
        layout.addWidget(description)

        buttons = QtWidgets.QDialogButtonBox()
        choose_button = buttons.addButton("Выбрать", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not getattr(release, "asset", None) or not release.asset.download_url:
            choose_button.setEnabled(False)


class ReleasePickerDialog(QtWidgets.QDialog):
    def __init__(self, releases: list, parent=None, current_version: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Выбор версии")
        self.resize(680, 540)
        self._releases = releases
        self._current_version = current_version
        self.selected = None

        layout = QtWidgets.QVBoxLayout(self)

        if current_version:
            current_label = QtWidgets.QLabel(f"Текущая версия: {current_version}")
            current_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(current_label)

        self.listw = QtWidgets.QListWidget()
        self.listw.itemDoubleClicked.connect(self._open_detail)
        self.listw.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self.listw)

        self.desc = QtWidgets.QTextEdit()
        self.desc.setReadOnly(True)
        self.desc.setFixedHeight(160)
        layout.addWidget(self.desc)

        info = QtWidgets.QLabel(
            "Выберите релиз. Если для текущей ОС и архитектуры нет подходящего архива, строка будет недоступна."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.detail_button = buttons.addButton("Подробнее", QtWidgets.QDialogButtonBox.ActionRole)
        self.detail_button.clicked.connect(self._open_detail)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()
        self._on_selection_changed(self.listw.currentItem(), None)

    def _populate(self) -> None:
        self.listw.clear()
        current_row = 0
        for release in self._releases:
            text = release.tag
            if getattr(release, "published_at", None):
                text += f"  -  {release.published_at}"
            if getattr(release, "prerelease", False):
                text += "  [pre-release]"
            if self._is_current(release.tag):
                text += "  -  установлена"
            if getattr(release, "asset", None):
                text += f"  -  {release.asset.name}"
            else:
                text += "  -  нет файла для этой системы"

            item = QtWidgets.QListWidgetItem(text)
            if not getattr(release, "asset", None) or not release.asset.download_url:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
            if self._is_current(release.tag):
                item.setBackground(QtCore.Qt.GlobalColor.yellow)
                item.setForeground(QtCore.Qt.GlobalColor.black)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                current_row = self.listw.count()
            item.setData(QtCore.Qt.UserRole, release)
            self.listw.addItem(item)

        if self.listw.count() > 0:
            self.listw.setCurrentRow(current_row)

    def _on_accept(self) -> None:
        item = self.listw.currentItem()
        if not item or not (item.flags() & QtCore.Qt.ItemIsEnabled):
            return
        self.selected = item.data(QtCore.Qt.UserRole)
        self.accept()

    def _on_selection_changed(self, current, previous) -> None:
        release = current.data(QtCore.Qt.UserRole) if current else None
        if release is None:
            self.desc.setPlainText("")
            self.detail_button.setEnabled(False)
            return
        self.detail_button.setEnabled(bool(current.flags() & QtCore.Qt.ItemIsEnabled))
        self.desc.setPlainText(getattr(release, "body", "") or "Описание отсутствует.")
        self.desc.moveCursor(QtGui.QTextCursor.Start)

    def _open_detail(self, item=None) -> None:
        if item is None:
            item = self.listw.currentItem()
        if not item or not (item.flags() & QtCore.Qt.ItemIsEnabled):
            return
        release = item.data(QtCore.Qt.UserRole)
        dialog = ReleaseDetailDialog(release, parent=self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.selected = release
            self.accept()

    def _is_current(self, tag: str) -> bool:
        if not self._current_version:
            return False

        def normalize(value: str) -> str:
            return value.lower().lstrip("v").strip()

        return normalize(tag) == normalize(self._current_version)
