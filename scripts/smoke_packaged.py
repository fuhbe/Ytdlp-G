"""Exercise a relocated Windows package using its executable and bundled tools.

The test driver uses development Python on CI. Every application operation runs
inside the frozen EXE, with system Python/FFmpeg/QuickJS removed from its PATH.
"""

import argparse
import functools
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def check_pe(path):
    with path.open("rb") as incoming:
        assert incoming.read(2) == b"MZ", "Not a Windows executable"
        incoming.seek(0x3C)
        offset = struct.unpack("<I", incoming.read(4))[0]
        incoming.seek(offset)
        assert incoming.read(4) == b"PE\0\0"
        assert struct.unpack("<H", incoming.read(2))[0] == 0x8664, "Expected x64"
        incoming.seek(offset + 24)
        assert struct.unpack("<H", incoming.read(2))[0] == 0x20B, "Expected PE32+"
        incoming.seek(offset + 24 + 68)
        assert struct.unpack("<H", incoming.read(2))[0] == 2, "Expected GUI subsystem"


def run_smoke(package, report):
    package = package.resolve(strict=True)
    executable = package / "Ytdlp-G.exe"
    tools = package / "_internal" / "bin"
    check_pe(executable)
    assert (package / "_internal" / "python312.dll").is_file()
    for filename in ("ffmpeg.exe", "ffprobe.exe", "qjs.exe"):
        assert (tools / filename).is_file(), filename
    assert (package / "licenses" / "python" / "manifest.json").is_file()
    environment = os.environ.copy()
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for variable in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        environment.pop(variable, None)
    process_options = {
        "env": environment,
        "capture_output": True,
        "text": True,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }
    evidence = {
        "executable": executable.name,
        "architecture": "x64",
        "subsystem": "GUI",
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "checks": [],
    }
    with tempfile.TemporaryDirectory(prefix="Ytdlp-G smoke ") as temporary:
        root = Path(temporary)
        environment["LOCALAPPDATA"] = str(root / "appdata")
        sequence = 0

        def worker(action, payload):
            nonlocal sequence
            sequence += 1
            request, events = root / f"request-{sequence}.json", root / f"events-{sequence}.jsonl"
            request.write_text(json.dumps({"action": action, "payload": payload}), "utf-8")
            result = subprocess.run(
                [str(executable), "--worker", str(request), str(events)],
                timeout=120,
                **process_options,
            )
            messages = (
                [json.loads(line) for line in events.read_text("utf-8").splitlines()]
                if events.exists()
                else []
            )
            errors = [event["data"] for event in messages if event["kind"] == "error"]
            assert result.returncode == 0 and not errors, (action, result.returncode, errors)
            results = [event["data"] for event in messages if event["kind"] == "result"]
            assert results, (action, "No result from frozen worker")
            evidence["checks"].append(action)
            return results[-1]

        health = worker("health", {})
        assert all(
            health.get(tool, "dependency_missing") != "dependency_missing"
            for tool in ("ffmpeg", "ffprobe", "quickjs")
        )
        evidence["versions"] = health
        gui = subprocess.run([str(executable), "--smoke-test"], timeout=60, **process_options)
        assert gui.returncode == 0, ("GUI smoke", gui.returncode)
        evidence["checks"].append("GUI + dependency worker")

        fixture = root / "authorized sample.mp4"
        subprocess.run(
            [
                str(tools / "ffmpeg.exe"),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x90:rate=15",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440",
                "-t",
                "2",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                str(fixture),
            ],
            check=True,
            timeout=30,
            **process_options,
        )
        original_digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
        output = str(root / "outputs")
        audio = worker(
            "convert", {"source": str(fixture), "destination": output, "container": "mp3"}
        )
        audio_info = worker("probe", {"source": audio["files"][0]})
        assert audio_info["streams"][0]["codec_name"] == "mp3"
        remux = worker(
            "convert",
            {"source": str(fixture), "destination": output, "container": "mkv", "remux": True},
        )
        cut = worker(
            "convert",
            {
                "source": str(fixture),
                "destination": output,
                "container": "mp4",
                "start": "00:00:00.5",
                "end": "00:00:01.5",
                "precise": True,
            },
        )
        cut_info = worker("probe", {"source": cut["files"][0]})
        assert abs(float(cut_info["format"]["duration"]) - 1) < 0.15
        archived = worker(
            "zip",
            {
                "sources": [audio["files"][0], remux["files"][0], cut["files"][0]],
                "target": str(root / "results.zip"),
                "compression": 0,
                "preserve": True,
            },
        )
        with zipfile.ZipFile(archived["files"][0]) as archive:
            assert len(archive.namelist()) == 3 and archive.testzip() is None
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == original_digest

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(root))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/authorized%20sample.mp4"
            lite = worker("lite_inspect", {"url": url})
            assert {c["key"] for c in lite["choices"]} >= {"video:mp4:90", "audio:aac:0"}
            native = worker(
                "lite_download",
                {
                    "analysis": lite,
                    "quality": "audio:aac:0",
                    "mode": "normal",
                    "destination": str(root / "lite audio"),
                },
            )
            native_info = worker("probe", {"source": native["files"][0]})
            assert len(native_info["streams"]) == 1
            assert native_info["streams"][0]["codec_name"] == "aac"
            lite_zip = worker(
                "lite_download",
                {
                    "analysis": lite,
                    "quality": "video:mp4:90",
                    "mode": "zip",
                    "destination": str(root / "lite zip"),
                },
            )
            assert len(lite_zip["files"]) == 1 and lite_zip["files"][0].endswith(".zip")
            with zipfile.ZipFile(lite_zip["files"][0]) as archive:
                assert len(archive.namelist()) == 1 and archive.testzip() is None
            assert list((root / "lite zip").rglob("*.mp4")) == []
            (root / "playlist.html").write_text(
                '<html><head><title>Two videos</title></head><body><video src="authorized%20sample.mp4" controls></video><video src="authorized%20sample.mp4?second" controls></video></body></html>',
                "utf-8",
            )
            playlist = worker(
                "lite_inspect", {"url": f"http://127.0.0.1:{server.server_port}/playlist.html"}
            )
            assert len(playlist["items"]) == 2
            playlist_zip = worker(
                "lite_download",
                {
                    "analysis": playlist,
                    "quality": "audio:aac:0",
                    "mode": "zip",
                    "destination": str(root / "playlist zip"),
                },
            )
            assert playlist_zip["completed"] == 2
            with zipfile.ZipFile(playlist_zip["files"][0]) as archive:
                assert len(archive.namelist()) == 2 and archive.testzip() is None
                assert all(name.endswith(".m4a") for name in archive.namelist())
            mp3 = worker(
                "lite_download",
                {
                    "analysis": lite,
                    "quality": "audio:mp3:convert",
                    "mode": "normal",
                    "destination": str(root / "mp3 normal"),
                },
            )
            mp3_info = worker("probe", {"source": mp3["files"][0]})
            assert len(mp3_info["streams"]) == 1
            assert mp3_info["streams"][0]["codec_name"] == "mp3"
            assert int(mp3_info["streams"][0]["bit_rate"]) == 320000
            mp3_zip = worker(
                "lite_download",
                {
                    "analysis": playlist,
                    "quality": "audio:mp3:convert",
                    "mode": "zip",
                    "destination": str(root / "mp3 playlist zip"),
                },
            )
            assert mp3_zip["completed"] == 2
            with zipfile.ZipFile(mp3_zip["files"][0]) as archive:
                assert len(archive.namelist()) == 2 and archive.testzip() is None
                assert all(name.endswith(".mp3") for name in archive.namelist())
            info = worker("inspect", {"url": url})
            assert info["formats"]
            downloaded = worker(
                "download",
                {
                    "id": "packaged-smoke",
                    "url": url,
                    "destination": str(root / "download destination with spaces"),
                    "options": {"output_mode": "both"},
                },
            )
            assert any(path.endswith(".mp4") for path in downloaded["files"])
            for path in downloaded["files"]:
                assert Path(path).is_file()
                if path.endswith(".zip"):
                    with zipfile.ZipFile(path) as archive:
                        assert archive.testzip() is None
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    evidence["result"] = "passed"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, indent=2), "utf-8")
    print(
        f"Packaged smoke passed: {len(evidence['checks'])} checks; system tools excluded from PATH"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--report", type=Path, default=Path("build/packaged-smoke.json"))
    arguments = parser.parse_args()
    run_smoke(arguments.package, arguments.report)
