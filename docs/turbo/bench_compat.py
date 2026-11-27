"""Compare Beta 2 and Beta 3 with identical inputs and a loopback HTTP server."""

import functools
import inspect
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ytdlp_g import lite, media, turbo


def run(*args):
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *map(str, args)],
        capture_output=True,
        text=True,
        check=True,
    )


def measure(root):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    turbo.configure({"encoder": "libx264", "downloader": "native"})
    new = "profile" in inspect.signature(media.ensure_mp4).parameters
    rows = {}
    try:
        for label, name in [
            ("download", "avc.mp4"),
            ("remux", "remux.mkv"),
            ("encode", "ffv1.mkv"),
            ("av1", "av1.mp4"),
        ]:
            times = []
            source = root / name
            for _ in range(3):
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp)
                    if label == "download":
                        url = f"http://127.0.0.1:{server.server_port}/avc.mp4"
                        analysis = lite.inspect_lite(url)
                        start = time.perf_counter()
                        result = lite.download_lite(
                            dict(
                                analysis=analysis, quality=lite.BEST, mode="normal", destination=tmp
                            )
                        )
                        assert result["status"] == "complete"
                        output = Path(result["files"][0])
                    else:
                        work = p / source.name
                        shutil.copyfile(source, work)
                        start = time.perf_counter()
                        output = media.ensure_mp4(
                            work, **({"profile": "compatible"} if new else {})
                        )
                    times.append(time.perf_counter() - start)
                    score = run(
                        "-i", source, "-i", output, "-lavfi", "ssim", "-an", "-f", "null", "-"
                    )
                    rows[label] = {
                        "bytes": output.stat().st_size,
                        "ssim": float(re.search(r"All:([\d.]+)", score.stderr)[1]),
                    }
            rows[label]["seconds"] = statistics.median(times)
        return rows
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "avc.mp4").exists():
        run(
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=25",
            "-f",
            "lavfi",
            "-i",
            "sine=r=48000",
            "-t",
            2,
            "-c:v",
            "libx264",
            "-threads",
            2,
            "-c:a",
            "aac",
            "-ac",
            2,
            folder / "avc.mp4",
        )
        for name, options in [
            ("remux.mkv", ["-c:v", "copy"]),
            ("av1.mp4", ["-c:v", "libaom-av1", "-cpu-used", "8"]),
            ("ffv1.mkv", ["-c:v", "ffv1"]),
        ]:
            run("-i", folder / "avc.mp4", *options, "-threads", 2, "-c:a", "copy", folder / name)
    print(json.dumps(measure(folder), indent=2))
