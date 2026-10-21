"""GUI entry point, isolated worker entry and CI smoke mode."""

import os
import sys


def main():
    if "--worker" in sys.argv:
        from .worker import main as worker_main

        return worker_main()

    from PySide6.QtCore import QLockFile, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .database import Database
    from .diagnostics import configure_logging
    from .i18n import translate
    from .paths import data_dir
    from .settings import Settings
    from .ui.window import Window

    app = QApplication(sys.argv)
    app.setApplicationName("Ytdlp-G")
    app.setOrganizationName("Ytdlp-G")
    app.setStyle("Fusion")
    root = data_dir()
    settings = Settings(root / "settings.json")
    lock = QLockFile(str(root / "application.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "Ytdlp-G", translate(settings.values["language"], "already_running")
        )
        return 1
    configure_logging(root)
    database = Database(root / "library.sqlite3")
    window = Window(settings, database)
    window.show()
    smoke_failed = []
    if "--smoke-test" in sys.argv:
        window.smoke_mode = True

        def smoke_result(data):
            if any(data.get(tool) == "dependency_missing" for tool in ("ffmpeg", "ffprobe")):
                smoke_failed.append(True)

        def smoke_error(data):
            smoke_failed.append(True)

        smoke_task = window.run_task("health", {}, smoke_result, error=smoke_error)
        smoke_task.finished.connect(lambda: QTimer.singleShot(0, window.quit_app))
        QTimer.singleShot(30000, lambda: (smoke_failed.append(True), window.quit_app()))
    try:
        result = app.exec()
        return 1 if smoke_failed else result
    finally:
        lock.unlock()


if __name__ == "__main__":
    # Avoid Windows app-ID grouping with generic Python hosts.
    if os.name == "nt" and "--worker" not in sys.argv:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ytdlp-G.Desktop.1")
    raise SystemExit(main())
