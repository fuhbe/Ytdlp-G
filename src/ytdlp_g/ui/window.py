"""Main desktop window: real controls connected to isolated media services."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QDateTime, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..database import ACTIVE
from ..i18n import Translator
from ..models import BUILTIN_PROFILES, Options
from ..paths import safe_name, validate_url
from ..scheduler import tick
from ..tasks import QueueManager, Task
from .widgets import FileList, OptionsWidget, button, check, combo, field, label, row, spin

NAV = [
    "home",
    "new_download",
    "queue",
    "playlists",
    "converter",
    "library",
    "export_zip",
    "schedules",
    "settings",
    "about",
]


class Window(QMainWindow):
    def __init__(self, settings, database):
        super().__init__()
        self.settings, self.db = settings, database
        self.tr = Translator(settings.values["language"])
        self.manager = QueueManager(database, settings, self)
        self.tasks = set()
        self.playlist_items = []
        self.playlist_info = {}
        self.inspections = {}
        self.playlist_url = ""
        self.playlist_page = 0
        self.batch_exports = self.db.batches()
        self.pending_conversions = []
        self.last_clipboard = ""
        self.force_exit = False
        self.network = QNetworkAccessManager(self)
        self.setWindowTitle(f"Ytdlp-G · {__version__}")
        self.resize(1280, 860)
        self.setMinimumSize(850, 620)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(215)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setSpacing(5)
        icons = [
            QStyle.StandardPixmap.SP_ComputerIcon,
            QStyle.StandardPixmap.SP_ArrowDown,
            QStyle.StandardPixmap.SP_FileDialogListView,
            QStyle.StandardPixmap.SP_DirIcon,
            QStyle.StandardPixmap.SP_MediaPlay,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_DriveHDIcon,
            QStyle.StandardPixmap.SP_BrowserReload,
            QStyle.StandardPixmap.SP_FileDialogContentsView,
            QStyle.StandardPixmap.SP_MessageBoxInformation,
        ]
        for index, key in enumerate(NAV):
            self.sidebar.addItem(self.tr(key))
            self.sidebar.item(index).setIcon(self.style().standardIcon(icons[index]))
            self.tr.bind(self.sidebar.item(index).setText, key)
        outer.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        for key in NAV:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(26, 22, 26, 22)
            heading = label(self.tr, key)
            heading.setObjectName("heading")
            layout.addWidget(heading)
            getattr(self, "build_" + key)(layout)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        self.build_tray()
        self.manager.notification.connect(self.notify)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(1000)
        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self.check_schedules)
        self.schedule_timer.start(1000)
        self.tr.changed.connect(self.retranslate)
        QApplication.clipboard().dataChanged.connect(self.clipboard_changed)
        QApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme())
        self.apply_theme()
        self.refresh_profiles()
        self.options.set_options(Options.from_dict(settings.values["options"]))
        for text_label in self.findChildren(QLabel):
            text_label.setTextFormat(Qt.TextFormat.PlainText)
        self.refresh()

    def navigate(self, key):
        self.sidebar.setCurrentRow(NAV.index(key))

    def message(self, key, details=""):
        box = QMessageBox(self)
        box.setWindowTitle("Ytdlp-G")
        box.setText(self.tr(key))
        if details:
            box.setDetailedText(details)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def confirm(self, key):
        box = QMessageBox(self)
        box.setWindowTitle("Ytdlp-G")
        box.setText(self.tr(key))
        accept = box.addButton(self.tr("confirm"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.tr("back"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() == accept

    def run_task(self, action, payload, callback, progress=None, error=None):
        task = Task(action, payload, self)
        self.tasks.add(task)
        task.result.connect(callback)
        task.error.connect(
            error
            or (
                lambda data: self.message(
                    data["code"], json.dumps(data, ensure_ascii=False, indent=2)
                )
            )
        )
        if progress:
            task.progress.connect(progress)

        def finished():
            self.tasks.discard(task)
            task.deleteLater()

        task.finished.connect(finished)
        task.start()
        return task

    def choose_folder(self, edit):
        folder = QFileDialog.getExistingDirectory(self, self.tr("destination"), edit.text())
        if folder:
            edit.setText(folder)

    def destination_row(self, layout, attribute, initial=None):
        edit = QLineEdit(initial or self.settings.values["destination"])
        self.tr.bind(edit.setAccessibleName, "destination")
        setattr(self, attribute, edit)
        layout.addWidget(label(self.tr, "destination"))
        layout.addLayout(row(edit, button(self.tr, "browse", lambda: self.choose_folder(edit))))
        return edit

    def table(self, keys):
        table = QTableWidget(0, len(keys))
        table.setMinimumHeight(220)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        for index, key in enumerate(keys):
            item = QTableWidgetItem(self.tr(key))
            table.setHorizontalHeaderItem(index, item)
            self.tr.bind(item.setText, key)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 290)
        return table

    def build_home(self, layout):
        title = label(self.tr, "welcome")
        title.setObjectName("hero")
        layout.addWidget(title)
        layout.addWidget(label(self.tr, "welcome_body", True))
        cards = QHBoxLayout()
        self.stat_labels = {}
        for key in ("queued", "running", "completed"):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            value = QLabel("0")
            value.setObjectName("stat")
            self.stat_labels[key] = value
            card_layout.addWidget(value)
            card_layout.addWidget(label(self.tr, key))
            cards.addWidget(card)
        layout.addLayout(cards)
        layout.addLayout(
            row(
                button(self.tr, "new_download", lambda: self.navigate("new_download"), True),
                button(self.tr, "converter", lambda: self.navigate("converter")),
                button(self.tr, "export_zip", lambda: self.navigate("export_zip")),
            )
        )
        layout.addWidget(label(self.tr, "help_body", True))
        self.clipboard_button = button(self.tr, "clipboard_found", self.accept_clipboard)
        self.clipboard_button.hide()
        layout.addWidget(self.clipboard_button)
        layout.addStretch()

    def build_new_download(self, layout):
        self.urls = QTextEdit()
        self.urls.setAcceptRichText(False)
        self.urls.setMaximumHeight(105)
        self.tr.bind(self.urls.setPlaceholderText, "url_hint")
        self.tr.bind(self.urls.setAccessibleName, "urls")
        layout.addWidget(self.urls)
        self.playlist_mode = check(self.tr, "playlist_mode")
        self.analyze_button = button(self.tr, "analyze", self.analyze, True)
        layout.addLayout(
            row(
                button(
                    self.tr,
                    "paste",
                    lambda: self.urls.setPlainText(QApplication.clipboard().text()),
                ),
                self.analyze_button,
                button(self.tr, "clear", self.urls.clear),
                self.playlist_mode,
            )
        )
        profile_form = QFormLayout()
        self.profile_box = QComboBox()
        self.profile_box.currentIndexChanged.connect(self.load_profile)
        field(profile_form, self.tr, "profile", self.profile_box)
        layout.addLayout(profile_form)
        self.destination_row(layout, "download_dest")
        self.options = OptionsWidget(self.tr)
        layout.addWidget(self.options)
        layout.addLayout(
            row(
                button(self.tr, "add_queue", lambda: self.enqueue(False)),
                button(self.tr, "download", lambda: self.enqueue(True), True),
            )
        )
        self.inspect_progress = QProgressBar()
        self.inspect_progress.hide()
        layout.addWidget(self.inspect_progress)
        metadata = QHBoxLayout()
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(200, 114)
        self.thumbnail.setScaledContents(False)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setObjectName("card")
        self.info = QTextBrowser()
        self.info.setMinimumHeight(160)
        self.info.setOpenExternalLinks(False)
        metadata.addWidget(self.thumbnail)
        metadata.addWidget(self.info, 1)
        layout.addLayout(metadata)
        self.formats = self.table(
            ["formats", "container", "resolution", "fps", "codec", "audio", "language", "size"]
        )
        self.formats.setColumnWidth(0, 100)
        layout.addWidget(self.formats)

    def build_playlists(self, layout):
        layout.addWidget(label(self.tr, "playlist_hint", True))
        self.playlist_title = QLabel()
        layout.addWidget(self.playlist_title)
        self.playlist_table = self.table(["title", "duration", "status"])
        self.playlist_table.itemSelectionChanged.connect(self.playlist_thumbnail)
        layout.addWidget(self.playlist_table)
        self.playlist_thumb = QLabel()
        self.playlist_thumb.setMaximumHeight(110)
        layout.addWidget(self.playlist_thumb)
        layout.addLayout(
            row(
                button(self.tr, "select_all", lambda: self.select_playlist("all")),
                button(self.tr, "deselect", lambda: self.select_playlist("none")),
                button(self.tr, "invert", lambda: self.select_playlist("invert")),
            )
        )
        layout.addLayout(
            row(
                button(self.tr, "range", lambda: self.select_playlist("range")),
                button(self.tr, "first_n", lambda: self.select_playlist("first")),
                button(self.tr, "load_more", self.more_playlist),
            )
        )
        self.group_playlist_zip = check(self.tr, "playlist_zip")
        layout.addWidget(self.group_playlist_zip)
        layout.addWidget(button(self.tr, "download_selected", self.download_playlist, True))

    def build_queue(self, layout):
        layout.addWidget(label(self.tr, "queue_notice", True))
        layout.addLayout(
            row(
                button(self.tr, "start", self.start_queue, True),
                button(self.tr, "stop_dispatch", self.stop_dispatch),
                button(self.tr, "cancel", lambda: self.job_action("cancel")),
                button(self.tr, "retry", lambda: self.job_action("retry")),
            )
        )
        layout.addLayout(
            row(
                button(self.tr, "priority", lambda: self.job_action("priority")),
                button(self.tr, "remove", lambda: self.job_action("remove")),
                button(self.tr, "details", lambda: self.job_action("details")),
            )
        )
        self.queue_table = self.table(["title", "status", "progress", "speed", "eta", "size"])
        layout.addWidget(self.queue_table)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(
            lambda point: self.job_menu(self.queue_table, point)
        )

    def build_library(self, layout):
        self.library_search = QLineEdit()
        self.tr.bind(self.library_search.setPlaceholderText, "search")
        self.library_filter = combo(
            self.tr, ["all", "completed", "failed", "cancelled", "interrupted"]
        )
        layout.addLayout(row(self.library_search, self.library_filter))
        self.library_table = self.table(["title", "status", "date", "container", "files"])
        layout.addWidget(self.library_table)
        for keys in (
            ("open_file", "open_folder", "retry", "remove"),
            ("copy_url", "details", "export_zip"),
        ):
            layout.addLayout(
                row(
                    *[
                        button(
                            self.tr,
                            key,
                            lambda checked=False, action=key: self.job_action(
                                action, self.library_table
                            ),
                        )
                        for key in keys
                    ]
                )
            )
        layout.addLayout(
            row(
                button(self.tr, "export_json", lambda: self.export_history("json")),
                button(self.tr, "export_csv", lambda: self.export_history("csv")),
                button(self.tr, "clear_history", self.clear_history),
            )
        )
        self.library_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library_table.customContextMenuRequested.connect(
            lambda point: self.job_menu(self.library_table, point)
        )

    def build_converter(self, layout):
        layout.addWidget(label(self.tr, "convert_notice", True))
        self.local_files = FileList()
        self.local_files.files_dropped.connect(self.local_files.add_files)
        layout.addWidget(self.local_files)
        layout.addLayout(
            row(
                button(self.tr, "import_files", lambda: self.import_files(self.local_files)),
                button(self.tr, "remove", lambda: self.remove_selected_files(self.local_files)),
                button(self.tr, "probe", self.probe_local),
            )
        )
        form = QFormLayout()
        self.convert_container = combo(
            self.tr,
            ["mp4", "mkv", "webm", "mov", "mp3", "m4a", "aac", "opus", "ogg", "wav", "flac"],
            False,
        )
        self.convert_codec = combo(self.tr, ["h264", "hevc", "av1"], False)
        self.convert_bitrate = combo(self.tr, [64, 96, 128, 192, 256, 320], False)
        self.convert_bitrate.setCurrentIndex(3)
        self.convert_height = combo(
            self.tr, [0, 144, 240, 360, 480, 720, 1080, 1440, 2160, 4320], False
        )
        for key, widget in (
            ("container", self.convert_container),
            ("codec", self.convert_codec),
            ("bitrate", self.convert_bitrate),
            ("resolution", self.convert_height),
        ):
            field(form, self.tr, key, widget)
        self.remux = check(self.tr, "remux")
        form.addRow(self.remux)
        self.cut_start, self.cut_end = QLineEdit("00:00:00"), QLineEdit("00:00:10")
        field(form, self.tr, "start_time", self.cut_start)
        field(form, self.tr, "end_time", self.cut_end)
        self.precise = check(self.tr, "precise", True)
        form.addRow(self.precise)
        layout.addLayout(form)
        self.destination_row(layout, "convert_dest")
        layout.addLayout(
            row(
                button(self.tr, "convert", lambda: self.start_conversions(False), True),
                button(self.tr, "cut", lambda: self.start_conversions(True)),
                button(self.tr, "cancel", self.cancel_conversions),
                button(
                    self.tr, "open_folder", lambda: self.open_path(self.convert_dest.text(), True)
                ),
            )
        )
        self.convert_progress = QProgressBar()
        layout.addWidget(self.convert_progress)
        self.convert_status = QLabel()
        layout.addWidget(self.convert_status)

    def build_export_zip(self, layout):
        layout.addWidget(label(self.tr, "zip_notice", True))
        self.zip_files = FileList()
        self.zip_files.files_dropped.connect(self.zip_files.add_files)
        layout.addWidget(self.zip_files)
        layout.addLayout(
            row(
                button(self.tr, "import_files", lambda: self.import_files(self.zip_files)),
                button(self.tr, "add_folder", self.zip_add_folder),
                button(self.tr, "remove", lambda: self.remove_selected_files(self.zip_files)),
            )
        )
        layout.addWidget(
            button(
                self.tr, "zip_selection", lambda: self.job_action("export_zip", self.library_table)
            )
        )
        form = QFormLayout()
        self.zip_name = QLineEdit("Ytdlp-G.zip")
        self.zip_compression = spin(0, 9, 0)
        field(form, self.tr, "zip_name", self.zip_name)
        field(form, self.tr, "compression", self.zip_compression)
        self.zip_preserve = check(self.tr, "preserve", True)
        self.zip_subfolders = check(self.tr, "subfolders", True)
        form.addRow(self.zip_preserve)
        form.addRow(self.zip_subfolders)
        layout.addLayout(form)
        self.destination_row(layout, "zip_dest")
        layout.addLayout(
            row(
                button(self.tr, "create_zip", self.export_zip, True),
                button(self.tr, "cancel", self.cancel_zip),
                button(self.tr, "open_folder", lambda: self.open_path(self.zip_dest.text(), True)),
            )
        )
        self.zip_progress = QProgressBar()
        layout.addWidget(self.zip_progress)
        self.zip_status = QLabel()
        layout.addWidget(self.zip_status)

    def build_schedules(self, layout):
        layout.addWidget(label(self.tr, "schedule_notice", True))
        form = QFormLayout()
        self.schedule_url = QLineEdit()
        field(form, self.tr, "url", self.schedule_url)
        self.schedule_due = QDateTimeEdit(QDateTime.currentDateTime().addSecs(60))
        self.schedule_due.setCalendarPopup(True)
        self.schedule_due.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        field(form, self.tr, "schedule_due", self.schedule_due)
        self.schedule_recurrence = combo(self.tr, ["once", "daily", "weekly"])
        field(form, self.tr, "recurrence", self.schedule_recurrence)
        layout.addLayout(form)
        layout.addWidget(label(self.tr, "options", True))
        layout.addWidget(label(self.tr, "schedule_options", True))
        self.destination_row(layout, "schedule_dest")
        layout.addLayout(
            row(
                button(self.tr, "add_schedule", self.add_schedule, True),
                button(self.tr, "cancel", self.cancel_schedule),
            )
        )
        self.schedule_table = self.table(["title", "schedule_due", "recurrence", "status"])
        layout.addWidget(self.schedule_table)

    def build_settings(self, layout):
        tabs = QTabWidget()
        layout.addWidget(tabs)
        forms = []
        for key in ("interface", "download_settings", "privacy", "profiles"):
            page = QWidget()
            form = QFormLayout(page)
            forms.append(form)
            index = tabs.addTab(page, self.tr(key))
            self.tr.bind(lambda text, i=index: tabs.setTabText(i, text), key)
        interface, downloads, privacy, profiles = forms
        self.language_box = combo(self.tr, ["pt-BR", "en", "es"], False)
        for index, text in enumerate(("Português (Brasil)", "English", "Español")):
            self.language_box.setItemText(index, text)
        self.language_box.setCurrentIndex(
            max(0, self.language_box.findData(self.settings.values["language"]))
        )
        self.language_box.currentIndexChanged.connect(self.change_language)
        field(interface, self.tr, "language", self.language_box)
        self.theme_box = combo(self.tr, ["auto", "light", "dark"])
        self.theme_box.setCurrentIndex(self.theme_box.findData(self.settings.values["theme"]))
        field(interface, self.tr, "theme", self.theme_box)
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        interface.addRow(button(self.tr, "accent", self.choose_accent))
        self.default_destination = QLineEdit(self.settings.values["destination"])
        field(downloads, self.tr, "destination", self.default_destination)
        downloads.addRow(
            button(self.tr, "browse", lambda: self.choose_folder(self.default_destination))
        )
        self.concurrency = spin(1, 8, self.settings.values["concurrency"])
        self.rate_limit = spin(0, 1000000, self.settings.values["options"]["rate_limit"])
        self.retries = spin(0, 10, self.settings.values["options"]["retries"])
        self.ffmpeg_path = QLineEdit(self.settings.values["options"]["ffmpeg"])
        self.ffprobe_path = QLineEdit(self.settings.values["options"]["ffprobe"])
        for key, widget in (
            ("concurrency", self.concurrency),
            ("rate_limit", self.rate_limit),
            ("retries", self.retries),
            ("ffmpeg", self.ffmpeg_path),
            ("ffprobe", self.ffprobe_path),
        ):
            field(downloads, self.tr, key, widget)
        downloads.addRow(
            button(self.tr, "browse_ffmpeg", lambda: self.choose_executable(self.ffmpeg_path))
        )
        downloads.addRow(
            button(self.tr, "browse_ffprobe", lambda: self.choose_executable(self.ffprobe_path))
        )
        downloads.addRow(button(self.tr, "health", self.health))
        self.health_text = QTextBrowser()
        self.health_text.setMinimumHeight(150)
        downloads.addRow(self.health_text)
        downloads.addRow(button(self.tr, "manual_update", lambda: self.message("update_notice")))
        self.preference_checks = {}
        for key in ("clipboard", "notifications", "sounds", "minimize_tray", "close_tray"):
            widget = check(self.tr, key, self.settings.values[key])
            self.preference_checks[key] = widget
            privacy.addRow(widget)
        self.preference_checks["clipboard"].toggled.connect(self.set_clipboard)
        privacy.addRow(button(self.tr, "backup", self.backup_settings))
        privacy.addRow(button(self.tr, "restore", self.restore_settings))
        privacy.addRow(button(self.tr, "cleanup_temporary", self.cleanup_temporary))
        privacy.addRow(button(self.tr, "clear_logs", self.clear_logs))
        self.profile_name = QLineEdit()
        field(profiles, self.tr, "profile_name", self.profile_name)
        profiles.addRow(button(self.tr, "save_profile", self.save_profile))
        profiles.addRow(button(self.tr, "delete_profile", self.delete_profile))
        profiles.addRow(button(self.tr, "export_profiles", self.export_profiles))
        profiles.addRow(button(self.tr, "import_profiles", self.import_profiles))
        layout.addWidget(button(self.tr, "save", self.save_settings, True))

    def build_about(self, layout):
        layout.addWidget(label(self.tr, "about_body", True))
        layout.addWidget(label(self.tr, "help_body", True))
        layout.addWidget(label(self.tr, "update_notice", True))
        layout.addStretch()

    def analyze(self):
        urls = [line.strip() for line in self.urls.toPlainText().splitlines() if line.strip()]
        try:
            urls = [validate_url(url) for url in urls]
        except ValueError:
            self.message("invalid_url")
            return
        if not urls:
            self.message("invalid_url")
            return
        playlist = self.playlist_mode.isChecked()
        if not playlist and "list" in parse_qs(urlsplit(urls[0]).query):
            playlist = self.confirm("playlist_question")
        self.pending_inspections = urls[1:] if not playlist else []
        if playlist:
            self.playlist_items.clear()
            self.playlist_url = urls[0]
            self.playlist_page = 1
        self.inspect_one(urls[0], playlist, 1)

    def inspect_one(self, url, playlist, page):
        self.analyze_button.setEnabled(False)
        self.inspect_progress.setRange(0, 0)
        self.inspect_progress.show()

        def finish(result):
            self.analyze_button.setEnabled(True)
            self.inspect_progress.hide()
            self.inspections[url] = result
            if "entries" in result:
                self.playlist_info = result
                known = {
                    (item.get("playlist_index"), item.get("webpage_url"))
                    for item in self.playlist_items
                }
                new_items = [
                    item
                    for item in result["entries"]
                    if (item.get("playlist_index"), item.get("webpage_url")) not in known
                ]
                self.playlist_items.extend(new_items)
                self.render_playlist()
                self.navigate("playlists")
                if not new_items:
                    self.message("no_more")
            else:
                self.show_info(result)
            if self.pending_inspections:
                next_url = self.pending_inspections.pop(0)
                self.inspect_one(next_url, False, 1)

        def failure(data):
            self.analyze_button.setEnabled(True)
            self.inspect_progress.hide()
            self.message(data["code"], json.dumps(data, indent=2))

        self.run_task(
            "inspect", {"url": url, "playlist": playlist, "page": page}, finish, error=failure
        )

    def show_info(self, result):
        self.current_info = result
        fields = [
            ("title", result.get("title")),
            ("channel", result.get("channel") or result.get("uploader")),
            ("platform", result.get("extractor_key")),
            ("duration", self.duration(result.get("duration"))),
            ("date", result.get("upload_date")),
            ("manual_subs", ", ".join(result.get("subtitles", []))),
            ("automatic_subs", ", ".join(result.get("automatic_captions", []))),
            ("chapters", len(result.get("chapters", []))),
        ]
        self.info.setPlainText(
            "\n".join(f"{self.tr(key)}: {value or self.tr('unknown')}" for key, value in fields)
            + "\n\n"
            + (result.get("description") or "")
        )
        formats = result.get("formats", [])
        self.options.set_formats(formats)
        self.formats.setRowCount(len(formats))
        for row_index, fmt in enumerate(formats):
            size = fmt.get("filesize") or fmt.get("filesize_approx")
            size_label = self.size(size) + (
                " · " + self.tr("estimated") if not fmt.get("filesize") and size else ""
            )
            values = [
                fmt.get("format_id"),
                fmt.get("ext"),
                fmt.get("height"),
                fmt.get("fps"),
                fmt.get("vcodec"),
                fmt.get("acodec"),
                fmt.get("language"),
                size_label,
            ]
            for column, value in enumerate(values):
                self.formats.setItem(
                    row_index, column, QTableWidgetItem(str(value if value is not None else "—"))
                )
        self.load_thumbnail(result.get("thumbnail"), self.thumbnail)

    def load_thumbnail(self, url, widget):
        widget.clear()
        if not url:
            return
        try:
            url = validate_url(url)
        except ValueError:
            return
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(15000)
        reply = self.network.get(request)
        reply.downloadProgress.connect(
            lambda received, total: (
                reply.abort() if received > 5_000_000 or total > 5_000_000 else None
            )
        )

        def complete():
            if reply.error() == reply.NetworkError.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(bytes(reply.readAll())):
                    widget.setPixmap(
                        pixmap.scaled(
                            195,
                            110,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            reply.deleteLater()

        reply.finished.connect(complete)

    def options_value(self):
        defaults = self.settings.values["options"] | {
            "rate_limit": self.rate_limit.value(),
            "retries": self.retries.value(),
            "ffmpeg": self.ffmpeg_path.text().strip(),
            "ffprobe": self.ffprobe_path.text().strip(),
        }
        return self.options.get_options(defaults).to_dict()

    def enqueue(self, start):
        try:
            options = self.options_value()
            urls = [
                validate_url(line) for line in self.urls.toPlainText().splitlines() if line.strip()
            ]
            if not urls:
                raise ValueError("invalid_url")
        except ValueError as exc:
            self.message(str(exc))
            return
        existing = {job["url"] for job in self.db.jobs()}
        if existing.intersection(urls) and not self.confirm("duplicate"):
            return
        for url in urls:
            info = self.inspections.get(url, {})
            if "entries" in info:
                self.navigate("playlists")
                return
            self.db.add_job(
                url,
                info.get("title") or urlsplit(url).hostname,
                self.download_dest.text(),
                options,
                platform=info.get("extractor_key") or "",
                thumbnail=info.get("thumbnail") or "",
            )
        if start:
            self.start_queue()
        self.refresh()
        self.navigate("queue")
        self.statusBar().showMessage(self.tr("added"), 5000)

    def render_playlist(self):
        checked_urls = {
            self.playlist_items[i].get("webpage_url")
            for i in range(min(self.playlist_table.rowCount(), len(self.playlist_items)))
            if self.playlist_table.item(i, 0)
            and self.playlist_table.item(i, 0).checkState() == Qt.CheckState.Checked
        }
        previous_count = self.playlist_table.rowCount()
        self.playlist_title.setText(
            str(self.playlist_info.get("title") or "")
            + f" · {len(self.playlist_items)} / {self.playlist_info.get('playlist_count') or '?'}"
        )
        self.playlist_table.setRowCount(len(self.playlist_items))
        for index, entry in enumerate(self.playlist_items):
            item = QTableWidgetItem(
                f"{entry.get('playlist_index') or index + 1:03d} · {entry.get('title') or self.tr('unavailable')}"
            )
            available = bool(entry.get("webpage_url")) and entry.get("availability") not in {
                "private",
                "premium_only",
                "subscriber_only",
                "needs_auth",
            }
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if available
                and (index >= previous_count or entry.get("webpage_url") in checked_urls)
                else Qt.CheckState.Unchecked
            )
            if not available:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.playlist_table.setItem(index, 0, item)
            self.playlist_table.setItem(
                index, 1, QTableWidgetItem(self.duration(entry.get("duration")))
            )
            self.playlist_table.setItem(
                index, 2, QTableWidgetItem(self.tr("ready" if available else "unavailable"))
            )

    def select_playlist(self, mode):
        low, high = 1, len(self.playlist_items)
        if mode == "first":
            high, ok = QInputDialog.getInt(
                self, self.tr("first_n"), self.tr("first_n"), 10, 1, max(1, high)
            )
            if not ok:
                return
        elif mode == "range":
            text, ok = QInputDialog.getText(self, self.tr("range"), self.tr("range_hint"))
            if not ok:
                return
            try:
                low, high = map(int, text.split("-"))
                if not 1 <= low <= high <= len(self.playlist_items):
                    raise ValueError
            except ValueError:
                self.message("invalid_options")
                return
        for index in range(self.playlist_table.rowCount()):
            item = self.playlist_table.item(index, 0)
            if not item.flags() & Qt.ItemFlag.ItemIsEnabled:
                continue
            selected = (
                item.checkState() != Qt.CheckState.Checked
                if mode == "invert"
                else low <= index + 1 <= high and mode != "none"
            )
            item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def more_playlist(self):
        if not self.playlist_url:
            self.message("no_playlist")
            return
        if not self.analyze_button.isEnabled():
            return
        self.playlist_page += 1
        self.pending_inspections = []
        self.inspect_one(self.playlist_url, True, self.playlist_page)

    def playlist_thumbnail(self):
        index = self.playlist_table.currentRow()
        if 0 <= index < len(self.playlist_items):
            self.load_thumbnail(self.playlist_items[index].get("thumbnail"), self.playlist_thumb)

    def download_playlist(self):
        try:
            options = self.options_value()
        except ValueError:
            self.message("invalid_options")
            return
        selected = [
            (i, item)
            for i, item in enumerate(self.playlist_items)
            if self.playlist_table.item(i, 0).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            self.message("select_files")
            return
        identifiers = []
        group = self.group_playlist_zip.isChecked()
        output_mode = options["output_mode"]
        for index, item in selected:
            item_options = options | {
                "_playlist_title": self.playlist_info.get("title", "Playlist"),
                "_playlist_index": item.get("playlist_index") or index + 1,
            }
            if group:
                item_options["output_mode"] = "normal"
            item_options["organization"] = "playlist"
            identifiers.append(
                self.db.add_job(
                    item["webpage_url"],
                    item.get("title") or "",
                    self.download_dest.text(),
                    item_options,
                    thumbnail=item.get("thumbnail") or "",
                )
            )
        if group:
            target = Path(self.download_dest.text()) / (
                safe_name(self.playlist_info.get("title") or "Playlist") + ".zip"
            )
            batch = {
                "ids": identifiers,
                "target": str(target),
                "compression": options["compression"],
                "preserve": output_mode != "zip",
            }
            batch["id"] = self.db.add_batch(batch)
            self.batch_exports.append(batch)
        self.start_queue()
        self.navigate("queue")

    def start_queue(self):
        self.manager.enabled = True
        self.manager.pump()

    def stop_dispatch(self):
        self.manager.enabled = False

    def selected_jobs(self, table):
        identifiers = {
            table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in table.selectionModel().selectedRows()
        }
        return [job for job in self.db.jobs() if job["id"] in identifiers]

    def job_action(self, action, table=None):
        table = table or self.queue_table
        jobs = self.selected_jobs(table)
        if not jobs:
            self.message("select_files")
            return
        if action == "remove" and not self.confirm("confirm_delete"):
            return
        if action == "export_zip":
            self.zip_files.add_files([path for job in jobs for path in job["files"]])
            self.navigate("export_zip")
            return
        for job in jobs:
            if action == "cancel":
                self.manager.cancel(job["id"])
            elif action == "retry":
                self.manager.retry(job["id"])
            elif action == "remove":
                self.db.delete(job["id"])
            elif action == "priority":
                self.db.update(job["id"], priority=job["priority"] + 1)
            elif action == "copy_url":
                QApplication.clipboard().setText(job["url"])
            elif action in {"open_file", "open_folder"}:
                path = job["files"][0] if job["files"] else job["destination"]
                self.open_path(path, action == "open_folder")
            elif action == "details":
                # URLs may include private query strings: details omit the URL.
                details = {
                    key: value for key, value in job.items() if key not in {"url", "thumbnail"}
                }
                if job["error"]:
                    details["error"] = self.tr(job["error"])
                self.message("details", json.dumps(details, ensure_ascii=False, indent=2))
        self.refresh()

    def job_menu(self, table, point):
        menu = QMenu(self)
        for key in (
            "open_file",
            "open_folder",
            "copy_url",
            "retry",
            "cancel",
            "export_zip",
            "details",
            "remove",
        ):
            action = menu.addAction(self.tr(key))
            action.triggered.connect(
                lambda checked=False, action_key=key: self.job_action(action_key, table)
            )
        menu.exec(table.viewport().mapToGlobal(point))

    def open_path(self, value, folder=False):
        path = Path(value)
        if folder and path.is_file():
            path = path.parent
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self.message("invalid_files")

    def refresh_job_table(self, table, jobs, history=False):
        selected = {job["id"] for job in self.selected_jobs(table)}
        table.setRowCount(len(jobs))
        table.setUpdatesEnabled(False)
        for index, job in enumerate(jobs):
            values = [job["title"], self.tr(job["status"])]
            if history:
                values += [
                    job["created"][:19].replace("T", " "),
                    job["options"]["container"].upper(),
                    "; ".join(job["files"]),
                ]
            else:
                values += [
                    f"{job['progress']:.1f}%",
                    self.size(job["speed"]) + "/s",
                    self.duration(job["eta"]),
                    f"{self.size(job['downloaded'])} / {'≈ ' if job['estimated'] else ''}{self.size(job['total'])}",
                ]
            for column, value in enumerate(values):
                item = table.item(index, column)
                if item is None:
                    item = QTableWidgetItem()
                    table.setItem(index, column, item)
                item.setText(str(value))
                item.setData(Qt.ItemDataRole.UserRole, job["id"])
                item.setToolTip(self.tr(job["error"]) if job["error"] else str(value))
            if not history:
                bar = table.cellWidget(index, 2)
                if bar is None:
                    bar = QProgressBar()
                    bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    table.setCellWidget(index, 2, bar)
                indeterminate = (
                    job["status"] == "processing" or job["status"] == "running" and not job["total"]
                )
                bar.setRange(0, 0 if indeterminate else 100)
                bar.setValue(int(job["progress"]))
                bar.setAccessibleName(self.tr("progress") + " · " + self.tr(job["status"]))
            if job["id"] in selected:
                # selectRow clears earlier rows in some selection modes.
                for column in range(table.columnCount()):
                    table.item(index, column).setSelected(True)
            else:
                for column in range(table.columnCount()):
                    table.item(index, column).setSelected(False)
        table.setUpdatesEnabled(True)

    def refresh(self):
        jobs = self.db.jobs()
        self.refresh_job_table(self.queue_table, jobs)
        term = self.library_search.text().casefold()
        status = self.library_filter.currentData()
        history = [
            j
            for j in jobs
            if (term in j["title"].casefold() or term in j["url"].casefold())
            and (status == "all" or status == j["status"])
        ]
        self.refresh_job_table(self.library_table, history, True)
        for key, widget in self.stat_labels.items():
            widget.setText(
                str(
                    sum(
                        1
                        for job in jobs
                        if job["status"] == key or key == "running" and job["status"] in ACTIVE
                    )
                )
            )
        self.render_schedules()
        for batch in self.batch_exports[:]:
            members = [job for job in jobs if job["id"] in batch["ids"]]
            if len(members) != len(batch["ids"]):
                self.batch_exports.remove(batch)
                self.db.set_batch_status(batch["id"], "failed")
                continue
            if all(job["status"] in {"completed", "failed", "cancelled"} for job in members):
                self.batch_exports.remove(batch)
                self.db.set_batch_status(batch["id"], "running")
                files = [path for job in members for path in job["files"]]
                records = []
                for path in files:
                    try:
                        info = Path(path).stat()
                        records.append((path, info.st_size, info.st_mtime_ns))
                    except OSError:
                        pass
                if files:
                    self.run_task(
                        "zip",
                        {
                            "sources": files,
                            "target": batch["target"],
                            "compression": batch["compression"],
                            "preserve": True,
                            "subfolders": True,
                        },
                        lambda result, group=members, preserve=batch["preserve"], key=batch["id"], sources=records: (
                            self.finish_playlist_zip(result, group, preserve, key, sources)
                        ),
                        error=lambda data, key=batch["id"]: self.fail_playlist_zip(key, data),
                    )
                else:
                    self.db.set_batch_status(batch["id"], "failed")

    def fail_playlist_zip(self, identifier, data):
        self.db.set_batch_status(identifier, "failed")
        self.notify(data["code"])

    def finish_playlist_zip(self, result, jobs, preserve, identifier, records):
        for job in jobs:
            if job["status"] == "completed":
                self.db.update(
                    job["id"], files=(job["files"] if preserve else []) + result["files"]
                )
        self.db.set_batch_status(identifier, "completed")
        # Persist the verified archive in history before deleting any source.
        if not preserve:
            for path, size, mtime in records:
                source = Path(path)
                try:
                    current = source.stat()
                    if current.st_size == size and current.st_mtime_ns == mtime:
                        source.unlink()
                except OSError:
                    pass
        self.notify("zip_completed")

    def export_history(self, kind):
        filename, _ = QFileDialog.getSaveFileName(
            self, self.tr("export_" + kind), f"Ytdlp-G-history.{kind}", f"{kind.upper()} (*.{kind})"
        )
        if not filename:
            return
        jobs = self.db.jobs(self.library_search.text())
        try:
            with Path(filename).open(
                "w", encoding="utf-8-sig" if kind == "csv" else "utf-8", newline=""
            ) as output:
                if kind == "json":
                    json.dump(jobs, output, ensure_ascii=False, indent=2)
                else:
                    keys = ["title", "url", "status", "created", "destination", "platform", "files"]
                    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
                    writer.writeheader()
                    # Neutralize spreadsheet formula injection in untrusted titles.
                    for job in jobs:
                        writer.writerow(
                            {
                                key: "'" + str(job[key])
                                if str(job[key]).startswith(("=", "+", "-", "@"))
                                else job[key]
                                for key in keys
                            }
                        )
        except OSError:
            self.message("operation_failed")

    def clear_history(self):
        if self.confirm("confirm_delete"):
            for job in self.db.jobs():
                if job["status"] == "completed":
                    self.db.delete(job["id"])
            self.refresh()

    def import_files(self, widget):
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("import_files"))
        widget.add_files(files)

    def remove_selected_files(self, widget):
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))

    def probe_local(self):
        items = self.local_files.selectedItems()
        if not items:
            self.message("select_files")
            return
        self.run_task(
            "probe",
            {"source": items[0].text(), "ffprobe": self.ffprobe_path.text().strip()},
            lambda result: self.message(
                "inspect_result", json.dumps(result, ensure_ascii=False, indent=2)
            ),
        )

    def start_conversions(self, cut):
        if self.pending_conversions or any(task.action == "convert" for task in self.tasks):
            self.message("busy")
            return
        files = [item.text() for item in self.local_files.selectedItems()]
        if not files:
            self.message("select_files")
            return
        for source in files:
            payload = {
                "source": source,
                "destination": self.convert_dest.text(),
                "container": self.convert_container.currentData(),
                "codec": self.convert_codec.currentData(),
                "bitrate": self.convert_bitrate.currentData(),
                "height": self.convert_height.currentData(),
                "remux": self.remux.isChecked() if not cut else False,
                "precise": self.precise.isChecked(),
                "ffmpeg": self.ffmpeg_path.text().strip(),
                "ffprobe": self.ffprobe_path.text().strip(),
            }
            if cut:
                payload |= {"start": self.cut_start.text(), "end": self.cut_end.text()}
            self.pending_conversions.append(payload)
        self.next_conversion()

    def next_conversion(self):
        if not self.pending_conversions:
            return
        payload = self.pending_conversions.pop(0)
        self.convert_status.setText(Path(payload["source"]).name)
        self.convert_progress.setValue(0)

        def success(result):
            self.convert_progress.setValue(100)
            self.convert_status.setText("\n".join(result["files"]))
            self.notify("conversion_completed")
            QTimer.singleShot(0, self.next_conversion)

        def failure(data):
            self.pending_conversions.clear()
            self.convert_status.setText(self.tr(data["code"]))
            if data["code"] != "cancelled":
                self.message(data["code"])

        self.run_task(
            "convert",
            payload,
            success,
            lambda data: self.convert_progress.setValue(int(data["progress"])),
            failure,
        )

    def cancel_conversions(self):
        self.pending_conversions.clear()
        for task in list(self.tasks):
            if task.action == "convert":
                task.cancel()

    def zip_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("add_folder"))
        if folder:
            self.zip_files.add_files(
                [
                    str(path)
                    for path in Path(folder).rglob("*")
                    if path.is_file() and not any(part.startswith(".ytdlp") for part in path.parts)
                ]
            )

    def export_zip(self):
        if any(task.action == "zip" for task in self.tasks):
            self.message("busy")
            return
        files = self.zip_files.paths()
        if not files:
            self.message("select_files")
            return
        if not self.zip_preserve.isChecked() and not self.confirm("confirm_sources"):
            return
        name = safe_name(self.zip_name.text())
        if not name.lower().endswith(".zip"):
            name += ".zip"
        target = str(Path(self.zip_dest.text()) / name)
        self.zip_progress.setValue(0)
        self.zip_status.setText(self.tr("busy"))

        def success(result):
            self.zip_status.setText("\n".join(result["files"]))
            self.zip_progress.setValue(100)
            self.notify("zip_completed")

        self.run_task(
            "zip",
            {
                "sources": files,
                "target": target,
                "compression": self.zip_compression.value(),
                "preserve": self.zip_preserve.isChecked(),
                "subfolders": self.zip_subfolders.isChecked(),
            },
            success,
            lambda data: self.zip_progress.setValue(int(data["progress"])),
            lambda data: self.zip_status.setText(self.tr(data["code"])),
        )

    def cancel_zip(self):
        for task in list(self.tasks):
            if task.action == "zip":
                task.cancel()
        self.zip_status.setText(self.tr("cancelled"))

    def add_schedule(self):
        try:
            url = validate_url(self.schedule_url.text())
            options = self.options_value()
            due = datetime.fromtimestamp(self.schedule_due.dateTime().toSecsSinceEpoch(), UTC)
            self.db.add_schedule(
                url,
                urlsplit(url).hostname,
                self.schedule_dest.text(),
                options,
                due,
                self.schedule_recurrence.currentData(),
            )
            self.render_schedules()
        except ValueError as exc:
            self.message(str(exc))

    def cancel_schedule(self):
        for index in self.schedule_table.selectionModel().selectedRows():
            self.db.cancel_schedule(
                self.schedule_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            )
        self.render_schedules()

    def render_schedules(self):
        rows = self.db.schedules()
        self.schedule_table.setRowCount(len(rows))
        for index, entry in enumerate(rows):
            values = [
                entry["title"],
                datetime.fromisoformat(entry["due"]).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                self.tr(entry["recurrence"]),
                self.tr("enabled" if entry["enabled"] else "disabled"),
            ]
            for column, value in enumerate(values):
                item = self.schedule_table.item(index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.schedule_table.setItem(index, column, item)
                item.setText(value)
                item.setData(Qt.ItemDataRole.UserRole, entry["id"])

    def check_schedules(self):
        if tick(self.db):
            self.start_queue()
            self.notify("schedule_started")

    def refresh_profiles(self):
        current = self.profile_box.currentData()
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItem(self.tr("current_options"), "")
        for name in [*BUILTIN_PROFILES, *self.settings.values["profiles"]]:
            self.profile_box.addItem(self.tr(name) if name in BUILTIN_PROFILES else name, name)
        self.profile_box.setCurrentIndex(max(0, self.profile_box.findData(current)))
        self.profile_box.blockSignals(False)

    def load_profile(self):
        name = self.profile_box.currentData()
        if name:
            self.options.set_options(self.settings.profile(name))

    def save_profile(self):
        name = self.profile_name.text().strip()
        if not name or name in BUILTIN_PROFILES:
            self.message("invalid_options")
            return
        try:
            self.settings.values["profiles"][name] = self.options_value()
            self.settings.save()
            self.refresh_profiles()
            self.profile_box.setCurrentIndex(self.profile_box.findData(name))
        except (ValueError, OSError):
            self.message("invalid_options")

    def delete_profile(self):
        name = self.profile_name.text().strip() or self.profile_box.currentData()
        self.settings.values["profiles"].pop(name, None)
        self.settings.save()
        self.refresh_profiles()

    def export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("export_profiles"), "Ytdlp-G-profiles.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(self.settings.values["profiles"], ensure_ascii=False, indent=2),
                    "utf-8",
                )
            except OSError:
                self.message("operation_failed")

    def import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("import_profiles"), "", "JSON (*.json)")
        if path:
            try:
                profiles = json.loads(Path(path).read_text("utf-8"))
                if not isinstance(profiles, dict) or any(
                    name in BUILTIN_PROFILES or not isinstance(name, str) or not name.strip()
                    for name in profiles
                ):
                    raise ValueError
                profiles = {
                    name: Options.from_dict(data).to_dict() for name, data in profiles.items()
                }
                self.settings.values["profiles"].update(profiles)
                self.settings.save()
                self.refresh_profiles()
            except (OSError, ValueError, TypeError):
                self.message("invalid_options")

    def change_language(self):
        language = self.language_box.currentData()
        self.settings.values["language"] = language
        self.settings.save()
        self.tr.set_language(language)

    def retranslate(self):
        self.refresh_profiles()
        self.refresh()
        if hasattr(self, "current_info"):
            self.show_info(self.current_info)

    def change_theme(self):
        self.settings.values["theme"] = self.theme_box.currentData()
        self.settings.save()
        self.apply_theme()

    def choose_accent(self):
        color = QColorDialog.getColor(QColor(self.settings.values["accent"]), self)
        if color.isValid():
            self.settings.values["accent"] = color.name()
            self.settings.save()
            self.apply_theme()

    def apply_theme(self):
        mode = self.settings.values["theme"]
        dark = (
            mode == "dark"
            or mode == "auto"
            and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        bg, panel, text, border, alternate = (
            ("#141820", "#1e2430", "#edf1fa", "#354052", "#252c39")
            if dark
            else ("#f3f5fa", "#ffffff", "#202b40", "#dbe1ee", "#f7f9fd")
        )
        accent = self.settings.values["accent"]
        color = QColor(accent)
        on_accent = (
            "#172033"
            if 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue() > 160
            else "white"
        )
        self.setStyleSheet(f"""
            QMainWindow, QScrollArea, QStackedWidget {{background:{bg}; color:{text};}}
            QWidget {{color:{text}; font-family:'Segoe UI', 'DejaVu Sans'; font-size:13px;}}
            QScrollArea > QWidget > QWidget {{background:{bg};}}
            QLabel#heading {{font-size:25px; font-weight:600; padding-bottom:12px;}}
            QLabel#hero {{font-size:31px; font-weight:700; padding:14px 0;}}
            QLabel#stat {{font-size:36px; font-weight:600;}}
            QFrame#card {{background:{panel}; border:1px solid {border}; border-radius:12px; padding:16px;}}
            QListWidget#sidebar {{background:{panel}; border:0; border-right:1px solid {border}; padding:20px 10px;}}
            QListWidget#sidebar::item {{padding:12px 7px; border-radius:7px;}}
            QListWidget#sidebar::item:selected {{background:{accent}; color:{on_accent};}}
            QPushButton {{background:{panel}; border:1px solid {border}; border-radius:7px; padding:9px 13px;}}
            QPushButton[primary=true] {{background:{accent}; color:{on_accent}; border-color:{accent};}}
            QPushButton:hover {{border-color:{accent};}}
            QPushButton:disabled {{color:#8893a5;}}
            QPushButton:focus, QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{border:2px solid {accent};}}
            QLineEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox, QDateTimeEdit, QListWidget, QTableWidget {{background:{panel}; border:1px solid {border}; border-radius:6px; padding:6px; selection-background-color:{accent}; selection-color:white;}}
            QComboBox QAbstractItemView {{background:{panel}; color:{text};}}
            QTableWidget {{alternate-background-color:{alternate}; gridline-color:{border};}}
            QHeaderView::section {{background:{panel}; color:{text}; border:0; border-bottom:1px solid {border}; padding:9px;}}
            QTabWidget::pane {{border:1px solid {border}; border-radius:7px;}}
            QTabBar::tab {{background:{panel}; padding:10px; border-bottom:2px solid transparent;}}
            QTabBar::tab:selected {{border-bottom-color:{accent};}}
            QProgressBar {{border:1px solid {border}; border-radius:5px; background:{panel}; text-align:center; min-height:19px;}}
            QProgressBar::chunk {{background:{accent}; border-radius:4px;}}
            QMenu {{background:{panel}; border:1px solid {border};}}
            QMenu::item:selected {{background:{accent}; color:{on_accent};}}
            QToolTip {{background:{panel}; color:{text}; border:1px solid {border};}}
        """)

    def choose_executable(self, edit):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("browse"),
            "",
            self.tr("executables_filter")
            if __import__("os").name == "nt"
            else self.tr("all_files_filter"),
        )
        if path:
            edit.setText(path)
            self.health()

    def health(self):
        self.health_text.setPlainText(self.tr("busy"))

        def result(data):
            self.health_text.setPlainText(
                "\n".join(f"{name}: {self.tr(value)}" for name, value in data.items())
            )

        self.run_task(
            "health",
            {
                "ffmpeg": self.ffmpeg_path.text().strip(),
                "ffprobe": self.ffprobe_path.text().strip(),
            },
            result,
        )

    def save_settings(self, silent=False):
        try:
            values = self.settings.values | {
                "destination": self.default_destination.text().strip(),
                "concurrency": self.concurrency.value(),
                "options": self.options_value(),
            }
            values.update(
                {key: widget.isChecked() for key, widget in self.preference_checks.items()}
            )
            self.settings.load(values)
            self.settings.save()
            if not silent:
                self.message("saved")
        except (ValueError, OSError):
            self.message("invalid_options")

    def backup_settings(self):
        self.save_settings(True)
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("backup"), "Ytdlp-G-settings.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(self.settings.values, ensure_ascii=False, indent=2), "utf-8"
                )
            except OSError:
                self.message("operation_failed")

    def restore_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("restore"), "", "JSON (*.json)")
        if not path:
            return
        try:
            self.settings.load(json.loads(Path(path).read_text("utf-8")))
            self.settings.save()
            values = self.settings.values
            self.language_box.setCurrentIndex(self.language_box.findData(values["language"]))
            self.theme_box.setCurrentIndex(self.theme_box.findData(values["theme"]))
            self.default_destination.setText(values["destination"])
            for widget in (
                self.download_dest,
                self.convert_dest,
                self.zip_dest,
                self.schedule_dest,
            ):
                widget.setText(values["destination"])
            self.concurrency.setValue(values["concurrency"])
            self.rate_limit.setValue(values["options"]["rate_limit"])
            self.retries.setValue(values["options"]["retries"])
            self.ffmpeg_path.setText(values["options"]["ffmpeg"])
            self.ffprobe_path.setText(values["options"]["ffprobe"])
            self.options.set_options(Options.from_dict(values["options"]))
            for key, widget in self.preference_checks.items():
                widget.setChecked(values[key])
            self.refresh_profiles()
            self.apply_theme()
        except (OSError, ValueError, TypeError):
            self.message("invalid_options")

    def cleanup_temporary(self):
        if self.manager.active or self.tasks:
            self.message("busy")
            return
        if not self.confirm("cleanup_warning"):
            return
        from ..diagnostics import cleanup_temporary

        destinations = {
            self.download_dest.text(),
            self.zip_dest.text(),
            self.convert_dest.text(),
            *[job["destination"] for job in self.db.jobs()],
        }
        try:
            for destination in destinations:
                cleanup_temporary(destination)
            self.message("cleanup_done")
        except OSError:
            self.message("operation_failed")

    def clear_logs(self):
        from ..diagnostics import clear_logs

        try:
            clear_logs(self.settings.path.parent)
            self.message("cleanup_done")
        except OSError:
            self.message("operation_failed")

    def set_clipboard(self, enabled):
        self.settings.values["clipboard"] = enabled
        self.settings.save()
        if not enabled:
            self.clipboard_button.hide()

    def clipboard_changed(self):
        if not self.settings.values["clipboard"]:
            return
        text = QApplication.clipboard().text().strip()
        if text == self.last_clipboard:
            return
        self.last_clipboard = text
        try:
            self.clipboard_url = validate_url(text)
        except ValueError:
            return
        self.clipboard_button.show()
        self.statusBar().showMessage(self.tr("clipboard_found"), 10000)

    def accept_clipboard(self):
        self.urls.setPlainText(self.clipboard_url)
        self.clipboard_button.hide()
        self.navigate("new_download")

    def build_tray(self):
        icon_path = Path(__file__).parents[1] / "resources" / "app.ico"
        icon = (
            QIcon(str(icon_path))
            if icon_path.exists()
            else self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Ytdlp-G")
        menu = QMenu(self)
        for key, callback in (
            ("open", self.showNormal),
            ("queue", lambda: (self.showNormal(), self.navigate("queue"))),
            ("quit", self.quit_app),
        ):
            action = QAction(self)
            self.tr.bind(action.setText, key)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
            )
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def notify(self, key):
        self.statusBar().showMessage(self.tr(key), 8000)
        if self.settings.values["notifications"] and self.tray.isVisible():
            self.tray.showMessage(
                "Ytdlp-G", self.tr(key), QSystemTrayIcon.MessageIcon.Information, 5000
            )
        if self.settings.values["sounds"]:
            QApplication.beep()

    def quit_app(self):
        self.force_exit = True
        self.close()

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent

        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and hasattr(self, "tray")
            and self.tray.isVisible()
            and self.settings.values["minimize_tray"]
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event):
        active = bool(self.manager.active or self.tasks)
        if active and not getattr(self, "smoke_mode", False):
            box = QMessageBox(self)
            box.setWindowTitle("Ytdlp-G")
            box.setText(self.tr("close_active"))
            background = box.addButton(self.tr("background"), QMessageBox.ButtonRole.ActionRole)
            background.setEnabled(self.tray.isVisible())
            exit_button = box.addButton(self.tr("exit"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(self.tr("back"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == background:
                self.hide()
                event.ignore()
                return
            if box.clickedButton() != exit_button:
                self.force_exit = False
                event.ignore()
                return
        elif not self.force_exit and self.settings.values["close_tray"] and self.tray.isVisible():
            self.hide()
            event.ignore()
            return
        self.save_settings(True)
        self.schedule_timer.stop()
        self.refresh_timer.stop()
        self.manager.shutdown()
        self.pending_conversions.clear()
        for task in list(self.tasks):
            task.cancel()
            task.process.waitForFinished(5000)
        self.tray.hide()
        self.db.close()
        event.accept()

    @staticmethod
    def duration(seconds):
        if seconds is None:
            return "—"
        seconds = max(0, int(seconds))
        return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def size(value):
        if not value:
            return "—"
        value = float(value)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} PiB"
