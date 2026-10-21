"""Bounded diagnostics with fixed codes, never raw extraction messages or URLs."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(root):
    logger = logging.getLogger("ytdlp_g")
    logger.setLevel(logging.INFO)
    root = Path(root) / "logs"
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        root / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.info("application_started")


def cleanup_temporary(destination):
    """Remove only app-owned staging directories, called after user confirmation."""
    import shutil

    root = Path(destination).resolve()
    if not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.is_symlink():
            continue
        if child.is_dir() and (
            child.name == ".ytdlp-g" or child.name.startswith((".ytdlpg-zip-", ".ytdlpg-convert-"))
        ):
            shutil.rmtree(child)
            removed += 1
    return removed


def clear_logs(root):
    logger = logging.getLogger("ytdlp_g")
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            handler.acquire()
            try:
                handler.stream.seek(0)
                handler.stream.truncate()
            finally:
                handler.release()
    for file in (Path(root) / "logs").glob("app.log.*"):
        file.unlink(missing_ok=True)
