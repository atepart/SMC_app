"""Dialogs and worker for GitHub release selection and downloading."""

from __future__ import annotations

import os
import tempfile
import zipfile
import time

import requests
from PySide6 import QtCore, QtGui, QtWidgets

from aocapp.infrastructure.updater import list_releases


class DownloadReleaseWorker(QtCore.QThread):
    finished_download = QtCore.Signal(str)  # Returns path to extracted source directory
    error = QtCore.Signal(str)
    progress = QtCore.Signal(int, int, float)  # downloaded, total, speed_mbps
    status = QtCore.Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            self.status.emit("Скачивание обновления...")
            resp = requests.get(self._url, stream=True, timeout=10)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))

            temp_dir = tempfile.mkdtemp(prefix="aocapp_update_")
            zip_path = os.path.join(temp_dir, "update.zip")

            downloaded = 0
            start_time = time.time()
            last_emit_time = start_time

            with open(zip_path, "wb") as f:
                # 128KB chunk for faster download
                for chunk in resp.iter_content(chunk_size=131072):
                    if self.isInterruptionRequested():
                        self.error.emit("Загрузка отменена")
                        return
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        # Update progress every ~0.1s
                        if (now - last_emit_time > 0.1) or (total > 0 and downloaded >= total):
                            elapsed = now - start_time
                            speed_mbps = (downloaded / 1024 / 1024) / elapsed if elapsed > 0 else 0
                            self.progress.emit(downloaded, total, speed_mbps)
                            last_emit_time = now

            self.status.emit("Распаковка обновления...")
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
                # Restore permissions for executable files (specifically for macOS .app bundles)
                for info in zf.infolist():
                    extracted_path = os.path.join(extract_dir, info.filename)
                    mode = info.external_attr >> 16
                    if mode:
                        os.chmod(extracted_path, mode)

            # Find the root of the app in the extracted folder
            items = os.listdir(extract_dir)
            if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
                src_dir = os.path.join(extract_dir, items[0])
            else:
                src_dir = extract_dir

            self.finished_download.emit(src_dir)
        except Exception as e:
            self.error.emit(str(e))


class FetchReleasesWorker(QtCore.QThread):
    finished_fetch = QtCore.Signal(list)
    error = QtCore.Signal(str)
    status = QtCore.Signal(str)

    def __init__(self, repo_slug: str, limit: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._repo_slug = repo_slug
        self._limit = limit

    def run(self) -> None:
        try:
            self.status.emit("Подключение к GitHub API...")
            releases = list_releases(self._repo_slug, self._limit)
            if self.isInterruptionRequested():
                return
            if not releases:
                self.error.emit("Не удалось получить список релизов")
                return
            available = sum(
                1 for release in releases if getattr(release, "asset", None) and release.asset.download_url
            )
            self.status.emit(f"Получено релизов: {len(releases)}; для вашей системы: {available}")
            self.finished_fetch.emit(releases)
        except Exception as exc:
            if not self.isInterruptionRequested():
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
            current_label.setStyleSheet("font-weight: bold; color: #d35400;")
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

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        self.detail_button = buttons.addButton("Подробнее", QtWidgets.QDialogButtonBox.ActionRole)
        self.manual_button = buttons.addButton("Скачать вручную", QtWidgets.QDialogButtonBox.ActionRole)
        self.auto_button = buttons.addButton("Обновить автоматически", QtWidgets.QDialogButtonBox.AcceptRole)

        self.detail_button.clicked.connect(self._open_detail)
        self.manual_button.clicked.connect(self._on_manual)
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
                current_row = self.listw.count() - 1
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

    def _on_manual(self) -> None:
        item = self.listw.currentItem()
        if not item or not (item.flags() & QtCore.Qt.ItemIsEnabled):
            return
        self.selected = item.data(QtCore.Qt.UserRole)
        self.done(QtWidgets.QDialog.DialogCode.Accepted + 1)  # Custom return code for manual

    def _on_selection_changed(self, current, previous) -> None:
        release = current.data(QtCore.Qt.UserRole) if current else None
        if release is None:
            self.desc.setPlainText("")
            self.detail_button.setEnabled(False)
            self.manual_button.setEnabled(False)
            self.auto_button.setEnabled(False)
            return
        has_asset = bool(current.flags() & QtCore.Qt.ItemIsEnabled)
        self.detail_button.setEnabled(has_asset)
        self.manual_button.setEnabled(has_asset)
        self.auto_button.setEnabled(has_asset)
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
