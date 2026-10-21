"""Compact Aero-inspired UI: link, native quality, destination and two outputs."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..i18n import Translator
from ..paths import validate_url
from ..tasks import Task


class AeroTitle(QFrame):
    minimize = Signal()
    close_window = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("aeroTitle")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 5, 0)
        icon = QLabel()
        icon.setPixmap(parent.windowIcon().pixmap(22, 22))
        layout.addWidget(icon)
        layout.addWidget(QLabel("Ytdlp-G"))
        layout.addStretch()
        minimize = QPushButton("—")
        minimize.setAccessibleName(parent.tr("lite_minimize"))
        minimize.setObjectName("minimize")
        minimize.setFixedSize(30, 24)
        minimize.clicked.connect(self.minimize.emit)
        close = QPushButton("×")
        close.setAccessibleName(parent.tr("quit"))
        close.setObjectName("closeButton")
        close.setFixedSize(42, 24)
        close.clicked.connect(self.close_window.emit)
        layout.addWidget(minimize)
        layout.addWidget(close)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()


class LiteWindow(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.tr = Translator(settings.values["language"])
        self.tasks = set()
        self.current_task = None
        self.analysis = None
        self.analysis_url = ""
        self.last_result = None
        self.smoke_mode = False
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(f"Ytdlp-G {__version__}")
        self.setWindowIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "app.ico")))
        self.setFixedSize(600, 440)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        title = AeroTitle(self)
        title.minimize.connect(self.showMinimized)
        title.close_window.connect(self.close)
        outer.addWidget(title)
        body = QFrame()
        body.setObjectName("body")
        outer.addWidget(body, 1)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(9)
        top = QHBoxLayout()
        heading = self.text("lite_heading")
        heading.setObjectName("heading")
        top.addWidget(heading, 1)
        self.language = QComboBox()
        for code, text in (("pt-BR", "PT-BR"), ("en", "EN"), ("es", "ES")):
            self.language.addItem(text, code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.tr.language)))
        self.language.setFixedWidth(78)
        self.language.currentIndexChanged.connect(self.change_language)
        top.addWidget(self.language)
        layout.addLayout(top)
        link_row = QHBoxLayout()
        self.url = QLineEdit()
        self.tr.bind(self.url.setPlaceholderText, "lite_url_hint")
        self.tr.bind(self.url.setAccessibleName, "url")
        self.url.textChanged.connect(self.invalidate)
        self.url.returnPressed.connect(self.analyze)
        link_row.addWidget(self.url, 1)
        self.paste = self.button(
            "paste", lambda: self.url.setText(QApplication.clipboard().text().strip())
        )
        self.analyze_button = self.button("analyze", self.analyze)
        link_row.addWidget(self.paste)
        link_row.addWidget(self.analyze_button)
        layout.addLayout(link_row)
        self.summary = QLabel(self.tr("lite_instruction"))
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setFixedHeight(40)
        layout.addWidget(self.summary)
        mode_row = QHBoxLayout()
        self.kind = QComboBox()
        for code, key in (("video", "video"), ("audio", "audio")):
            index = self.kind.count()
            self.kind.addItem(self.tr(key), code)
            self.tr.bind(lambda text, i=index: self.kind.setItemText(i, text), key)
        self.kind.setCurrentIndex(1 if settings.values["options"]["kind"] == "audio" else 0)
        self.kind.currentIndexChanged.connect(self.refresh_choices)
        mode_row.addWidget(self.text("kind"))
        mode_row.addWidget(self.kind, 1)
        self.output = QComboBox()
        for code, key in (("normal", "normal"), ("zip", "zip")):
            index = self.output.count()
            self.output.addItem(self.tr(key), code)
            self.tr.bind(lambda text, i=index: self.output.setItemText(i, text), key)
        self.output.setCurrentIndex(1 if settings.values["options"]["output_mode"] == "zip" else 0)
        mode_row.addWidget(self.output, 1)
        layout.addLayout(mode_row)
        quality_row = QHBoxLayout()
        quality_row.addWidget(self.text("quality"))
        self.quality = QComboBox()
        self.quality.setEnabled(False)
        self.tr.bind(self.quality.setAccessibleName, "quality")
        self.quality.currentIndexChanged.connect(self.update_download_enabled)
        quality_row.addWidget(self.quality, 1)
        layout.addLayout(quality_row)
        notice = self.text("lite_available_notice")
        notice.setWordWrap(True)
        notice.setObjectName("hint")
        layout.addWidget(notice)
        destination = QHBoxLayout()
        self.destination = QLineEdit(settings.values["destination"])
        self.tr.bind(self.destination.setAccessibleName, "destination")
        destination.addWidget(self.text("lite_folder"))
        destination.addWidget(self.destination, 1)
        self.browse = self.button("browse", self.choose_folder)
        destination.addWidget(self.browse)
        layout.addLayout(destination)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel(self.tr("ready"))
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(32)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.open_button = self.button("open_folder", self.open_folder)
        self.cancel_button = self.button("cancel", self.cancel)
        self.cancel_button.setEnabled(False)
        self.download_button = self.button("download", self.start_download)
        self.download_button.setObjectName("downloadButton")
        self.download_button.setEnabled(False)
        actions.addWidget(self.open_button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.download_button)
        layout.addLayout(actions)
        self.tr.changed.connect(self.retranslate)
        self.setStyleSheet("""
            QWidget {font-family:'Segoe UI','DejaVu Sans';font-size:12px;color:#18354c;}
            LiteWindow {background:#9fc8e4;border:1px solid #426e8c;border-radius:7px;}
            QFrame#aeroTitle {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #e5f4ff,stop:0.45 #afcee7,stop:0.5 #8cb7d9,stop:1 #b8d9f0);border-bottom:1px solid #7197b5;}
            QFrame#aeroTitle QLabel {font-size:14px;font-weight:600;color:#17334b;}
            QFrame#body {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f7fcff,stop:0.6 #edf5fb,stop:1 #dcebf6);}
            QLabel#heading {font-size:18px;color:#1b4e73;}
            QLabel#hint {font-size:11px;color:#49667c;}
            QLineEdit,QComboBox {background:white;border:1px solid #99b0c1;border-radius:3px;padding:6px;min-height:16px;selection-background-color:#4c9cda;}
            QComboBox QAbstractItemView {background:#ffffff;color:#18354c;border:1px solid #8ca7bb;selection-background-color:#246da4;selection-color:#ffffff;outline:0;}
            QComboBox QAbstractItemView::item {background:#ffffff;color:#18354c;min-height:24px;padding:3px 6px;}
            QComboBox QAbstractItemView::item:selected,QComboBox QAbstractItemView::item:hover {background:#246da4;color:#ffffff;}
            QLineEdit:focus,QComboBox:focus {border:1px solid #2384c2;}
            QPushButton {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:0.48 #eff6fb,stop:0.5 #deebf4,stop:1 #e5f1f9);border:1px solid #8ca7bb;border-radius:4px;padding:6px 10px;min-height:16px;}
            QPushButton:hover {border-color:#3684b5;background:#e5f5ff;}
            QPushButton:focus {border:2px solid #388aba;}
            QPushButton:disabled {color:#8093a1;border-color:#bdcbd5;}
            QPushButton#downloadButton {border-color:#4b8aaf;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #effaff,stop:0.48 #c5e7fa,stop:0.5 #91c8e8,stop:1 #d2eefc);font-weight:600;}
            QPushButton#closeButton {color:white;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ecb4a8,stop:0.48 #cf7765,stop:0.5 #b9442c,stop:1 #d2735c);border-color:#976454;padding:0;font-size:19px;}
            QPushButton#minimize {padding:0;border-radius:3px;font-size:15px;}
            QProgressBar {background:#f7fcff;border:1px solid #a7baca;border-radius:3px;min-height:19px;text-align:center;}
            QProgressBar::chunk {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #c4f59d,stop:0.48 #8dd45d,stop:0.5 #55b42f,stop:1 #a2e37d);border-radius:2px;}
        """)

        # The native combo-menu delegate can inherit a dark Windows menu while
        # our Aero text stays dark. Use the styled view for consistent contrast.
        for combo in (self.kind, self.quality, self.output, self.language):
            combo.setItemDelegate(QStyledItemDelegate(combo))

    def text(self, key):
        widget = QLabel()
        self.tr.bind(widget.setText, key)
        return widget

    def button(self, key, callback):
        widget = QPushButton()
        self.tr.bind(widget.setText, key)
        self.tr.bind(widget.setAccessibleName, key)
        widget.clicked.connect(callback)
        return widget

    def message(self, key):
        box = QMessageBox(self)
        box.setWindowTitle("Ytdlp-G")
        box.setText(self.tr(key))
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def run_task(self, action, payload, callback, progress=None, error=None):
        task = Task(action, payload, self)
        self.tasks.add(task)
        self.current_task = task
        self.set_busy(True)
        task.result.connect(callback)
        task.error.connect(error or self.on_error)
        task.progress.connect(progress or self.on_progress)

        def finished():
            self.tasks.discard(task)
            if self.current_task is task:
                self.current_task = None
            self.set_busy(False)
            task.deleteLater()

        task.finished.connect(finished)
        task.start()
        return task

    def set_busy(self, busy):
        for control in (
            self.url,
            self.paste,
            self.analyze_button,
            self.kind,
            self.output,
            self.destination,
            self.browse,
        ):
            control.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.quality.setEnabled(not busy and self.quality.count() > 0)
        self.update_download_enabled()

    def update_download_enabled(self):
        self.download_button.setEnabled(
            not self.tasks and self.analysis is not None and bool(self.quality.currentData())
        )

    def invalidate(self):
        self.analysis = None
        self.analysis_url = ""
        self.quality.clear()
        self.quality.setEnabled(False)
        self.summary.setText(self.tr("lite_instruction"))
        self.update_download_enabled()

    def analyze(self):
        if self.tasks:
            return
        try:
            url = validate_url(self.url.text())
        except ValueError:
            self.message("invalid_url")
            return
        self.invalidate()
        self.progress.setRange(0, 0)
        self.status.setText(self.tr("lite_analyzing"))

        def result(data):
            self.analysis, self.analysis_url = data, url
            self.show_summary()
            kinds = {choice["kind"] for choice in data["choices"]}
            if self.kind.currentData() not in kinds:
                self.kind.setCurrentIndex(
                    self.kind.findData("video" if "video" in kinds else "audio")
                )
            self.refresh_choices()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.status.setText(self.tr("lite_choose_quality"))

        self.run_task("lite_inspect", {"url": url}, result)

    def show_summary(self):
        if self.analysis:
            text = (
                self.fontMetrics().elidedText(
                    self.analysis["title"], Qt.TextElideMode.ElideRight, 550
                )
                + "\n"
                + self.tr(
                    "lite_items",
                    count=len(self.analysis["items"]),
                    skipped=self.analysis["skipped"],
                )
            )
            self.summary.setText(text)

    def refresh_choices(self):
        selected = self.quality.currentData()
        self.quality.clear()
        if self.analysis:
            for choice in self.analysis["choices"]:
                if choice["kind"] != self.kind.currentData():
                    continue
                if choice.get("conversion"):
                    text = self.tr("lite_mp3_quality")
                elif choice["kind"] == "video":
                    text = f"{choice['height']}p · {choice['container'].upper()}"
                else:
                    low, high = choice["bitrate_min"], choice["bitrate_max"]
                    bitrate = (
                        (str(high) if low == high else f"{low}–{high}") + " kbps"
                        if low and high
                        else self.tr("lite_original")
                    )
                    text = f"{bitrate} · {choice['container'].upper()} ({choice['codec'].upper()})"
                self.quality.addItem(text, choice["key"])
                if choice.get("conversion"):
                    self.quality.setItemData(
                        self.quality.count() - 1,
                        self.tr("lite_mp3_hint"),
                        Qt.ItemDataRole.ToolTipRole,
                    )
            self.quality.setCurrentIndex(max(0, self.quality.findData(selected)))
            if not self.quality.count():
                self.status.setText(self.tr("lite_no_kind"))
        self.quality.setEnabled(not self.tasks and self.quality.count() > 0)
        self.update_download_enabled()

    def start_download(self):
        if self.tasks or not self.analysis or not self.quality.currentData():
            return
        if not self.destination.text().strip():
            self.message("invalid_files")
            return
        self.progress.setRange(0, 0)
        self.save_preferences()

        def result(data):
            self.last_result = data
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.status.setText(
                self.tr(
                    "lite_done", count=data["completed"], failed=data["failed"] + data["skipped"]
                )
            )

        self.run_task(
            "lite_download",
            {
                "analysis": self.analysis,
                "quality": self.quality.currentData(),
                "mode": self.output.currentData(),
                "destination": self.destination.text().strip(),
            },
            result,
        )

    def on_progress(self, data):
        phase = data.get("phase") or data.get("status", "running")
        key = {
            "analyzing": "lite_analyzing",
            "checking": "lite_checking",
            "running": "running",
            "processing": "processing",
            "archiving": "archiving",
        }.get(phase, "busy")
        current, total = (
            data.get("current", 0),
            data.get("total_items")
            or (data.get("total") if phase in {"analyzing", "checking"} else 0),
        )
        self.status.setText(self.tr(key) + (f" · {current}/{total or '?'}" if current else ""))
        if (
            phase in {"analyzing", "checking", "processing"}
            or phase == "running"
            and not data.get("total")
        ):
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(data.get("progress", 0)))

    def on_error(self, data):
        self.progress.setRange(0, 100)
        self.status.setText(self.tr(data["code"]))
        if data["code"] != "cancelled" and not self.smoke_mode:
            self.message(data["code"])

    def cancel(self):
        if self.current_task:
            self.current_task.cancel()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, self.tr("destination"), self.destination.text()
        )
        if path:
            self.destination.setText(path)
            self.save_preferences()

    def open_folder(self):
        path = Path(self.destination.text())
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def change_language(self):
        self.tr.set_language(self.language.currentData())
        self.save_preferences()

    def retranslate(self):
        self.show_summary()
        self.refresh_choices()
        if not self.analysis:
            self.summary.setText(self.tr("lite_instruction"))
        if not self.tasks:
            self.status.setText(self.tr("ready"))

    def save_preferences(self):
        self.settings.values["language"] = self.tr.language
        self.settings.values["destination"] = self.destination.text().strip()
        self.settings.values["options"]["kind"] = self.kind.currentData()
        self.settings.values["options"]["output_mode"] = self.output.currentData()
        self.settings.save()

    def quit_app(self):
        self.close()

    def closeEvent(self, event):
        if self.tasks and not self.smoke_mode:
            box = QMessageBox(self)
            box.setWindowTitle("Ytdlp-G")
            box.setText(self.tr("lite_close_active"))
            leave = box.addButton(self.tr("exit"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(self.tr("back"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not leave:
                event.ignore()
                return
        self.save_preferences()
        for task in list(self.tasks):
            task.cancel()
            task.process.waitForFinished(5000)
        event.accept()

    def smoke_close(self):
        QTimer.singleShot(0, self.quit_app)
