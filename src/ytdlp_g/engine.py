"""Atomic per-user updates of the pure-Python yt-dlp engine and its EJS scripts."""

import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .paths import data_dir

CHECK_INTERVAL = 24 * 60 * 60
MAX_DOWNLOAD = 32 * 1024 * 1024


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(value), "utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        value = json.loads(path.read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def fetch(url, limit=MAX_DOWNLOAD):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"pypi.org", "files.pythonhosted.org"}:
        raise ValueError("engine_update_failed")
    request = urllib.request.Request(url, headers={"User-Agent": "Ytdlp-G engine updater"})
    with urllib.request.urlopen(request, timeout=15) as response:
        final = urlsplit(response.url)
        if final.scheme != "https" or final.hostname not in {"pypi.org", "files.pythonhosted.org"}:
            raise ValueError("engine_update_failed")
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("engine_update_failed")
    return content


def metadata(package, version=None):
    suffix = f"/{version}" if version else ""
    result = json.loads(fetch(f"https://pypi.org/pypi/{package}{suffix}/json", 2 * 1024 * 1024))
    info = result["info"]
    release = Version(info["version"])
    if release.is_prerelease or release.is_devrelease:
        raise ValueError("engine_update_failed")
    if not SpecifierSet(info.get("requires_python") or "").contains(
        ".".join(map(str, sys.version_info[:3]))
    ):
        raise ValueError("engine_update_failed")
    return result


def install_wheel(meta, target, package):
    asset = next(
        item
        for item in meta["urls"]
        if item["filename"].endswith("-py3-none-any.whl") and not item.get("yanked")
    )
    content = fetch(asset["url"])
    if hashlib.sha256(content).hexdigest() != asset["digests"]["sha256"]:
        raise ValueError("engine_update_failed")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        total = 0
        for member in archive.infolist():
            relative = PurePosixPath(member.filename)
            total += member.file_size
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in member.filename
                or not relative.parts
                or ":" in member.filename
                or total > MAX_DOWNLOAD * 4
                or (member.external_attr >> 16) & 0o170000 == 0o120000
                or not (
                    relative.parts[0] == package
                    or relative.parts[0].endswith((".dist-info", ".data"))
                )
            ):
                raise ValueError("engine_update_failed")
            # Wheel command-line scripts and manpages are not loaded by the app.
            if relative.parts[0].endswith(".data"):
                continue
            if not member.is_dir():
                output = target.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(member)
                if output.suffix == ".py":
                    compile(data, str(output), "exec")
                output.write_bytes(data)
    if not (target / package / "__init__.py").is_file():
        raise ValueError("engine_update_failed")


def cached_engine(root):
    return engine_record(root, read_json(root / "current.json"))


def engine_record(root, active):
    name = active.get("directory", "")
    if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
        return None
    directory = root / name
    if not all((directory / p / "__init__.py").is_file() for p in ("yt_dlp", "yt_dlp_ejs")):
        return None
    try:
        if Version(active["version"]) < Version(importlib.metadata.version("yt-dlp")):
            return None
    except (KeyError, ValueError):
        return None
    return active | {"path": str(directory)}


def prepare_engine(force=False, check=True, progress=lambda event: None, root=None):
    try:
        return _prepare_engine(force, check, progress, root)
    except (OSError, ValueError, TypeError):
        return {"version": importlib.metadata.version("yt-dlp"), "path": "", "status": "offline"}


def _prepare_engine(force=False, check=True, progress=lambda event: None, root=None):
    """Check daily, preserve the last engine on failure; never mutate running code."""
    root = Path(root) if root is not None else data_dir() / "engines"
    root.mkdir(parents=True, exist_ok=True)
    active = cached_engine(root)
    fallback = active or {"version": importlib.metadata.version("yt-dlp"), "path": ""}
    state = read_json(root / "check.json")
    status = fallback | {"status": "cached" if active else "bundled"}
    elapsed = time.time() - float(state.get("checked", 0))
    if not check or (not force and 0 <= elapsed < CHECK_INTERVAL):
        return status
    lock = root / "update.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > 300:
            lock.unlink(missing_ok=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return status | {"status": "busy"}
    os.close(descriptor)
    try:
        progress({"phase": "engine_updating"})
        latest = metadata("yt-dlp")
        version = latest["info"]["version"]
        if Version(version) < Version(fallback["version"]):
            raise ValueError("engine_update_failed")
        if Version(version) == Version(fallback["version"]) and (active or not force):
            atomic_json(root / "check.json", {"checked": time.time()})
            return status | {"status": "current"}
        # EJS is version-coupled to yt-dlp; never substitute an unrelated latest EJS.
        requirements = [Requirement(r) for r in latest["info"].get("requires_dist") or []]
        requirement = next(r for r in requirements if r.name.replace("_", "-") == "yt-dlp-ejs")
        exact = next(s.version for s in requirement.specifier if s.operator == "==")
        ejs = metadata("yt-dlp-ejs", exact)
        with tempfile.TemporaryDirectory(dir=root, prefix=".update-") as temporary:
            staging = Path(temporary)
            install_wheel(latest, staging, "yt_dlp")
            install_wheel(ejs, staging, "yt_dlp_ejs")
            name = "engine-" + version + "-" + uuid.uuid4().hex
            shutil.move(str(staging), root / name)
        previous = {k: v for k, v in (active or {}).items() if k in {"version", "ejs", "directory"}}
        active = {"version": version, "ejs": exact, "directory": name, "previous": previous}
        atomic_json(root / "current.json", active)
        atomic_json(root / "check.json", {"checked": time.time()})
        return active | {"path": str(root / name), "status": "updated"}
    except Exception:
        # A transient network/compatibility failure never destroys the working engine.
        atomic_json(root / "check.json", {"checked": time.time() - CHECK_INTERVAL + 300})
        return status | {"status": "offline"}
    finally:
        lock.unlink(missing_ok=True)


def activate_engine(state):
    """Called before any yt-dlp import, including inside a frozen worker."""
    path = state.get("path")
    if path:
        sys.path.insert(0, path)
        importlib.invalidate_caches()
        try:
            importlib.import_module("yt_dlp_ejs")
            module = importlib.import_module("yt_dlp")
            if not Path(module.__file__).resolve().is_relative_to(Path(path).resolve()):
                raise ImportError("Managed engine was not loaded")
            return state
        except Exception:
            sys.path.remove(path)
            for name in list(sys.modules):
                if name.split(".")[0] in {"yt_dlp", "yt_dlp_ejs"}:
                    sys.modules.pop(name, None)
            importlib.invalidate_caches()
            root = Path(path).parent
            current = read_json(root / "current.json")
            previous = engine_record(root, current.get("previous") or {})
            if current.get("directory") == Path(path).name:
                if previous:
                    atomic_json(
                        root / "current.json", {k: v for k, v in previous.items() if k != "path"}
                    )
                else:
                    (root / "current.json").unlink(missing_ok=True)
            if previous and previous["path"] != path:
                recovered = activate_engine(previous)
                return recovered | {"status": "fallback"}
            state = {
                "version": importlib.metadata.version("yt-dlp"),
                "path": "",
                "status": "fallback",
            }
    importlib.import_module("yt_dlp")
    return state
