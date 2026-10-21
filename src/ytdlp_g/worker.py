"""JSON-line worker protocol. Spawned with no console; stdout is machine-only."""

import json
import os
import sys
import traceback
from pathlib import Path

EVENTS = None


def emit(kind, data):
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
    from . import __version__
    from .archive import create_zip
    from .downloader import download, error_code, inspect
    from .media import convert, probe, version

    try:
        request = json.loads(Path(request_path).read_text("utf-8"))
        action, payload = request["action"], request["payload"]

        def progress(data):
            emit("progress", data)

        if action == "lite_inspect":
            from .lite import inspect_lite

            result = inspect_lite(payload["url"], progress)
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
    except BaseException as exc:
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
