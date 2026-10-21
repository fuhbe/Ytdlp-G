"""Qt process orchestration: all signals are delivered on the GUI thread."""

import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTemporaryDir, QTimer, Signal

from .database import ACTIVE
from .media import hidden_process


class Task(QObject):
    progress = Signal(dict)
    result = Signal(dict)
    error = Signal(dict)
    finished = Signal()

    def __init__(self, action, payload, parent=None):
        super().__init__(parent)
        self.action, self.payload = action, payload
        self.process = QProcess(self)
        self.workspace = QTemporaryDir()
        self.events_path = Path(self.workspace.path()) / "events.jsonl"
        self.request_path = Path(self.workspace.path()) / "request.json"
        self.offset = 0
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(100)
        self.poll_timer.timeout.connect(self.read)
        self.buffer = bytearray()
        self.outcome = False
        self.cancelled = False
        self.process.readyReadStandardOutput.connect(lambda: self.process.readAllStandardOutput())
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self.done)
        self.process.errorOccurred.connect(self.process_error)

    def start(self):
        self.request_path.write_text(
            json.dumps({"action": self.action, "payload": self.payload}), "utf-8"
        )
        args = ["--worker", str(self.request_path), str(self.events_path)]
        self.poll_timer.start()
        if getattr(sys, "frozen", False):
            self.process.start(sys.executable, args)
        else:
            self.process.start(sys.executable, ["-m", "ytdlp_g.main", *args])

    def read(self):
        if not self.events_path.exists():
            return
        with self.events_path.open("rb") as incoming:
            incoming.seek(self.offset)
            chunk = incoming.read()
            self.offset += len(chunk)
            self.buffer.extend(chunk)
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if event.get("kind") == "progress":
                self.progress.emit(event["data"])
            elif event.get("kind") in {"result", "error"}:
                self.outcome = True
                if event["kind"] == "error":
                    logging.getLogger("ytdlp_g").warning(
                        "worker_error action=%s code=%s type=%s trace=%s",
                        self.action,
                        event["data"].get("code"),
                        event["data"].get("type"),
                        event["data"].get("trace"),
                    )
                getattr(self, event["kind"]).emit(event["data"])

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.poll_timer.stop()
            self.outcome = True
            self.error.emit({"code": "operation_failed", "type": "ProcessStart"})
            self.finished.emit()

    def done(self, *args):
        self.poll_timer.stop()
        self.read()
        if not self.outcome:
            self.error.emit(
                {
                    "code": "cancelled" if self.cancelled else "operation_failed",
                    "type": "ProcessExit",
                }
            )
        self.finished.emit()

    def cancel(self):
        self.cancelled = True
        pid = self.process.processId()
        if not pid:
            return
        if os.name == "nt":
            # Terminate the entire tree, including FFmpeg, without a console.
            self.killer = subprocess.Popen(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **hidden_process(),
            )
            self.kill_timer = QTimer(self)

            def finish_kill():
                if self.killer.poll() is not None:
                    self.process.kill()
                    self.kill_timer.stop()

            self.kill_timer.timeout.connect(finish_kill)
            self.kill_timer.start(50)
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                self.process.kill()
            self.process.kill()


class QueueManager(QObject):
    changed = Signal()
    notification = Signal(str)

    def __init__(self, database, settings, parent=None):
        super().__init__(parent)
        self.db, self.settings = database, settings
        self.active = {}
        self.enabled = False
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.pump)
        self.timer.start()

    def pump(self):
        if not self.enabled:
            return
        slots = int(self.settings.values["concurrency"]) - len(self.active)
        for job in [j for j in self.db.jobs() if j["status"] == "queued"][: max(0, slots)]:
            identifier = job["id"]
            payload = job | {
                "playlist_title": job["options"].get("_playlist_title", ""),
                "playlist_index": job["options"].get("_playlist_index"),
            }
            task = Task("download", payload, self)
            self.active[identifier] = task
            self.db.update(identifier, status="running", error="")
            task.progress.connect(lambda data, key=identifier: self.on_progress(key, data))
            task.result.connect(lambda data, key=identifier: self.on_result(key, data))
            task.error.connect(lambda data, key=identifier: self.on_error(key, data))
            task.finished.connect(lambda key=identifier, worker=task: self.release(key, worker))
            task.start()
            self.notification.emit("download_started")
            self.changed.emit()

    def on_progress(self, identifier, data):
        allowed = {"status", "progress", "downloaded", "total", "speed", "eta", "estimated"}
        self.db.update(identifier, **{key: value for key, value in data.items() if key in allowed})
        self.changed.emit()

    def on_result(self, identifier, data):
        self.db.update(
            identifier,
            status="completed",
            files=data["files"],
            title=data.get("title", ""),
            progress=100,
            speed=0,
            eta=0,
        )
        self.notification.emit("download_completed")

    def on_error(self, identifier, data):
        self.db.update(
            identifier,
            status="cancelled" if data["code"] == "cancelled" else "failed",
            error=data["code"],
            speed=0,
            eta=0,
        )
        self.notification.emit(data["code"])

    def release(self, identifier, task):
        self.active.pop(identifier, None)
        task.deleteLater()
        self.changed.emit()

    def cancel(self, identifier):
        if identifier in self.active:
            self.active[identifier].cancel()
        else:
            job = next((job for job in self.db.jobs() if job["id"] == identifier), None)
            if job and job["status"] in {"queued", "interrupted"}:
                self.db.update(identifier, status="cancelled")
            self.changed.emit()

    def retry(self, identifier):
        job = next((j for j in self.db.jobs() if j["id"] == identifier), None)
        if job and job["status"] not in ACTIVE and identifier not in self.active:
            self.db.update(identifier, status="queued", error="", progress=0)
            self.changed.emit()

    def shutdown(self):
        self.enabled = False
        self.timer.stop()
        for task in list(self.active.values()):
            task.cancel()
            task.process.waitForFinished(5000)
