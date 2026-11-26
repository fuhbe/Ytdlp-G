"""JSON-line worker protocol. Spawned with no console; stdout is machine-only."""

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

EVENTS = None
WRITE_LOCK = threading.RLock()
ENGINE = None


def emit(kind, data):
    with WRITE_LOCK:
        EVENTS.write(json.dumps({"kind": kind, "data": data}, ensure_ascii=True) + "\n")
        EVENTS.flush()


def main():
    global EVENTS
    index = sys.argv.index("--worker")
    request_path, events_path = sys.argv[index + 1 : index + 3]
    EVENTS = Path(events_path).open("w", encoding="utf-8")
    # Windowed PyInstaller has no standard streams. IPC is file-based in all modes.
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
    if os.name != "nt":
        try:
            os.setsid()
        except OSError:
            pass
    return dispatch(json.loads(Path(request_path).read_text("utf-8")))


def serve():
    import socket

    global EVENTS
    if os.name != "nt":
        os.setsid()
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
    with socket.create_connection(("127.0.0.1", int(sys.argv[-1])), timeout=15) as connection:
        connection.settimeout(None)
        with (
            connection.makefile("w", encoding="utf8") as EVENTS,
            connection.makefile("r", encoding="utf8") as requests,
        ):
            emit("hello", os.environ.pop("YTDLPG_SESSION_KEY"))
            for line in requests:
                dispatch(json.loads(line))
    return 0


def dispatch(request):
    global ENGINE
    from . import __version__
    from .archive import create_zip
    from .media import convert, probe, version

    if ENGINE is None:
        from .diagnostics import configure_logging
        from .paths import data_dir

        configure_logging(data_dir(), worker=True)
    try:
        action, payload = request["action"], request["payload"]

        last = {}

        def progress(data):
            phase = (data.get("phase"), data.get("status"), data.get("current"))
            now = time.monotonic()
            with WRITE_LOCK:
                if (
                    phase == last.get("phase")
                    and now - last["stamp"] < 0.12
                    and data.get("progress") != 100
                ):
                    return
                last.update(phase=phase, stamp=now)
                emit("progress", data)

        from .engine import activate_engine, prepare_engine

        if ENGINE is None:
            ENGINE = activate_engine(
                prepare_engine(
                    force=action == "engine_update",
                    check=action in {"engine_update", "engine_background"},
                    progress=progress,
                )
            )
        engine = ENGINE
        from . import turbo

        turbo.configure(payload.get("performance", {}))
        from .downloader import download, inspect

        if action in {"engine_update", "engine_background"}:
            result = engine
        elif action == "clear_cache":
            result = turbo.clear_cache()
        elif action == "lite_inspect":
            from .lite import inspect_lite

            result = inspect_lite(payload["url"], progress)
        elif action == "lite_zip_retry":
            from .lite import retry_zip

            result = retry_zip(payload, progress)
        elif action == "lite_download":
            from .lite import download_lite

            result = download_lite(payload, progress)
        elif action == "inspect":
            result = inspect(**payload)
        elif action == "download":
            result = download(payload, progress)
        elif action == "convert":
            result = convert(payload, progress)
        elif action == "probe":
            result = probe(payload["source"], payload.get("ffprobe", ""))
        elif action == "zip":
            result = {"files": [str(create_zip(progress=progress, **payload))]}
        elif action == "health":
            import yt_dlp.version

            result = {
                "app": __version__,
                "yt-dlp": yt_dlp.version.__version__,
                "python": sys.version.split()[0],
                "engine_source": "managed" if engine.get("path") else "bundled",
            }
            from yt_dlp.utils._jsruntime import QuickJsRuntime

            from .media import executable

            try:
                runtime = QuickJsRuntime(executable("qjs")).info
                result["quickjs"] = (
                    runtime.version if runtime and runtime.supported else "dependency_missing"
                )
            except (ValueError, OSError):
                result["quickjs"] = "dependency_missing"
            for tool in ("ffmpeg", "ffprobe"):
                try:
                    result[tool] = version(tool, payload.get(tool, ""))
                except (ValueError, OSError, TimeoutError):
                    result[tool] = "dependency_missing"
        else:
            raise ValueError("invalid_options")
        emit("result", result)
    except Exception as exc:
        from .downloader import error_code

        # Stack function names help diagnostics without disclosing URLs or paths.
        emit(
            "error",
            {
                "code": error_code(exc),
                "type": type(exc).__name__,
                "trace": [frame.name for frame in traceback.extract_tb(exc.__traceback__)],
            },
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
