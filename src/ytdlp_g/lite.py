"""Available-only media choices and the two-output simplified download flow."""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import yt_dlp

from . import turbo
from .archive import create_zip
from .downloader import base_options, download, error_code
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


def enrich_metadata(info):
    """Probe direct media when the extractor cannot report codec/resolution.

    Never infer a 1080p or bitrate preset from a filename/container. Signed
    URLs and headers remain in worker memory, outside the returned catalog.
    """
    formats = info.get("formats") or [info]
    for fmt in formats:
        if (
            fmt.get("vcodec") is not None
            and fmt.get("acodec") is not None
            and (fmt.get("vcodec") == "none" or fmt.get("height"))
        ):
            continue
        source = fmt.get("url")
        if not source or fmt.get("has_drm"):
            continue
        try:
            source = validate_url(source)
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
            result = subprocess.run(
                args + ["-show_streams", "-of", "json", source],
                capture_output=True,
                text=True,
                timeout=30,
                **hidden_process(),
            )
            if result.returncode:
                continue
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
                abr=float(audio.get("bit_rate") or 0) / 1000,
                asr=audio.get("sample_rate"),
            )
            fmt.setdefault("format_id", "direct")
        except (ValueError, OSError, subprocess.TimeoutExpired):
            continue
    info["formats"] = formats
    return info


def quality_catalog(info):
    """Offer actual source resolutions with sound, always delivered as MP4/MP3."""
    formats = usable_formats(info)
    pure_audio = [
        f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in {None, "none"}
    ]
    # yt-dlp sorts formats from worst to best, accounting for codec, channels,
    # bitrate and source preferences. Preserve that ranking for separate sound.
    best_audio = pure_audio[-1] if pure_audio else None
    choices, scores = {}, {}
    for video in formats:
        height = video.get("height")
        if not height or video.get("vcodec") in {None, "none"}:
            continue
        if int(height) <= 0:
            continue
        combined = video.get("acodec") not in {None, "none"}
        if not combined and not best_audio:
            continue
        key = f"video:mp4:{int(height)}"
        score = (
            float(video.get("fps") or 0),
            video.get("dynamic_range") not in {None, "SDR"},
            int(video.get("bit_depth") or 8),
            str(video.get("vcodec", "")).startswith(("avc", "h264")),
            float(video.get("tbr") or 0),
        )
        if key not in scores or score > scores[key]:
            scores[key] = score
            choices[key] = {
                "key": key,
                "kind": "video",
                "height": int(height),
                "container": "mp4",
                "video_stream": str(video["format_id"]),
                "audio_stream": "" if combined else str(best_audio["format_id"]),
                "codec": str(video.get("vcodec") or ""),
                "hdr": video.get("dynamic_range") not in {None, "SDR"}
                or int(video.get("bit_depth") or 8) > 8,
                "fps": video.get("fps"),
                "direct": str(video.get("vcodec", "")).startswith(("avc", "h264"))
                and str((video if combined else best_audio).get("acodec", "")).startswith(
                    ("aac", "mp4a")
                ),
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
            "audio_stream": "",
            "video_stream": "",
        }
    return choices


def common_choices(catalogs):
    if not catalogs:
        return []
    keys = set(catalogs[0])
    for catalog in catalogs[1:]:
        keys.intersection_update(catalog)
    result = []
    for key in keys:
        choice = dict(catalogs[0][key])
        choice.pop("video_stream", None)
        choice.pop("audio_stream", None)
        if choice["kind"] == "audio":
            choice["bitrate_min"] = min(c[key]["bitrate_min"] for c in catalogs)
            choice["bitrate_max"] = max(c[key]["bitrate_max"] for c in catalogs)
        result.append(choice)
    return sorted(
        result,
        key=lambda c: (
            c["kind"] != "video",
            bool(c.get("conversion")),
            -c.get("height", 0),
            {"mp4": 0, "webm": 1, "mkv": 2}.get(c["container"], 3),
            -c.get("bitrate_max", 0),
            c["key"],
        ),
    )


def inspect_lite(url, emit=lambda data: None):
    url = validate_url(url)
    return turbo.cached(("catalog", url), lambda: _inspect(url, emit))


def full_info(url, index=None, entry=None, refresh=False):
    def load():
        if entry is not None:
            return enrich_metadata(entry)
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


def _inspect(url, emit):
    catalogs, items = [], []
    skipped = 0
    options = extraction_options() | {
        "skip_download": True,
        "noplaylist": False,
        "extract_flat": "in_playlist",
        "lazy_playlist": True,
        "ignoreerrors": True,
    }
    with turbo.youtube_dl(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("unavailable")
        playlist = "entries" in info
        title = info.get("title") or "download"
        count = info.get("playlist_count") or info.get("n_entries") or 0
        entries = info["entries"] if playlist else [info]

        def analyze(pair):
            index, entry = pair
            emit(
                {
                    "phase": "analyzing",
                    "current": index,
                    "total": count,
                    "title": (entry or {}).get("title", ""),
                }
            )
            if not entry:
                return None
            try:
                candidate = (
                    entry.get("webpage_url") or entry.get("url") or (url if not playlist else "")
                )
                if (
                    not str(candidate).startswith(("https://", "http://"))
                    and entry.get("ie_key") == "Youtube"
                ):
                    candidate = "https://www.youtube.com/watch?v=" + str(entry.get("id", ""))
                item_url = validate_url(candidate)
                # Embedded multi-video pages share a page URL. Keep the exact
                # page entry index so re-extraction/download selects that item.
                source_index = (
                    index if playlist and item_url == url and entry.get("formats") else None
                )
                seed = entry if source_index or not playlist and entry.get("formats") else None
                entry = full_info(item_url, source_index, seed)
                catalog = quality_catalog(entry)
                if not catalog:
                    raise ValueError("format_unavailable")
                return catalog, {
                    "url": item_url,
                    "title": entry.get("title") or title,
                    "index": index,
                    "source_index": source_index,
                }
            except (yt_dlp.utils.DownloadError, ValueError):
                return None

        for result in turbo.ordered_map(
            analyze, enumerate(entries, 1), min(4, turbo.prefs["downloads"])
        ):
            if result:
                catalog, item = result
                catalogs.append(catalog)
                items.append(item)
            else:
                skipped += 1
    if not items:
        raise ValueError("unavailable")
    choices = common_choices(catalogs)
    if not choices:
        raise ValueError("lite_no_common")
    return {
        "url": url,
        "title": title,
        "playlist": playlist,
        "items": items,
        "choices": choices,
        "skipped": skipped,
        "catalog_version": 1,
    }


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


def download_lite(payload, emit=lambda data: None):
    analysis = payload["analysis"]
    key = payload["quality"]
    if key not in {choice["key"] for choice in analysis["choices"]}:
        raise ValueError("format_unavailable")
    mode = payload["mode"]
    if mode not in {"normal", "zip"}:
        raise ValueError("invalid_options")
    destination = Path(payload["destination"]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    identifier = "lite-" + uuid.uuid4().hex
    working = destination / ".ytdlp-g" / identifier
    target = working / "files" if mode == "zip" else destination
    files, failures = [], []
    total = len(analysis["items"])

    def one(pair):
        number, item = pair
        for attempt in range(2):
            try:
                fresh = full_info(
                    validate_url(item["url"]),
                    item.get("source_index"),
                    refresh=bool(attempt) or not analysis.get("catalog_version"),
                )
                selected = quality_catalog(fresh).get(key)
                if not selected:
                    raise ValueError("format_unavailable")
                options = Options(
                    kind=selected["kind"],
                    container=selected["container"],
                    bitrate=320,
                    audio_stream=selected["audio_stream"],
                    video_stream=selected["video_stream"],
                    metadata=False,
                    organization="playlist" if analysis["playlist"] else "flat",
                ).to_dict()

                def progress(data, current=number, item_title=item["title"]):
                    emit(
                        data
                        | {
                            "phase": data.get("status", "running"),
                            "current": current,
                            "total_items": total,
                            "title": item_title,
                        }
                    )

                use_external = not attempt and use_aria(fresh, selected)
                result = download(
                    {
                        "id": f"{identifier}-{number}" + ("-aria" if use_external else ""),
                        "url": item["url"],
                        "source_index": item.get("source_index"),
                        "destination": str(target),
                        "options": options,
                        "playlist_title": analysis["title"] if analysis["playlist"] else "",
                        "playlist_index": item["index"] if analysis["playlist"] else None,
                    },
                    progress,
                    info_cache=fresh,
                    direct_mp4=not attempt and selected.get("direct", False),
                    recovery=bool(attempt),
                    aria=use_external,
                )
                return result["files"], None
            except (yt_dlp.utils.DownloadError, ValueError, OSError) as exc:
                if attempt or isinstance(exc, ValueError):
                    return [], {"index": item["index"], "code": error_code(exc)}
                turbo.feedback(failed=True)
                emit({"phase": "checking", "current": number, "total": total})

    for completed, error in turbo.ordered_map(
        one, enumerate(analysis["items"], 1), turbo.prefs["downloads"]
    ):
        files.extend(completed)
        if error:
            failures.append(error)
    if not files:
        raise ValueError(failures[0]["code"] if failures else "no_output")
    if mode == "zip":
        emit({"phase": "archiving", "progress": 0})
        archive = create_zip(
            files,
            destination / (safe_name(analysis["title"]) + ".zip"),
            compression=0,
            subfolders=True,
            progress=lambda event: emit(event | {"phase": "archiving"}),
        )
        files = [str(archive)]
        # Files are removed only after SHA256/CRC validation and final publication.
        shutil.rmtree(working)
    return {
        "files": files,
        "completed": total - len(failures),
        "failed": len(failures),
        "skipped": analysis.get("skipped", 0),
        "failures": failures,
    }
