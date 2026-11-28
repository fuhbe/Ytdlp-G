"""Exercise exact CLI distributions on clean Windows, using only local media."""

import functools
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

single, portable, artifacts = (Path(arg).resolve() for arg in sys.argv[1:])
checks = []
timings = []


def run(label, command, stdin="", expect_json=False):
    start = time.perf_counter()
    p = subprocess.run(
        [str(w) for w in command],
        input=stdin,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=240,
        env=env,
    )
    elapsed = time.perf_counter() - start
    if p.returncode:
        raise RuntimeError((label, p.stdout, p.stderr))
    checks.append(label)
    timings.append((label, elapsed))
    return json.loads(p.stdout) if expect_json else p.stdout


with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    env = os.environ.copy()
    env.update(YTDLPG_CLI_HOME=str(root / "db"), PYTHONIOENCODING="utf-8")
    env["PATH"] = (
        os.path.join(os.environ["SystemRoot"], "System32") + os.pathsep + os.environ["SystemRoot"]
    )
    tools = portable.parent / "_internal" / "bin"
    ffmpeg = tools / "ffmpeg.exe"
    source = root / "sample.mp4"
    run(
        "fixture",
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=640x360:r=25",
            "-f",
            "lavfi",
            "-i",
            "sine=r=48000",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-ac",
            "2",
            "-c:a",
            "aac",
            source,
        ],
    )
    assert "0.1.0-beta.1" in run("single version", [single, "--version"])
    assert "YTDLP-G CLI" in run("single menu", [single], "0\n")
    assert (
        run("single doctor", [single, "doctor", "--json"], expect_json=True)["status"] == "complete"
    )
    health = run("portable doctor", [portable, "doctor", "--json"], expect_json=True)
    assert all(
        Path(tool).is_relative_to(portable.parent) for tool in health["dependencies"].values()
    )
    assert "libx264" in health["encoders"]
    env["PATH"] = str(portable.parent) + os.pathsep + env["PATH"]
    for shell, command in (
        ("CMD", ["cmd.exe", "/d", "/c", "ytdlp-g.exe --version"]),
        (
            "PowerShell",
            [
                str(
                    Path(os.environ["SystemRoot"])
                    / "System32/WindowsPowerShell/v1.0/powershell.exe"
                ),
                "-NoProfile",
                "-Command",
                f"& '{portable}' --version",
            ],
        ),
    ):
        assert "0.1.0-beta.1" in run(shell, command)
    for language in ("pt-BR", "en", "es"):
        run("language " + language, [portable, "config", "--language", language])
        assert "YTDLP-G CLI" in run("portable menu " + language, [portable], "0\n")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/sample.mp4"
    outputs = {}
    try:
        for engine in ("native", "aria2c"):
            dest = root / engine
            res = run(
                "download " + engine,
                [
                    portable,
                    "download",
                    "--input-file",
                    "-",
                    "--downloader",
                    engine,
                    "--quality",
                    "1080",
                    "--json",
                    "-o",
                    dest,
                ],
                url + "\n" + url + "\n",
                True,
            )
            path = Path(res["jobs"][0]["files"][0])
            outputs[engine] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            run(
                "decode " + engine,
                [ffmpeg, "-v", "error", "-xerror", "-i", path, "-f", "null", "-"],
            )
        res = run(
            "mp3 zip",
            [portable, "download", url, "--mp3", "--zip", "-o", root / "zip", "--json"],
            expect_json=True,
        )
        with zipfile.ZipFile(res["jobs"][0]["files"][0]) as z:
            assert z.testzip() is None and any(n.endswith(".mp3") for n in z.namelist())
        res = run(
            "convert offline",
            [portable, "convert", source, "--copy-compatible", "-o", root / "offline", "--json"],
            expect_json=True,
        )
        assert Path(res["files"][0]).is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
report = dict(system=platform.platform(), checks=checks, encoders=health["encoders"], files=outputs)
(artifacts / "validation.json").write_text(json.dumps(report, indent=2), "utf-8")
lines = [
    "# Medições da edição CLI",
    "",
    platform.platform(),
    "",
    "Mídia local de 2 s, 640×360 a 25 FPS. Um ensaio por operação, incluindo inicialização do processo. Os tempos incluem análise, verificação e operações de disco. HTTP em loopback. Uso de CPU e GPU não instrumentado.",
    "",
    "| Operação | Segundos |",
    "|---|---:|",
]
lines += [f"| {name} | {elapsed:.3f} |" for name, elapsed in timings]
lines += [
    "",
    "Tamanho e SHA-256 dos MP4 disponíveis em validation.json. GPU física, Windows 10/11 cliente e YouTube público precisam de validação separada.",
]
(artifacts / "benchmarks.md").write_text("\n".join(lines) + "\n", "utf-8")
