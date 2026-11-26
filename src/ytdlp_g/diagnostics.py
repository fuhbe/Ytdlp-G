"""Bounded diagnostics with fixed codes, never raw extraction messages or URLs."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(root, worker=False):
    logger = logging.getLogger("ytdlp_g")
    logger.setLevel(logging.INFO)
    root = Path(root) / "logs"
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        root / ("worker.log" if worker else "app.log"),
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
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


def diagnostic(stage, exc, index=0, attempt=1, encoder=None):
    """Only export recognized signals from third-party text, never arbitrary substrings."""
    import re

    from yt_dlp.version import __version__

    from .downloader import error_code

    message = str(exc)
    status = re.search(r"(?i)\b(?:HTTP(?: Error| error| status)?[: ]+)([45][0-9]{2})\b", message)
    result = dict(
        stage=stage,
        index=index,
        attempt=attempt,
        code=error_code(exc),
        type=type(exc).__name__,
        engine=__version__,
    )
    for fragment, reason in (
        ("signature solving failed", "signature_solver"),
        ("challenge solving failed", "player_challenge"),
        ("javascript runtime", "javascript_runtime"),
        ("requested format", "missing_format"),
        ("sabr", "sabr"),
        ("po token", "po_token"),
        ("login", "authentication"),
        ("429", "rate_limit"),
        ("timed out", "timeout"),
        ("invalid data found", "invalid_stream"),
        ("could not write header", "mux_header"),
        ("unknown encoder", "encoder_missing"),
        ("error initializing", "encoder_initialization"),
        ("no space left", "disk_full"),
        ("permission denied", "access_denied"),
        ("connection reset", "connection_reset"),
        ("unable to download fragment", "fragment"),
        ("aria2c", "aria2c"),
    ):
        if fragment in message.lower():
            result["reason"] = reason
            break
    if status:
        result["http"] = int(status[1])
    if encoder:
        result["encoder"] = encoder
    if isinstance(exc, OSError):
        result["errno"] = exc.errno
    if result["code"] == "operation_failed":
        result["code"] = {
            "extraction": "extract_failed",
            "download": "transfer_failed",
            "publish": "publish_failed",
            "zip": "zip_failed",
            "conversion": "conversion_failed",
            "merge": "merge_failed",
        }.get(stage, "operation_failed")
    logging.getLogger("ytdlp_g").warning("%s", result)
    return result
