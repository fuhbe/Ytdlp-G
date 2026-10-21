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
    options = base_options()
    for name in ("qjs", "deno"):
        try:
            options["js_runtimes"] = {
                "quickjs" if name == "qjs" else name: {"path": executable(name)}
            }
            break
        except ValueError:
            continue
    return options


def audio_codec(value):
    value = str(value or "").lower()
    for prefixes, family in (
        (("mp4a", "aac"), "aac"),
        (("opus",), "opus"),
        (("vorbis",), "vorbis"),
        (("mp3", "mpga"), "mp3"),
        (("flac",), "flac"),
    ):
        if value.startswith(prefixes):
            return family
    return ""


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
    """Build native stream choices and one explicit best-audio MP3 conversion.

    Video keys represent a real resolution/container, audio keys represent the
    ordered native audio qualities of a codec. Intersection works across lists
    without assuming format IDs or a fixed bitrate shared by different videos.
    """
    formats = usable_formats(info)
    pure_audio = [
        f for f in formats if f.get("vcodec") in {None, "none"} and audio_codec(f.get("acodec"))
    ]
    choices = {}
    video_groups = {}
    for video in formats:
        height = video.get("height")
        if not height or video.get("vcodec") in {None, "none"}:
            continue
        height = int(height)
        if height <= 0:
            continue
        combined = video.get("acodec") not in {None, "none"}
        ext = video.get("ext")
        if ext not in {"mp4", "webm", "mkv", "mov"}:
            continue
        if combined or not pure_audio:
            pairs = [(ext, "")]
        else:
            pairs = []
            for audio in pure_audio:
                family = audio_codec(audio.get("acodec"))
                if ext in {"mp4", "mov"} and family == "aac":
                    container = "mp4"
                elif ext == "webm" and family in {"opus", "vorbis"}:
                    container = "webm"
                else:
                    container = "mkv"
                pairs.append((container, str(audio["format_id"])))
        for container, audio_id in pairs:
            key = f"video:{container}:{height}"
            h264 = str(video.get("vcodec", "")).startswith(("avc", "h264"))
            audio = next((a for a in pure_audio if str(a["format_id"]) == audio_id), {})
            score = (
                h264,
                float(video.get("fps") or 0),
                float(audio.get("abr") or 0),
                float(video.get("tbr") or 0),
            )
            if key not in video_groups or score > video_groups[key][0]:
                video_groups[key] = (
                    score,
                    {
                        "key": key,
                        "kind": "video",
                        "height": height,
                        "container": container,
                        "video_stream": str(video["format_id"]),
                        "audio_stream": audio_id,
                        "codec": str(video.get("vcodec") or ""),
                    },
                )
    choices.update({key: value[1] for key, value in video_groups.items()})
    audio_groups = {}
    # If there are no audio-only streams, extract the existing audio losslessly.
    for fmt in pure_audio or [f for f in formats if audio_codec(f.get("acodec"))]:
        family = audio_codec(fmt.get("acodec"))
        audio_groups.setdefault(family, []).append(fmt)
    for family, candidates in audio_groups.items():
        ordered = sorted(
            candidates,
            key=lambda f: (
                float(f.get("abr") or 0),
                float(f.get("asr") or 0),
                float(f.get("tbr") or 0),
            ),
            reverse=True,
        )
        seen = set()
        rank = 0
        for fmt in ordered:
            # Repeated language/transport variants with identical quality do not
            # create dozens of indistinguishable controls in the compact window.
            bitrate = round(float(fmt.get("abr") or 0))
            fingerprint = (bitrate, fmt.get("asr"))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            container = {
                "aac": "m4a",
                "opus": "opus",
                "vorbis": "ogg",
                "mp3": "mp3",
                "flac": "flac",
                "wav": "wav",
            }[family]
            key = f"audio:{family}:{rank}"
            choices[key] = {
                "key": key,
                "kind": "audio",
                "container": container,
                "bitrate_min": bitrate,
                "bitrate_max": bitrate,
                "audio_stream": str(fmt["format_id"]),
                "video_stream": "",
                "codec": family,
            }
            rank += 1
    if any(fmt.get("acodec") not in {None, "none"} for fmt in formats):
        # An explicit conversion, not a bitrate claimed to exist at the source.
        # Leave the stream unset: yt-dlp selects bestaudio/best independently for
        # each item, including playlists whose native audio codecs differ.
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
                container=(
                    "mp3"
                    if selected.get("conversion")
                    else "original"
                    if selected["kind"] == "audio"
                    else selected["container"]
                ),
                bitrate=320 if selected.get("conversion") else 192,
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
