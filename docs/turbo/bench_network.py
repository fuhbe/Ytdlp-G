# ruff: noqa: B023
# timed() invokes each closure synchronously inside its iteration.
import functools
import json
import resource
import statistics
import subprocess
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ytdlp_g import lite


class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith(".ts"):
            time.sleep(0.04)
        super().do_GET()

    def log_message(self, *x):
        pass


def command(*args):
    return subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, check=True)


stats = {}


def metric(k, val):
    stats.setdefault(k, []).append(val)


def timed(k, fun):
    st = time.perf_counter()
    result = fun()
    metric(k, time.perf_counter() - st)
    return result


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    src = root / "clip.mp4"
    command(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=640x360:r=24",
        "-f",
        "lavfi",
        "-i",
        "sine",
        "-t",
        "8",
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-g",
        "12",
        "-c:a",
        "aac",
        str(src),
    )
    command(
        "-i",
        str(src),
        "-c",
        "copy",
        "-hls_time",
        ".5".replace(".5", "0.5"),
        "-hls_list_size",
        "0",
        str(root / "stream.m3u8"),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=d))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    (root / "list.html").write_text(
        "<html><head><title>List</title></head><body>"
        + "".join(f'<video src="clip.mp4?n={n}" controls></video>' for n in range(6))
        + "</body></html>"
    )
    for i in range(3):
        for page, key, typ in [
            ("stream.m3u8", "video:best", "hls"),
            ("list.html", "audio:mp3:convert", "list"),
        ]:
            a = timed(typ + "_inspect", lambda: lite.inspect_lite(base + page + "?i=" + str(i)))
            chosen = next(
                (c["key"] for c in a["choices"] if c["key"] == key), a["choices"][0]["key"]
            )
            r = timed(
                typ + "_total",
                lambda: lite.download_lite(
                    dict(
                        analysis=a, quality=chosen, mode="normal", destination=str(root / f"out{i}")
                    )
                ),
            )
            assert r["completed"] == len(a["items"]) and not r["failed"]
            size = sum(Path(p).stat().st_size for p in r["files"])
            metric(typ + "_bytes", size)
            metric(typ + "_effective_mib_s", size / stats[typ + "_total"][-1] / 2**20)
    for preset in ("medium", "fast", "faster", "veryfast"):
        out = root / "enc.mp4"
        timed(
            preset,
            lambda: command(
                "-i",
                str(src),
                "-threads",
                "2",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                preset,
                "-c:a",
                "copy",
                str(out),
            ),
        )
        run = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(src),
                "-i",
                str(out),
                "-lavfi",
                "ssim",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        metric(preset + "_ssim", float(run.stderr.rsplit("All:", 1)[1].split()[0]))
        metric(preset + "_bytes", out.stat().st_size)
    for whom, k in [(resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "child")]:
        use = resource.getrusage(whom)
        metric(k + "_maxrss_kib", use.ru_maxrss)
        metric(k + "_cpu_s", use.ru_utime + use.ru_stime)
        metric(k + "_input_blocks", use.ru_inblock)
        metric(k + "_output_blocks", use.ru_oublock)
    server.shutdown()
print(json.dumps({k: statistics.median(v) for k, v in stats.items()}))
