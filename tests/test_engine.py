"""Updater integrity, offline recovery, cadence and actual worker activation."""

import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile

import pytest

from ytdlp_g import engine


def wheel(package, extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(package + "/__init__.py", "")
        if extra:
            archive.writestr(*extra)
    return stream.getvalue()


@pytest.fixture
def upstream(monkeypatch):
    payloads = {}
    for name, version in [("yt-dlp", "2099.1.1"), ("yt-dlp-ejs", "0.8.0")]:
        content = wheel(name.replace("-", "_"))
        url = "https://files.pythonhosted.org/" + name + ".whl"
        payloads[url] = content
        payloads[
            "https://pypi.org/pypi/" + name + ("/0.8.0" if name.endswith("ejs") else "") + "/json"
        ] = json.dumps(
            {
                "info": {
                    "version": version,
                    "requires_python": ">=3.11",
                    "requires_dist": ['yt-dlp-ejs==0.8.0; extra == "default"'],
                },
                "urls": [
                    {
                        "url": url,
                        "filename": name + "-py3-none-any.whl",
                        "digests": {"sha256": hashlib.sha256(content).hexdigest()},
                    }
                ],
            }
        ).encode()
    monkeypatch.setattr(engine, "fetch", lambda url, limit=0: payloads[url])
    return payloads


def test_atomic_pair_update_and_daily_cadence(tmp_path, upstream, monkeypatch):
    state = engine.prepare_engine(root=tmp_path)
    assert state["status"] == "updated" and state["ejs"] == "0.8.0"
    assert engine.cached_engine(tmp_path)["version"] == "2099.1.1"
    monkeypatch.setattr(engine, "fetch", lambda *args: pytest.fail("Checked twice within one day"))
    assert engine.prepare_engine(root=tmp_path)["status"] == "cached"
    engine.atomic_json(tmp_path / "check.json", {"checked": time.time() - 25 * 3600})
    calls = []

    def offline(*args):
        calls.append(True)
        raise OSError("offline")

    monkeypatch.setattr(engine, "fetch", offline)
    failed = engine.prepare_engine(root=tmp_path)
    assert calls and failed["status"] == "offline"
    assert failed["path"] == state["path"]


def test_corrupt_download_keeps_active_pair(tmp_path, upstream):
    first = engine.prepare_engine(root=tmp_path)
    current = (tmp_path / "current.json").read_bytes()
    upstream["https://files.pythonhosted.org/yt-dlp-ejs.whl"] = b"corrupted"
    # Force a later engine release so the entire pair has to be downloaded.
    url = "https://pypi.org/pypi/yt-dlp/json"
    data = json.loads(upstream[url])
    data["info"]["version"] = "2099.1.2"
    upstream[url] = json.dumps(data).encode()
    failed = engine.prepare_engine(force=True, root=tmp_path)
    assert failed["status"] == "offline" and failed["path"] == first["path"]
    assert (tmp_path / "current.json").read_bytes() == current
    assert not list(tmp_path.glob(".update-*"))


@pytest.mark.parametrize(
    "member", ["../escape.py", "/escape.py", "yt_dlp/../../escape.py", "yt_dlp\\escape.py"]
)
def test_rejects_archive_traversal(tmp_path, monkeypatch, member):
    content = wheel("yt_dlp", (member, "bad"))
    monkeypatch.setattr(engine, "fetch", lambda *args: content)
    meta = {
        "urls": [
            {
                "filename": "engine-py3-none-any.whl",
                "url": "x",
                "digests": {"sha256": hashlib.sha256(content).hexdigest()},
            }
        ]
    }
    with pytest.raises(ValueError, match="engine_update_failed"):
        engine.install_wheel(meta, tmp_path, "yt_dlp")


def test_update_lock_and_incompatible_python(tmp_path, upstream):
    (tmp_path / "update.lock").touch()
    assert engine.prepare_engine(root=tmp_path)["status"] == "busy"
    (tmp_path / "update.lock").unlink()
    url = "https://pypi.org/pypi/yt-dlp/json"
    data = json.loads(upstream[url])
    data["info"]["requires_python"] = ">=99"
    upstream[url] = json.dumps(data).encode()
    assert engine.prepare_engine(force=True, root=tmp_path)["status"] == "offline"
    assert not (tmp_path / "current.json").exists()


def test_cached_engine_activation_precedes_bundled_import(tmp_path, upstream):
    state = engine.prepare_engine(root=tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from ytdlp_g.engine import activate_engine; "
            "activate_engine(json.loads(sys.argv[1])); import yt_dlp; print(yt_dlp.__file__)",
            json.dumps(state),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert state["path"] in result.stdout


def test_failed_import_falls_back_to_bundled(tmp_path):
    package = tmp_path / "yt_dlp"
    package.mkdir()
    (package / "__init__.py").write_text('raise RuntimeError("incompatible engine")')
    state = {"path": str(tmp_path)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from ytdlp_g.engine import activate_engine; "
            "print(json.dumps(activate_engine(json.loads(sys.argv[1]))))",
            json.dumps(state),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["status"] == "fallback"
