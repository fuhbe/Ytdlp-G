"""Available-only media choices and the two-output simplified download flow."""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import yt_dlp

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
            str(video.get("vcodec", "")).startswith(("avc", "h264")),
            float(video.get("fps") or 0),
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
    catalogs, items = [], []
    skipped = 0
    options = extraction_options() | {
        "skip_download": True,
        "noplaylist": False,
        "extract_flat": "in_playlist",
        "lazy_playlist": True,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("unavailable")
        playlist = "entries" in info
        title = info.get("title") or "download"
        count = info.get("playlist_count") or info.get("n_entries") or 0
        entries = info["entries"] if playlist else [info]
        for index, entry in enumerate(entries, 1):
            emit(
                {
                    "phase": "analyzing",
                    "current": index,
                    "total": count,
                    "title": (entry or {}).get("title", ""),
                }
            )
            if not entry:
                skipped += 1
                continue
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
                if not source_index and (playlist or not entry.get("formats")):
                    with yt_dlp.YoutubeDL(
                        extraction_options() | {"noplaylist": True, "skip_download": True}
                    ) as single:
                        entry = single.extract_info(item_url, download=False)
                if not entry:
                    raise ValueError("unavailable")
                catalog = quality_catalog(enrich_metadata(entry))
                if not catalog:
                    raise ValueError("format_unavailable")
                catalogs.append(catalog)
                items.append(
                    {
                        "url": item_url,
                        "title": entry.get("title") or title,
                        "index": index,
                        "source_index": source_index,
                    }
                )
            except (yt_dlp.utils.DownloadError, ValueError):
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
    }


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
    for number, item in enumerate(analysis["items"], 1):
        emit({"phase": "checking", "current": number, "total": total, "title": item["title"]})
        try:
            extraction = extraction_options() | {"skip_download": True, "noplaylist": True}
            if item.get("source_index"):
                extraction["playlist_items"] = str(item["source_index"])
            with yt_dlp.YoutubeDL(extraction) as ydl:
                fresh = ydl.extract_info(validate_url(item["url"]), download=False)
                if fresh and "entries" in fresh:
                    fresh = next(iter(fresh["entries"]), None)
            selected = quality_catalog(enrich_metadata(fresh or {})).get(key)
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

            result = download(
                {
                    "id": f"{identifier}-{number}",
                    "url": item["url"],
                    "source_index": item.get("source_index"),
                    "destination": str(target),
                    "options": options,
                    "playlist_title": analysis["title"] if analysis["playlist"] else "",
                    "playlist_index": item["index"] if analysis["playlist"] else None,
                },
                progress,
            )
            files.extend(result["files"])
        except (yt_dlp.utils.DownloadError, ValueError, OSError) as exc:
            failures.append({"index": item["index"], "code": error_code(exc)})
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
