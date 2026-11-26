# ruff: noqa: B023
# timed() invokes each closure synchronously inside its iteration.
import functools
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yt_dlp import YoutubeDL

from ytdlp_g import lite
from ytdlp_g.archive import create_zip
from ytdlp_g.paths import publish

orig = YoutubeDL.extract_info
calls = 0


def counted(*a, **kw):
    global calls
    calls += 1
    return orig(*a, **kw)


YoutubeDL.extract_info = counted


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


rows = {}


def timed(key, fn):
    start = time.perf_counter()
    result = fn()
    rows.setdefault(key, []).append(time.perf_counter() - start)
    return result


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    src = root / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(src),
        ],
        check=True,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=d))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    blob = root / "blob"
    blob.write_bytes(os.urandom(32 << 20))
    for i in range(3):
        url = f"http://127.0.0.1:{server.server_port}/sample.mp4?item={i}"
        prior = calls
        a = timed("inspect", lambda: lite.inspect_lite(url))
        first = []
        start = time.perf_counter()
        result = timed(
            "download",
            lambda: lite.download_lite(
                dict(
                    analysis=a,
                    quality="video:mp4:360",
                    mode="normal",
                    destination=str(root / "out"),
                ),
                lambda e: (
                    first.append(time.perf_counter())
                    if e.get("status") == "running" and not first
                    else None
                ),
            ),
        )
        rows.setdefault("first_byte", []).append(first[0] - start)
        rows.setdefault("extractions", []).append(calls - prior)
        timed("repeat_inspect", lambda: lite.inspect_lite(url))
        target = timed(
            "publish32",
            lambda: publish(
                blob,
                root / "copy",
                **({"immutable": True} if "immutable" in publish.__code__.co_varnames else {}),
            ),
        )
        target.unlink()
        target = timed("zip32", lambda: create_zip([blob], root / "a.zip"))
        target.unlink()
        for preset in ["medium", "fast", "faster", "veryfast"]:
            out = root / "encoded.mp4"
            timed(
                preset,
                lambda: subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(src),
                        "-threads",
                        "2",
                        "-c:v",
                        "libx264",
                        "-preset",
                        preset,
                        "-crf",
                        "18",
                        "-c:a",
                        "copy",
                        str(out),
                    ],
                    check=True,
                ),
            )
            rows.setdefault(preset + "_bytes", []).append(out.stat().st_size)
        timed(
            "startup_health",
            lambda: subprocess.run(
                [sys.executable, "-m", "ytdlp_g.main", "--smoke-test"],
                check=True,
                env=os.environ | {"QT_QPA_PLATFORM": "offscreen"},
            ),
        )
    server.shutdown()
print(json.dumps({key: statistics.median(vals) for key, vals in rows.items()}))
