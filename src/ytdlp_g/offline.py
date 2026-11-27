"""Local-only batch processing. All encoding targets are private staging files."""

import os
import tempfile
from pathlib import Path

from .diagnostics import diagnostic
from .media import PROFILES, ensure_mp4, fits_profile, probe
from .paths import publish, safe_name

VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".mpeg",
    ".mpg",
    ".wmv",
    ".ts",
    ".mts",
    ".m2ts",
    ".flv",
    ".ogv",
    ".3gp",
}


def input_files(inputs, destination, recursive):
    files = {}
    for name in inputs:
        path = Path(name).resolve()
        if path.is_dir():
            if path == destination:
                raise ValueError("invalid_files")
            for parent, dirs, names in os.walk(path, followlinks=False):
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if recursive
                    and d not in {".ytdlp-g", "Convertidos"}
                    and not (Path(parent) / d).resolve().is_relative_to(destination)
                )
                for n in sorted(names):
                    f = Path(parent) / n
                    if not f.is_symlink() and f.suffix.lower() in VIDEO_EXTENSIONS:
                        files[f] = None
        else:
            files[path] = None
    return list(files)


def convert_batch(payload, emit):
    destination = Path(payload["destination"]).resolve()
    profile = payload.get("profile", "compatible")
    if profile not in PROFILES:
        raise ValueError("invalid_options")
    files = input_files(payload["inputs"], destination, payload.get("recursive", False))
    excluded = set(payload.get("exclude", []))
    files = [p for p in files if str(p) not in excluded]
    if not files:
        raise ValueError("invalid_files")
    destination.mkdir(exist_ok=True, parents=True)
    results, failures, skipped = [], [], []
    for index, source in enumerate(files, 1):

        def progress(event, i=index, name=source.name):
            emit(event | {"index": i, "name": name, "total_items": len(files)})

        try:
            progress({"status": "verifying"})
            info = probe(source)
            if source.suffix.lower() == ".mp4" and fits_profile(info, profile):
                if payload.get("skip", True):
                    skipped.append(str(source))
                    progress({"status": "skipped", "source": str(source)})
                    continue
                result = publish(source, destination / (safe_name(source.stem) + ".mp4"))
            else:
                with tempfile.TemporaryDirectory(dir=destination, prefix=".convert-") as tmp:
                    output = ensure_mp4(
                        source,
                        profile=profile,
                        output_path=Path(tmp) / "final.mp4",
                        progress=progress,
                    )
                    result = publish(
                        output,
                        destination / (safe_name(source.stem) + ".mp4"),
                        immutable=output != source,
                    )
            results.append(str(result))
            progress({"status": "completed", "source": str(source)})
        except Exception as exc:
            failures.append(
                {"source": str(source), "diagnostic": diagnostic("conversion", exc, index)}
            )
    return {"files": results, "skipped": skipped, "failures": failures}
