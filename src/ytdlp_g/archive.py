"""Cancellable ZIP creation, verified before publication or source removal."""

import hashlib
import tempfile
import zipfile
from pathlib import Path

from .paths import publish, safe_name


class Cancelled(Exception):
    pass


def create_zip(
    sources,
    target,
    compression=0,
    preserve=True,
    subfolders=False,
    progress=lambda event: None,
    cancelled=lambda: False,
):
    sources = [Path(p).absolute() for p in sources]
    if not sources or len(set(sources)) != len(sources):
        raise ValueError("invalid_files")
    if any(not p.is_file() or p.is_symlink() for p in sources):
        raise ValueError("invalid_files")
    target = Path(target).absolute()
    if target in sources:
        raise ValueError("invalid_files")
    target.parent.mkdir(parents=True, exist_ok=True)
    total = sum(p.stat().st_size for p in sources) or 1
    common = Path(__import__("os").path.commonpath([str(p.parent) for p in sources]))
    used, records = set(), []
    written = 0
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".ytdlpg-zip-") as temp:
        temporary = Path(temp) / "archive.zip"
        method = zipfile.ZIP_STORED if not compression else zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(
            temporary, "w", method, compresslevel=compression or None, allowZip64=True
        ) as archive:
            for source in sources:
                relative = source.relative_to(common) if subfolders else Path(source.name)
                parts = [safe_name(part) for part in relative.parts]
                name = "/".join(parts)
                counter = 0
                while name.casefold() in used:
                    counter += 1
                    name = "/".join(
                        parts[:-1] + [f"{Path(parts[-1]).stem} ({counter}){Path(parts[-1]).suffix}"]
                    )
                used.add(name.casefold())
                digest = hashlib.sha256()
                stat = source.stat()
                with (
                    source.open("rb") as incoming,
                    archive.open(name, "w", force_zip64=True) as outgoing,
                ):
                    while chunk := incoming.read(1024 * 1024):
                        if cancelled():
                            raise Cancelled()
                        outgoing.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        progress(
                            {"status": "archiving", "progress": min(99, written * 100 / total)}
                        )
                records.append((source, name, digest.hexdigest(), stat.st_size, stat.st_mtime_ns))
        with zipfile.ZipFile(temporary) as archive:
            for _, name, expected, _, _ in records:
                digest = hashlib.sha256()
                with archive.open(name) as entry:
                    while chunk := entry.read(1024 * 1024):
                        if cancelled():
                            raise Cancelled()
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError("zip_integrity")
        if cancelled():
            raise Cancelled()
        result = publish(temporary, target)
        # Publish copies bytes; verify the actual destination as well.
        try:
            with zipfile.ZipFile(result) as archive:
                if archive.testzip() is not None:
                    raise ValueError("zip_integrity")
        except BaseException:
            result.unlink(missing_ok=True)
            raise
        if not preserve:
            for source, _, _, size, mtime in records:
                current = source.stat()
                if current.st_size == size and current.st_mtime_ns == mtime:
                    source.unlink()
        progress({"status": "archiving", "progress": 100})
        return result
