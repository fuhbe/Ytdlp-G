"""Offline conversion dialog with a cancellable process for local media."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..media import PROFILES
from ..tasks import Task


def profile_combo(tr, selected):
    combo = QComboBox()
    for name in PROFILES:
        combo.addItem(tr("profile_" + name), name)
    combo.setCurrentIndex(max(0, combo.findData(selected)))
    return combo


class OfflineDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.t = parent.tr
        self.setWindowTitle(self.t("offline_title"))
        self.setAcceptDrops(True)
        self.resize(540, 430)
        self.task = None
        self.failed = []
        self.completed = set()
        self.inputs = []
        self.diag = []
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setAcceptDrops(False)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        layout.addLayout(row)

        def button(key, callback, where):
            btn = QPushButton(self.t(key))
            btn.clicked.connect(callback)
            where.addWidget(btn)
            return btn

        self.files_btn = button(
            "offline_files",
            lambda: self.add(QFileDialog.getOpenFileNames(self, self.windowTitle())[0]),
            row,
        )
        self.folder_btn = button(
            "offline_folder", lambda: self.add([QFileDialog.getExistingDirectory(self)]), row
        )
        self.recursive = QCheckBox(self.t("offline_recursive"))
        row.addWidget(self.recursive)
        self.profile = profile_combo(self.t, parent.profile.currentData())
        layout.addWidget(self.profile)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.profile.currentIndexChanged.connect(self.describe)
        self.describe()
        self.skip = QCheckBox(self.t("offline_skip"))
        self.skip.setChecked(True)
        layout.addWidget(self.skip)
        dest = QHBoxLayout()
        layout.addLayout(dest)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText(self.t("destination"))
        dest.addWidget(self.destination)
        self.browse = button("browse", self.choose_destination, dest)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.start_btn = button("offline_start", lambda: self.start(False), actions)
        self.retry_btn = button("retry", lambda: self.start(True), actions)
        self.copy_btn = button(
            "lite_copy",
            lambda: QApplication.clipboard().setText(json.dumps(self.diag, indent=2)),
            actions,
        )
        self.cancel_btn = button("cancel", self.stop, actions)
        self.busy(False)

    def describe(self):
        self.hint.setText(self.t("hint_" + self.profile.currentData()))

    def add(self, paths):
        for name in paths:
            if name and name not in self.inputs:
                self.inputs.append(name)
                self.list.addItem(name)
                if not self.destination.text():
                    path = Path(name)
                    self.destination.setText(
                        str((path if path.is_dir() else path.parent) / "Convertidos")
                    )
        self.busy(False)

    def choose_destination(self):
        directory = QFileDialog.getExistingDirectory(self)
        if directory:
            self.destination.setText(directory)

    def dragEnterEvent(self, event):
        if not self.task and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.task:
            self.add([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def busy(self, active):
        for w in (
            self.files_btn,
            self.folder_btn,
            self.skip,
            self.browse,
            self.profile,
            self.destination,
            self.recursive,
        ):
            w.setEnabled(not active)
        self.start_btn.setEnabled(bool(self.inputs) and not active)
        self.cancel_btn.setEnabled(active)
        self.retry_btn.setEnabled(bool(self.failed) and not active)
        self.copy_btn.setEnabled(bool(self.diag) and not active)

    def start(self, retry):
        if self.task or not self.destination.text().strip():
            return
        if not retry:
            self.completed.clear()
            self.diag.clear()
        if retry:
            self.request = self.request | {
                "inputs": list(self.failed),
                "exclude": list(self.completed),
            }
        else:
            self.request = {
                "inputs": list(self.inputs),
                "destination": self.destination.text(),
                "profile": self.profile.currentData(),
                "recursive": self.recursive.isChecked(),
                "skip": self.skip.isChecked(),
                "exclude": list(self.completed),
            }
        self.failed = []
        self.progress.setRange(0, 0)
        self.task = Task("offline_batch", self.request, self)
        self.task.progress.connect(self.update_progress)
        self.task.result.connect(self.result)
        self.task.error.connect(self.error)
        self.task.finished.connect(self.done)
        self.busy(True)
        self.task.start()

    def update_progress(self, e):
        total = e["total_items"]
        i = e["index"]
        fraction = e.get("progress", 0) / 100
        if e["status"] in {"completed", "skipped"}:
            self.completed.add(e["source"])
            fraction = 1
        self.progress.setRange(0, 100)
        self.progress.setValue(int(100 * (i - 1 + fraction) / total))
        self.status.setText(f"{i}/{total} · {self.t(e['status'])} · {e['name']}")

    def result(self, r):
        self.failed = [f["source"] for f in r["failures"]]
        self.diag = [f["diagnostic"] for f in r["failures"]]
        self.progress.setValue(100)
        self.status.setText(
            self.t(
                "offline_done",
                saved=len(r["files"]),
                skipped=len(r["skipped"]),
                failed=len(self.failed),
            )
        )
        for f in r["failures"]:
            self.list.addItem(f"{Path(f['source']).name} · {self.t(f['diagnostic']['code'])}")

    def error(self, e):
        self.failed = self.request["inputs"]
        self.diag = [e]
        self.status.setText(self.t(e["code"]))

    def done(self):
        self.task.deleteLater()
        self.task = None
        self.busy(False)

    def stop(self):
        if self.task:
            self.task.cancel()

    def reject(self):
        if self.task:
            self.stop()
            return
        super().reject()
