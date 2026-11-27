"""Available-only media choices and the two-output simplified download flow."""

import hashlib
import json
import subprocess
import threading
import time
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp.utils import DownloadCancelled

from . import turbo
from .archive import Cancelled, create_zip
from .diagnostics import diagnostic
from .downloader import base_options, download
from .media import executable, hidden_process
from .models import Options
from .paths import safe_name, validate_url


def extraction_options():
    return base_options()


def usable_formats(info):
    result = []
    for fmt in info.get("formats") or []:
        identifier = str(fmt.get("format_id") or "")
        if not identifier or not all(c.isalnum() or c in "-_." for c in identifier):
            continue
        if fmt.get("has_drm") or fmt.get("ext") in {"mhtml", "json", "jpg", "png"}:
            continue
        if fmt.get("vcodec") in {None, "none"} and fmt.get("acodec") in {None, "none"}:
            continue
        result.append(fmt)
    return result


def frame_rate(stream):
    for field in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = Fraction(str(stream.get(field)))
            if 0 < rate <= 1000:
                return float(rate)
        except (ValueError, ZeroDivisionError):
            continue
    return None


def enrich_metadata(info):
    """Probe direct media when the extractor cannot report codec/resolution.

    Never infer a 1080p or bitrate preset from a filename/container. Signed
    URLs and headers remain in worker memory, outside the returned catalog.
    """
    formats = info.get("formats") or [info.copy()]

    def fill(fmt):
        if (
            fmt.get("vcodec") is not None
            and fmt.get("acodec") is not None
            and (
                fmt.get("vcodec") == "none"
                or fmt.get("height")
                and (fmt.get("fps") or fmt.get("manifest_url"))
            )
        ):
            return
        source = fmt.get("url")
        if not source or fmt.get("has_drm"):
            return
        try:
            parts = urlsplit(source)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                return
            headers = fmt.get("http_headers") or info.get("http_headers") or {}
            header_text = "".join(
                f"{key}: {value}\r\n"
                for key, value in headers.items()
                if "\r" not in str(key) + str(value) and "\n" not in str(key) + str(value)
            )
            args = [
                executable("ffprobe"),
                "-v",
                "error",
                "-rw_timeout",
                "15000000",
                "-protocol_whitelist",
                "http,https,tcp,tls,crypto",
            ]
            if header_text:
                args += ["-headers", header_text]
            with turbo.analysis_slots:
                result = subprocess.run(
                    args + ["-show_streams", "-of", "json", source],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    **hidden_process(),
                )
            if result.returncode:
                diagnostic("probe", RuntimeError(result.stderr))
                return
            streams = json.loads(result.stdout).get("streams", [])
            video = next(
                (
                    stream
                    for stream in streams
                    if stream.get("codec_type") == "video"
                    and not stream.get("disposition", {}).get("attached_pic")
                ),
                {},
            )
            audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
            fmt.update(
                vcodec=video.get("codec_name", "none"),
                acodec=audio.get("codec_name", "none"),
                height=video.get("height"),
                width=video.get("width"),
                fps=frame_rate(video) or fmt.get("fps"),
                dynamic_range={"smpte2084": "HDR10", "arib-std-b67": "HLG"}.get(
                    video.get("color_transfer"), fmt.get("dynamic_range")
                ),
                abr=float(audio.get("bit_rate") or 0) / 1000,
                asr=audio.get("sample_rate"),
            )
            fmt.setdefault("format_id", "direct")
        except (ValueError, OSError, subprocess.TimeoutExpired):
            return

    if len(formats) == 1:
        fill(formats[0])
    else:
        list(turbo.ordered_map(fill, formats, 2))
    info["formats"] = formats
    return info


def quality_catalog(info, profile="compatible"):
    """Offer actual source resolutions with sound, always delivered as MP4/MP3."""
    formats = usable_formats(info)
    pure_audio = [
        f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in {None, "none"}
    ]
    # yt-dlp sorts formats from worst to best, accounting for codec, channels,
    # bitrate and source preferences. Preserve that ranking for separate sound.
    best_audio = pure_audio[-1] if pure_audio else None
    choices = {}
    best_sources = {}
    sound = best_audio
    if profile != "original" and sound:
        for candidate in reversed(pure_audio):
            if (
                str(candidate.get("acodec")).startswith(("mp4a.40.2", "aac_low"))
                and candidate.get("audio_channels") == 2
                and candidate.get("language") == sound.get("language")
                and float(candidate.get("abr") or 0) >= 0.85 * float(sound.get("abr") or 0)
            ):
                sound = candidate
                break
    for rank, video in enumerate(formats):
        height = video.get("height")
        if not height or video.get("vcodec") in {None, "none"}:
            continue
        if int(height) <= 0:
            continue
        combined = video.get("acodec") not in {None, "none"}
        if not combined and not best_audio:
            continue
        fps = float(video["fps"]) if video.get("fps") else None
        dynamic = video.get("dynamic_range") or ""
        hdr = bool(dynamic and dynamic != "SDR")
        key = f"video:mp4:{int(height)}:{fps or '?'}:{dynamic or '?'}"
        # Formats arrive in yt-dlp's source preference order, worst first.
        previous = best_sources.get(key)
        if profile != "original" and previous:
            # Prefer AVC only within the same source quality tier and geometry.
            prior_rate = float(previous.get("vbr") or previous.get("tbr") or 0)
            rate = float(video.get("vbr") or video.get("tbr") or 0)
            if (
                str(previous.get("vcodec")).startswith(("avc", "h264"))
                and not str(video.get("vcodec")).startswith(("avc", "h264"))
                and previous.get("quality") == video.get("quality")
                and previous.get("width") == video.get("width")
                and prior_rate >= rate * 0.85
            ):
                continue
        best_sources[key] = video
        choices[key] = {
            "key": key,
            "kind": "video",
            "height": int(height),
            "container": "mp4",
            "video_stream": str(video["format_id"]),
            "audio_stream": "" if combined else str(sound["format_id"]),
            "codec": str(video.get("vcodec") or ""),
            "hdr": hdr,
            "dynamic_range": dynamic,
            "fps": fps,
            "rank": rank,
        }
    if any(fmt.get("acodec") not in {None, "none"} for fmt in formats):
        choices["audio:mp3:convert"] = {
            "key": "audio:mp3:convert",
            "kind": "audio",
            "container": "mp3",
            "codec": "mp3",
            "conversion": True,
            "bitrate_min": 320,
            "bitrate_max": 320,
            "audio_stream": next(
                (
                    str(f["format_id"])
                    for f in reversed(pure_audio)
                    if f.get("acodec") == "mp3" or f.get("ext") == "mp3"
                ),
                str(best_audio["format_id"]) if best_audio else "",
            ),
            "video_stream": "",
        }
    return choices


BEST = "video:best"
MP3 = "audio:mp3:convert"


def quality_order(choice):
    return (choice["height"], choice.get("fps") or 0, choice.get("hdr", False), choice["rank"])


def select_format(catalog, key):
    if key in catalog:
        return catalog[key]
    if key == BEST:
        limit = float("inf")
    elif key.startswith("video:max:"):
        limit = int(key.rsplit(":", 1)[1])
    else:
        raise ValueError("format_unavailable")
    candidates = [c for c in catalog.values() if c["kind"] == "video" and c["height"] <= limit]
    if not candidates:
        raise ValueError("format_unavailable")
    return max(candidates, key=quality_order)


def common_choices(catalogs, playlist=None):
    playlist = len(catalogs) > 1 if playlist is None else playlist
    combined = {k: c for catalog in catalogs for k, c in catalog.items()}
    video = sorted(
        (c for c in combined.values() if c["kind"] == "video"), key=quality_order, reverse=True
    )
    result = [{"key": BEST, "kind": "video", "container": "mp4"}] if video else []
    if playlist:
        result.extend(
            {
                "key": f"video:max:{h}",
                "kind": "video",
                "height": h,
                "container": "mp4",
                "maximum": True,
            }
            for h in sorted({c["height"] for c in video}, reverse=True)
        )
    else:
        result.extend(
            {k: v for k, v in c.items() if k not in {"audio_stream", "video_stream", "rank"}}
            for c in video
        )
    if MP3 in combined:
        result.append(
            {k: v for k, v in combined[MP3].items() if k not in {"audio_stream", "video_stream"}}
        )
    return result


def inspect_lite(url, emit=lambda data: None, profile="compatible"):
    url = validate_url(url)
    return turbo.cached(("catalog", url, profile), lambda: _inspect(url, emit, profile))


def full_info(url, index=None, entry=None, refresh=False):
    def load():
        seed = entry if entry is not None else turbo.take_seed(url, index) if not refresh else None
        if seed is not None:
            return enrich_metadata(seed)
        options = extraction_options() | {"noplaylist": True, "skip_download": True}
        if index:
            options["playlist_items"] = str(index)
        with turbo.youtube_dl(options) as single:
            raw = single.extract_info(url, download=False)
            if raw and "entries" in raw:
                raw = next(iter(raw["entries"]), None)
            if not raw:
                raise ValueError("unavailable")
            return enrich_metadata(raw)

    return turbo.cached(("info", url, index), load, refresh)


def item_references(entries, playlist, url):
    entries = iter(entries)
    index = 0
    while True:
        index += 1
        try:
            entry = next(entries) or {}
        except StopIteration:
            return
        except (Cancelled, DownloadCancelled):
            raise
        except Exception as exc:
            yield {
                "index": index,
                "title": f"#{index}",
                "discovery_error": diagnostic("extraction", exc, index),
            }
            return
        number = entry.get("playlist_index") or index
        item = {"index": number, "title": entry.get("title") or f"#{number}"}
        if entry:
            candidate = entry.get("webpage_url") or entry.get("url") or url
            if (
                not str(candidate).startswith(("https://", "http://"))
                and entry.get("ie_key") == "Youtube"
            ):
                candidate = "https://www.youtube.com/watch?v=" + str(entry.get("id", ""))
            try:
                item_url = validate_url(candidate) if playlist else url
            except ValueError:
                item_url = url
            source_index = number if playlist and item_url == url else None
            item.update(url=item_url, source_index=source_index)
            if entry.get("formats"):
                # Keep raw streams in RAM. Detailed probing is deferred to the item worker.
                turbo.cached(
                    ("seed", item_url, source_index), lambda entry=entry: entry, refresh=True
                )
        yield item


@contextmanager
def playlist_source(url, emit):
    options = extraction_options() | {
        "skip_download": True,
        "noplaylist": False,
        "extract_flat": "in_playlist",
        "lazy_playlist": True,
        "ignoreerrors": False,
    }
    emit({"phase": "analyzing"})
    with turbo.youtube_dl(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("unavailable")
        playlist = "entries" in info
        entries = info["entries"] if playlist else [info]
        count = (
            len(entries)
            if isinstance(entries, (list, tuple))
            else info.get("playlist_count") or info.get("n_entries") or 0
        )
        yield {
            "url": url,
            "title": info.get("title") or "download",
            "playlist": playlist,
            "count": count,
            "catalog_version": 2,
            "items": item_references(entries, playlist, url),
        }


def list_items(url, emit):
    with playlist_source(url, emit) as plan:
        items = list(plan["items"])
        return plan | {"items": items, "skipped": sum("url" not in i for i in items)}


def _inspect(url, emit, profile):
    plan = list_items(url, emit)

    def analyze(item):
        if "url" not in item:
            return {}
        emit({"phase": "analyzing", "current": item["index"], "total": len(plan["items"])})
        try:
            return quality_catalog(full_info(item["url"], item.get("source_index")), profile)
        except (Cancelled, DownloadCancelled):
            raise
        except Exception as exc:
            item["inspection_error"] = diagnostic("extraction", exc, item["index"])
            return {}

    catalogs = list(turbo.ordered_map(analyze, plan["items"], min(4, turbo.prefs["downloads"])))
    plan["choices"] = common_choices(catalogs, plan["playlist"])
    if not plan["choices"]:
        error = next(
            (i["inspection_error"]["code"] for i in plan["items"] if "inspection_error" in i),
            "unavailable",
        )
        raise ValueError(error)
    return plan


def use_aria(info, selected):
    from urllib.request import Request, urlopen

    if turbo.prefs["downloader"] == "native":
        return False
    try:
        executable("aria2c")
    except ValueError:
        return False
    formats = usable_formats(info)
    ids = {selected.get("video_stream"), selected.get("audio_stream")} - {""}
    candidates = [f for f in formats if f.get("format_id") in ids] if ids else formats
    if not candidates or any(f.get("protocol") not in {"http", "https"} for f in candidates):
        return False
    if turbo.prefs["downloader"] == "aria2c":
        return True
    fmt = candidates[-1]
    if (fmt.get("filesize") or fmt.get("filesize_approx") or 0) < 16 * 1024**2:
        return False
    try:
        with urlopen(Request(fmt["url"], headers={"Range": "bytes=0-0"}), timeout=3) as response:
            return response.status == 206 and response.headers.get("Content-Range", "").startswith(
                "bytes 0-0/"
            )
    except (ValueError, OSError):
        return False


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()[:20]


def saved_item(record, target):
    try:
        saved = json.loads(record.read_text("utf-8"))
        paths = []
        for name, size, stamp in saved["files"]:
            path = (target / name).resolve()
            if not path.is_relative_to(target) or path.is_symlink():
                return None
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (size, stamp):
                return None
            paths.append(str(path))
        return (paths, saved.get("lower")) if paths else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def save_record(record, target, files, lower):
    records = []
    for name in files:
        path = Path(name)
        stat = path.stat()
        records.append((str(path.relative_to(target)), stat.st_size, stat.st_mtime_ns))
    record.parent.mkdir(parents=True, exist_ok=True)
    tmp = record.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(files=records, lower=lower)), "utf8")
    tmp.replace(record)


def finish_zip(files, destination, title, emit):
    return str(
        turbo.zip_pool.submit(
            create_zip,
            files,
            destination / (safe_name(title, 70) + ".zip"),
            compression=0,
            subfolders=True,
            progress=lambda e: emit(
                e | {"phase": "archiving", "progress": 95 + min(4, e["progress"] * 0.04)}
            ),
        ).result()
    )


def job_id(url, quality, mode, profile):
    if quality == MP3 or profile == "original":
        return identity(url, quality, mode)
    from .media import PROFILES

    if profile not in PROFILES:
        raise ValueError("invalid_options")
    return identity(url, quality, mode, profile)


def retry_zip(payload, emit):
    from .paths import cleanup_stage

    destination = Path(payload["destination"]).resolve()
    working = (
        destination
        / ".ytdlp-g"
        / job_id(payload["url"], payload["quality"], "zip", payload.get("profile", "compatible"))
    )
    state = json.loads((working / "archive.json").read_text("utf8"))
    target = (working / "files").resolve()
    files = []
    for name, size, stamp in state["files"]:
        path = (target / name).resolve()
        if not path.is_relative_to(target) or not path.is_file():
            raise ValueError("invalid_files")
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (size, stamp):
            raise ValueError("zip_integrity")
        files.append(path)
    try:
        archive = finish_zip(files, destination, state["title"], emit)
    except (Cancelled, DownloadCancelled):
        raise
    except Exception as exc:
        return state["result"] | {
            "status": "zip_failed",
            "archive_error": diagnostic("zip", exc),
            "files": [str(f) for f in files],
        }
    try:
        (working / "archive.json").unlink(missing_ok=True)
    except OSError as exc:
        diagnostic("cleanup", exc)
    if not state["result"]["failed"] and not state["result"]["skipped"]:
        cleanup_stage(working)
    return state["result"] | {"files": [archive]}


def download_lite(payload, emit=lambda data: None):
    url = payload.get("url") or (payload.get("analysis") or {}).get("url")
    if url and payload["mode"] == "zip":
        key = job_id(url, payload["quality"], "zip", payload.get("profile", "compatible"))
        pending = Path(payload["destination"]) / ".ytdlp-g" / key / "archive.json"
        if pending.is_file():
            return retry_zip(payload | {"url": url}, emit)
    if payload.get("analysis"):
        return download_plan(payload, payload["analysis"], emit)
    with playlist_source(validate_url(payload["url"]), emit) as plan:
        return download_plan(payload, plan, emit)


def download_plan(payload, analysis, emit):
    from .paths import cleanup_stage

    key = payload["quality"]
    if key not in {BEST, MP3} and key not in {
        choice["key"] for choice in analysis.get("choices", [])
    }:
        raise ValueError("format_unavailable")
    mode = payload["mode"]
    if mode not in {"normal", "zip"}:
        raise ValueError("invalid_options")
    destination = Path(payload["destination"]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    profile = payload.get("profile", "compatible")
    job = job_id(analysis.get("url") or analysis["items"][0].get("url"), key, mode, profile)
    working = destination / ".ytdlp-g" / job
    target = working / "files" if mode == "zip" else destination
    items = analysis["items"]
    total = len(items) if isinstance(items, list) else analysis["count"]
    fractions = {}
    counts = dict(completed=0, failed=0, skipped=0)
    lock = threading.Lock()

    def report(item, event, outcome=None):
        i = item["index"]
        with lock:
            if outcome:
                counts[outcome] += 1
                fractions[i] = 1
            elif event.get("status") == "running":
                fractions[i] = max(fractions.get(i, 0), min(0.9, event.get("progress", 0) * 0.009))
            elif event.get("status") == "processing" and event.get("encoder"):
                fractions[i] = max(
                    fractions.get(i, 0), 0.90 + min(0.09, event.get("progress", 0) * 0.0009)
                )
            emit(
                event
                | counts
                | {
                    "aggregate": True,
                    "phase": event.get("phase") or event.get("status", "running"),
                    "progress": min(1, sum(fractions.values()) / total)
                    * (95 if mode == "zip" else 99)
                    if total
                    else 0,
                    "current": i,
                    "total_items": total,
                    "remaining": max(0, total - sum(counts.values())) if total else "?",
                }
            )

    def one(item):
        i = item["index"]
        if item.get("discovery_error"):
            report(item, {}, "failed")
            return [], item["discovery_error"], None
        if "url" not in item:
            report(item, {}, "skipped")
            return [], None, None
        stamp = identity(job, i, item["url"], item.get("source_index"), item["title"])
        record = working / (stamp + ".json")
        previous = saved_item(record, target)
        if previous:
            report(item, {}, "completed")
            return previous[0], None, previous[1]
        original = None
        for attempt in range(2):
            stage = "extraction"
            try:
                report(item, {"phase": "checking"})
                fresh = full_info(
                    validate_url(item["url"]),
                    item.get("source_index"),
                    refresh=bool(attempt) or not analysis.get("catalog_version"),
                )
                selected = select_format(quality_catalog(fresh, profile), key)
                if (
                    original
                    and selected["kind"] == "video"
                    and quality_order(selected)[:3] < quality_order(original)[:3]
                ):
                    raise ValueError("selection_mismatch")
                original = selected
                selected["duration"] = fresh.get("duration") if not fresh.get("is_live") else None
                options = Options(
                    kind=selected["kind"],
                    container=selected["container"],
                    bitrate=320,
                    audio_stream=selected["audio_stream"],
                    video_stream=selected["video_stream"],
                    metadata=False,
                    organization="playlist" if analysis["playlist"] else "flat",
                ).to_dict()
                external = not attempt and use_aria(fresh, selected)
                # Distinct downloader/format staging also avoids Beta 1's 40-character ID truncation.
                identifier = identity(
                    stamp, selected["video_stream"], selected["audio_stream"], external, attempt
                )
                stage = "download"
                result = download(
                    {
                        "id": identifier,
                        "lite": True,
                        "selected": selected,
                        "profile": profile,
                        "url": item["url"],
                        "source_index": item.get("source_index"),
                        "destination": str(target),
                        "options": options,
                        "playlist_title": analysis["title"] if analysis["playlist"] else "",
                        "playlist_index": i if analysis["playlist"] else None,
                    },
                    lambda data: report(item, data),
                    info_cache=fresh,
                    recovery=bool(attempt),
                    aria=external,
                )
                stage = "publish"
                files = result["files"]
                lower = (
                    {"index": i, "height": selected["height"]}
                    if key.startswith("video:max:")
                    and selected["height"] < int(key.rsplit(":", 1)[1])
                    else None
                )
                save_record(record, target, files, lower)
                report(item, {}, "completed")
                return files, None, lower
            except (Cancelled, DownloadCancelled):
                raise
            except Exception as exc:
                detail = diagnostic(getattr(exc, "stage", stage), exc, i, attempt + 1)
                permanent = {
                    "access_denied",
                    "disk_full",
                    "private_media",
                    "unavailable",
                    "invalid_url",
                    "dependency_missing",
                    "selection_mismatch",
                    "hdr_unsupported",
                    "conversion_failed",
                    "merge_failed",
                    "publish_failed",
                    "invalid_options",
                }
                if attempt or detail["code"] in permanent:
                    report(item, {}, "failed")
                    return [], detail, None
                turbo.feedback(failed=True)
                if detail.get("http") == 429 or detail["code"] == "network_error":
                    time.sleep(2 if detail.get("http") == 429 else 1)

    files, failures, lower = [], [], []
    for paths, failure, adjusted in turbo.ordered_map(
        one, items, turbo.prefs["downloads"] + turbo.prefs["conversions"]
    ):
        files.extend(paths)
        if failure:
            failures.append(failure)
        if adjusted:
            lower.append(adjusted)
    status = "failed" if not files else "partial" if failures or counts["skipped"] else "complete"
    result = counts | {"status": status, "failures": failures, "lower": lower, "remaining": 0}
    if mode == "zip" and files:
        state = {
            "title": safe_name(analysis["title"], 70),
            "result": result,
            "files": [
                (str(p.relative_to(target)), p.stat().st_size, p.stat().st_mtime_ns)
                for p in map(Path, files)
            ],
        }
        tmp = working / "archive.tmp"
        tmp.write_text(json.dumps(state), "utf8")
        tmp.replace(working / "archive.json")
        try:
            files = [finish_zip(files, destination, analysis["title"], emit)]
        except (Cancelled, DownloadCancelled):
            raise
        except Exception as exc:
            detail = diagnostic("zip", exc)
            return result | {"status": "zip_failed", "archive_error": detail, "files": files}
        try:
            (working / "archive.json").unlink(missing_ok=True)
        except OSError as exc:
            diagnostic("cleanup", exc)
    if status == "complete":
        cleanup_stage(working)
    return result | {"files": files}
