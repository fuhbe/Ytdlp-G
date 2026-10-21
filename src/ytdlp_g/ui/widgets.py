"""Translated, accessible widgets and media options shared across pages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import Options


def label(tr, key, wrap=False):
    widget = QLabel()
    tr.bind(widget.setText, key)
    widget.setWordWrap(wrap)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(tr, key, callback=None, primary=False):
    widget = QPushButton()
    tr.bind(widget.setText, key)
    tr.bind(widget.setAccessibleName, key)
    tr.bind(widget.setToolTip, key)
    if primary:
        widget.setProperty("primary", True)
    if callback:
        widget.clicked.connect(callback)
    return widget


def check(tr, key, checked=False):
    widget = QCheckBox()
    tr.bind(widget.setText, key)
    tr.bind(widget.setAccessibleName, key)
    widget.setChecked(checked)
    return widget


def combo(tr, choices, translated=True):
    widget = QComboBox()
    for value in choices:
        widget.addItem(tr(value) if translated else str(value), value)
        if translated:
            index = widget.count() - 1
            tr.bind(lambda text, i=index: widget.setItemText(i, text), value)
    return widget


def field(form, tr, key, widget):
    text = label(tr, key)
    text.setBuddy(widget)
    tr.bind(widget.setAccessibleName, key)
    form.addRow(text, widget)


def spin(low, high, value):
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def row(*widgets):
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    return layout


class FileList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setMinimumHeight(120)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        self.files_dropped.emit(
            [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        )
        event.acceptProposedAction()

    def add_files(self, files):
        existing = {self.item(i).text() for i in range(self.count())}
        from pathlib import Path

        for path in files:
            if path not in existing and Path(path).is_file() and not Path(path).is_symlink():
                self.addItem(path)
                existing.add(path)

    def paths(self):
        return [self.item(i).text() for i in range(self.count())]


class OptionsWidget(QWidget):
    def __init__(self, tr):
        super().__init__()
        self.tr = tr
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        self.controls = {}
        media, subtitles, archive, organization = [QWidget() for _ in range(4)]
        for page, key in zip(
            (media, subtitles, archive, organization),
            ("options", "subtitles", "export_zip", "organization"),
            strict=True,
        ):
            index = tabs.addTab(page, tr(key))
            tr.bind(lambda text, i=index: tabs.setTabText(i, text), key)
        main_form = QFormLayout(media)
        self.kind = combo(tr, ["video", "audio", "video_only", "subtitles"])
        self.container = QComboBox()
        self.quality = combo(
            tr,
            [
                "best",
                "compatible",
                "small",
                "144",
                "240",
                "360",
                "480",
                "720",
                "1080",
                "1440",
                "2160",
                "4320",
            ],
        )
        self.codec = combo(tr, ["auto", "h264", "hevc", "av1"])
        self.bitrate = combo(tr, [64, 96, 128, 192, 256, 320], translated=False)
        self.bitrate.setCurrentIndex(3)
        self.video_stream = combo(tr, ["auto"])
        self.audio_stream = combo(tr, ["auto"])
        for name in (
            "kind",
            "container",
            "quality",
            "codec",
            "bitrate",
            "video_stream",
            "audio_stream",
        ):
            control = getattr(self, name)
            self.controls[name] = control
            field(main_form, tr, name, control)
        for key, initial in (
            ("metadata", True),
            ("thumbnail", False),
            ("embed_thumbnail", False),
            ("info_json", False),
            ("description", False),
        ):
            control = check(tr, key, initial)
            self.controls[key] = control
            main_form.addRow(control)
        main_form.addRow(label(tr, "media_notice", True))
        sub_form = QFormLayout(subtitles)
        self.controls["subtitles"] = QLineEdit()
        field(sub_form, tr, "sub_languages", self.controls["subtitles"])
        for key in ("auto_subtitles", "embed_subtitles"):
            self.controls[key] = check(tr, key)
            sub_form.addRow(self.controls[key])
        self.controls["subtitle_format"] = combo(tr, ["srt", "vtt"], False)
        field(sub_form, tr, "subtitle_format", self.controls["subtitle_format"])
        zip_form = QFormLayout(archive)
        self.controls["output_mode"] = combo(tr, ["normal", "zip", "both"])
        self.controls["compression"] = spin(0, 9, 0)
        for key in ("output_mode", "compression"):
            field(zip_form, tr, key, self.controls[key])
        zip_form.addRow(label(tr, "zip_notice", True))
        org_form = QFormLayout(organization)
        self.controls["organization"] = combo(
            tr,
            [
                "flat",
                "channel",
                "artist",
                "album",
                "playlist",
                "date",
                "platform",
                "type",
                "resolution",
            ],
        )
        field(org_form, tr, "organization", self.controls["organization"])
        self.controls["name_primary"] = combo(
            tr, ["title", "id", "uploader", "artist", "album", "upload_date"]
        )
        self.controls["name_secondary"] = combo(tr, ["id", "height", "upload_date", "none"])
        self.controls["name_prefix"] = QLineEdit()
        for key in ("name_primary", "name_secondary", "name_prefix"):
            field(org_form, tr, key, self.controls[key])
        self.preview = QLabel()
        field(org_form, tr, "name_preview", self.preview)
        self.controls["organization"].currentIndexChanged.connect(self.preview_name)
        self.controls["name_primary"].currentIndexChanged.connect(self.preview_name)
        self.controls["name_secondary"].currentIndexChanged.connect(self.preview_name)
        self.controls["name_prefix"].textChanged.connect(self.preview_name)
        tr.changed.connect(self.preview_name)
        self.preview_name()
        self.controls["sponsor_mode"] = combo(tr, ["off", "mark", "remove_segments"])
        field(org_form, tr, "sponsor_mode", self.controls["sponsor_mode"])
        self.controls["sponsor_categories"] = QLineEdit("sponsor")
        field(org_form, tr, "sponsor_categories", self.controls["sponsor_categories"])
        self.kind.currentIndexChanged.connect(self.containers)
        self.containers()

    def preview_name(self):
        from ..paths import safe_name

        kind = self.controls["organization"].currentData()
        title = self.tr("sample_title")
        channel = self.tr("sample_channel")
        artist = self.tr("sample_artist")
        album = self.tr("sample_album")
        playlist = self.tr("sample_playlist")
        samples = {
            "title": title,
            "id": "ID",
            "uploader": channel,
            "artist": artist,
            "album": album,
            "upload_date": "20261021",
            "height": "1080",
            "none": "",
        }
        primary = samples[self.controls["name_primary"].currentData() or "title"]
        secondary = samples[self.controls["name_secondary"].currentData() or "id"]
        prefix = self.controls["name_prefix"].text()
        name = (
            (safe_name(prefix) + " - " if prefix else "")
            + primary
            + (f" [{secondary}]" if secondary else "")
        )
        name += "." + (self.container.currentData() or "mp4")
        examples = {
            "flat": name,
            "channel": f"{channel}/{name}",
            "artist": f"{artist}/{name}",
            "album": f"{artist}/{album}/{name}",
            "playlist": f"{playlist}/001 - {name}",
            "date": f"20261021/{name}",
            "platform": f"YouTube/{name}",
            "type": f"{self.tr(self.kind.currentData())}/{name}",
            "resolution": f"1080/{name}",
        }
        self.preview.setText(examples.get(kind, ""))

    def containers(self):
        old = self.container.currentData()
        self.container.clear()
        values = (
            ["mp3", "m4a", "aac", "opus", "ogg", "wav", "flac", "original"]
            if self.kind.currentData() == "audio"
            else ["mp4", "mkv", "webm", "mov"]
        )
        for value in values:
            self.container.addItem(value.upper(), value)
        self.container.setCurrentIndex(max(0, self.container.findData(old)))

    def set_options(self, options):
        for key, control in self.controls.items():
            value = getattr(options, key)
            if key == "sponsor_mode" and value == "remove":
                value = "remove_segments"
            if isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(max(0, control.findData(value or "auto")))
            elif isinstance(control, QSpinBox):
                control.setValue(value)
            else:
                control.setText(value)

    def get_options(self, defaults):
        result = dict(defaults)
        for key, control in self.controls.items():
            if isinstance(control, QCheckBox):
                result[key] = control.isChecked()
            elif isinstance(control, QComboBox):
                result[key] = control.currentData()
            elif isinstance(control, QSpinBox):
                result[key] = control.value()
            else:
                result[key] = control.text().strip()
        for key in ("video_stream", "audio_stream"):
            if result[key] == "auto":
                result[key] = ""
        if result["sponsor_mode"] == "remove_segments":
            result["sponsor_mode"] = "remove"
        return Options.from_dict(result)

    def set_formats(self, formats):
        for box, codec in ((self.video_stream, "vcodec"), (self.audio_stream, "acodec")):
            selected = box.currentData()
            while box.count() > 1:
                box.removeItem(1)
            for item in formats:
                if item.get(codec) not in {None, "none"}:
                    name = f"{item['format_id']} · {item.get('ext')} · {item.get(codec)} · {item.get('height') or item.get('language') or ''}"
                    box.addItem(name, item["format_id"])
            box.setCurrentIndex(max(0, box.findData(selected)))
