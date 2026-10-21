import time

from PySide6.QtCore import QThread

from ytdlp_g.database import Database
from ytdlp_g.i18n import Translator
from ytdlp_g.settings import Settings
from ytdlp_g.tasks import Task
from ytdlp_g.ui.widgets import label
from ytdlp_g.ui.window import NAV, Window


def wait_until(qapp, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for Qt worker")


def test_translation_signal_updates_existing_widget(qapp):
    tr = Translator()
    widget = label(tr, "new_download")
    tr.set_language("es")
    assert widget.text() == "Nueva descarga"
    tr.set_language("en")
    assert widget.text() == "New download"


def test_worker_result_arrives_on_gui_thread_without_stdout(qapp):
    task = Task("health", {})
    received, errors, done = [], [], []
    task.result.connect(lambda data: received.append((data, QThread.currentThread())))
    task.error.connect(errors.append)
    task.finished.connect(lambda: done.append(True))
    task.start()
    wait_until(qapp, lambda: bool(done))
    assert not errors
    assert received[0][0]["app"] == "1.2.0"
    assert received[0][1] == qapp.thread()
    task.deleteLater()


def test_live_languages_keep_urls_and_options_and_navigation(qapp, tmp_path):
    settings = Settings(tmp_path / "settings.json")
    db = Database(tmp_path / "db")
    window = Window(settings, db)
    window.urls.setPlainText("https://example.org/authorized")
    window.options.quality.setCurrentIndex(window.options.quality.findData("720"))
    for language, heading in (
        ("es", "Nueva descarga"),
        ("en", "New download"),
        ("pt-BR", "Novo download"),
    ):
        window.language_box.setCurrentIndex(window.language_box.findData(language))
        assert window.sidebar.item(1).text() == heading
        assert window.urls.toPlainText() == "https://example.org/authorized"
        assert window.options.quality.currentData() == "720"
        for key in NAV:
            window.navigate(key)
            assert window.pages.currentIndex() == NAV.index(key)
    window.quit_app()


def test_gui_download_pipeline_to_history(qapp, tmp_path, media_url):
    settings = Settings(tmp_path / "settings.json")
    settings.values["destination"] = str(tmp_path / "downloads")
    settings.values["notifications"] = False
    db = Database(tmp_path / "db")
    window = Window(settings, db)
    window.urls.setPlainText(media_url)
    window.enqueue(True)
    wait_until(qapp, lambda: bool(db.jobs()) and db.jobs()[0]["status"] in {"failed", "completed"})
    assert db.jobs()[0]["status"] == "completed", db.jobs()[0]["error"]
    wait_until(qapp, lambda: not window.manager.active)
    window.refresh()
    assert window.library_table.rowCount() == 1
    assert db.jobs()[0]["files"]
    window.quit_app()


def test_cancel_worker_emits_cancelled_and_stops_process(qapp, tmp_path):
    # A non-routable local endpoint fails only after timeout; cancel after spawn.
    task = Task("inspect", {"url": "http://127.0.0.1:1/video", "playlist": False})
    errors, done = [], []
    task.error.connect(errors.append)
    task.finished.connect(lambda: done.append(True))
    task.start()
    wait_until(qapp, lambda: task.process.processId() > 0)
    task.cancel()
    wait_until(qapp, lambda: bool(done))
    assert errors[0]["code"] == "cancelled"
    assert not task.process.processId()


def test_restart_recovers_grouped_playlist_zip(qapp, tmp_path, media_url):
    from pathlib import Path

    from ytdlp_g.models import Options

    settings = Settings(tmp_path / "settings.json")
    settings.values["destination"] = str(tmp_path / "downloads")
    db_path = tmp_path / "db"
    db = Database(db_path)
    ids = [
        db.add_job(
            media_url,
            "Sample",
            settings.values["destination"],
            Options().to_dict() | {"_playlist_title": "List", "_playlist_index": index},
        )
        for index in (1, 2)
    ]
    batch_id = db.add_batch(
        {"ids": ids, "target": str(tmp_path / "List.zip"), "compression": 0, "preserve": False}
    )
    db.close()
    db = Database(db_path)
    window = Window(settings, db)
    window.start_queue()
    wait_until(
        qapp,
        lambda: (
            db.connection.execute("SELECT status FROM batches WHERE id=?", (batch_id,)).fetchone()[
                0
            ]
            in {"completed", "failed"}
        ),
    )
    assert (
        db.connection.execute("SELECT status FROM batches WHERE id=?", (batch_id,)).fetchone()[0]
        == "completed"
    )
    assert all(job["files"] == [str(tmp_path / "List.zip")] for job in db.jobs())
    assert Path(tmp_path / "List.zip").is_file()
    assert not list(Path(settings.values["destination"]).rglob("*.mp4"))
    wait_until(qapp, lambda: not window.manager.active and not window.tasks)
    window.quit_app()


def test_smoke_test_exits_without_active_task_dialog(tmp_path):
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "ytdlp_g.main", "--smoke-test"],
        env=os.environ | {"XDG_DATA_HOME": str(tmp_path), "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
