"""yt-dlp API adapter. Network work is called only inside an isolated worker."""

import json
import shutil
import subprocess
from pathlib import Path

import yt_dlp

from .archive import create_zip
from .media import executable
from .models import Options
from .paths import publish, safe_name, validate_url


class QuietLogger:
    def debug(self, message):
        pass

    info = warning = error = debug


def base_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "logger": QuietLogger(),
        "socket_timeout": 15,
        "windowsfilenames": True,
        "noprogress": True,
        "cachedir": False,
        "color": "never",
    }


def summarize(info):
    """Restrict metadata to UI fields; never serialize extraction credentials."""
    keys = (
        "id",
        "title",
        "thumbnail",
        "uploader",
        "channel",
        "extractor_key",
        "duration",
        "upload_date",
        "description",
        "webpage_url",
        "playlist_count",
        "availability",
        "playlist_index",
    )
    result = {key: info.get(key) for key in keys}
    if not result["thumbnail"] and info.get("thumbnails"):
        result["thumbnail"] = info["thumbnails"][-1].get("url")
    result["description"] = str(result["description"] or "")[:3000]
    result["formats"] = [
        {
            key: fmt.get(key)
            for key in (
                "format_id",
                "ext",
                "height",
                "width",
                "fps",
                "vcodec",
                "acodec",
                "language",
                "filesize",
                "filesize_approx",
                "format_note",
                "audio_channels",
            )
        }
        for fmt in info.get("formats", [])
    ]
    result["subtitles"] = list((info.get("subtitles") or {}).keys())
    result["automatic_captions"] = list((info.get("automatic_captions") or {}).keys())
    result["chapters"] = [
        {key: item.get(key) for key in ("title", "start_time", "end_time")}
        for item in info.get("chapters") or []
    ]
    return result


def inspect(url, playlist=False, page=1, page_size=100):
    url = validate_url(url)
    options = base_options() | {"skip_download": True, "noplaylist": not playlist}
    if playlist:
        if not 1 <= int(page) <= 10000:
            raise ValueError("invalid_options")
        options |= {
            "extract_flat": "in_playlist",
            "lazy_playlist": True,
            "playlist_items": f"{(page - 1) * page_size + 1}:{page * page_size}",
            "ignoreerrors": True,
        }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("unavailable")
        result = summarize(info)
        if "entries" in info:
            result["entries"] = []
            for index, entry in enumerate(info["entries"], (page - 1) * page_size + 1):
                if not entry:
                    continue
                item = summarize(entry)
                item["playlist_index"] = item.get("playlist_index") or index
                candidate = entry.get("webpage_url") or entry.get("url", "")
                if (
                    not candidate.startswith(("https://", "http://"))
                    and entry.get("ie_key") == "Youtube"
                ):
                    candidate = "https://www.youtube.com/watch?v=" + str(entry.get("id", ""))
                try:
                    item["webpage_url"] = validate_url(candidate)
                except ValueError:
                    item["webpage_url"] = ""
                result["entries"].append(item)
            result["page"] = page
        return result


def format_selector(options):
    if options.kind in {"audio", "subtitles"}:
        return options.audio_stream or "bestaudio/best"
    if options.video_stream:
        return options.video_stream + (
            "+" + options.audio_stream
            if options.audio_stream and options.kind != "video_only"
            else ""
        )
    constraint = f"[height<={options.quality}]" if options.quality.isdigit() else ""
    video = "bv" if options.kind == "video_only" else "bv*"
    if options.quality == "compatible":
        if options.kind == "video_only":
            return "bv[vcodec^=avc1]/bv"
        return f"{video}[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/b"
    if options.quality == "small":
        return "wv*+wa/w" if options.kind != "video_only" else "wv"
    if options.kind == "video_only":
        return f"bv{constraint}"
    return f"{video}{constraint}+ba/b{constraint}"


def download_options(options, stage, progress):
    postprocessors = []
    prefix = (
        (safe_name(options.name_prefix, 30).replace("%", "%%") + " - ")
        if options.name_prefix
        else ""
    )
    template = prefix + f"%({options.name_primary}).80s"
    if options.name_secondary != "none":
        template += f" [%({options.name_secondary}).30s]"
    template += ".%(ext)s"
    result = base_options() | {
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        # Keep the destination out of the template: yt-dlp's filename trimming
        # operates on the whole template and can truncate long Windows parents.
        "outtmpl": template,
        "paths": {"home": str(stage)},
        "format": format_selector(options),
        "retries": options.retries,
        "fragment_retries": options.retries,
        "retry_sleep_functions": {"http": lambda n: min(30, 2**n)},
        "progress_hooks": [progress],
        "postprocessor_hooks": [lambda event: progress({"status": "postprocessing"})],
        "writethumbnail": options.thumbnail or options.embed_thumbnail,
        "writeinfojson": False,
        "clean_infojson": True,
        "writedescription": options.description,
        "skip_download": options.kind == "subtitles",
        "writesubtitles": bool(options.subtitles),
        "writeautomaticsub": options.auto_subtitles,
        "subtitleslangs": [v.strip() for v in options.subtitles.split(",") if v.strip()],
        "subtitlesformat": "vtt/best",
        "allow_unplayable_formats": False,
    }
    try:
        result["js_runtimes"] = {"deno": {"path": executable("deno")}}
    except ValueError:
        pass
    try:
        result["ffmpeg_location"] = str(Path(executable("ffmpeg", options.ffmpeg)).parent)
    except ValueError:
        if options.kind == "audio" and options.container == "original":
            pass
        else:
            raise
    try:
        result["js_runtimes"] = {"quickjs": {"path": executable("qjs")}}
    except ValueError:
        pass
    if options.rate_limit:
        result["ratelimit"] = options.rate_limit * 1024
    if options.codec != "auto":
        result["format_sort"] = [
            {"h264": "vcodec:h264", "hevc": "vcodec:h265", "av1": "vcodec:av01"}[options.codec]
        ]
    if options.kind == "audio" and options.container != "original":
        codec = "vorbis" if options.container == "ogg" else options.container
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": str(options.bitrate),
            }
        )
    elif options.kind == "audio" and options.container == "original":
        postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": "best"})
    elif options.kind in {"video", "video_only"}:
        result["merge_output_format"] = options.container
        postprocessors.append({"key": "FFmpegVideoRemuxer", "preferedformat": options.container})
    if options.subtitles and options.subtitle_format == "srt":
        postprocessors.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})
    if options.embed_subtitles:
        if options.container not in {"mp4", "mkv", "mov", "webm"} or options.kind == "subtitles":
            raise ValueError("incompatible_container")
        postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": True})
    if options.metadata and options.kind != "subtitles":
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
    if options.embed_thumbnail:
        if options.container not in {"mp3", "m4a", "opus", "flac", "mkv", "mp4", "mov"}:
            raise ValueError("incompatible_container")
        postprocessors.append(
            {"key": "EmbedThumbnail", "already_have_thumbnail": options.thumbnail}
        )
    if options.sponsor_mode != "off":
        categories = set(options.sponsor_categories.split(","))
        postprocessors.insert(
            0, {"key": "SponsorBlock", "categories": categories, "when": "after_filter"}
        )
        if options.sponsor_mode == "remove":
            postprocessors.append({"key": "ModifyChapters", "remove_sponsor_segments": categories})
    result["postprocessors"] = postprocessors
    return result


def organization_folder(info, options):
    field = {
        "channel": "uploader",
        "artist": "artist",
        "album": "album",
        "playlist": "playlist",
        "date": "upload_date",
        "platform": "extractor_key",
        "resolution": "height",
    }.get(options.organization)
    if options.organization == "flat":
        return Path()
    if options.organization == "type":
        return Path(options.kind)
    value = info.get(field) or info.get("_playlist_title") or "unknown"
    if options.organization == "album":
        return Path(safe_name(info.get("artist") or "unknown")) / safe_name(value)
    return Path(safe_name(value))


def download(payload, emit=lambda event: None):
    options = Options.from_dict(payload["options"])
    destination = Path(payload["destination"]).resolve()
    identifier = safe_name(payload["id"], 40)
    stage = destination / ".ytdlp-g" / identifier
    stage.mkdir(parents=True, exist_ok=True)

    def hook(event):
        status = event.get("status")
        if status in {"finished", "postprocessing"}:
            emit({"status": "processing", "progress": 0})
        elif status == "downloading":
            total = event.get("total_bytes") or event.get("total_bytes_estimate") or 0
            downloaded = event.get("downloaded_bytes", 0)
            emit(
                {
                    "status": "running",
                    "downloaded": downloaded,
                    "total": total,
                    "progress": min(100, downloaded * 100 / total) if total else 0,
                    "speed": event.get("speed") or 0,
                    "eta": event.get("eta") or 0,
                    "estimated": int(not bool(event.get("total_bytes"))),
                }
            )

    extraction = download_options(options, stage, hook)
    if payload.get("source_index"):
        extraction["playlist_items"] = str(int(payload["source_index"]))
    with yt_dlp.YoutubeDL(extraction) as ydl:
        info = ydl.extract_info(validate_url(payload["url"]), download=True)
        if not info:
            raise ValueError("unavailable")
    if options.info_json:
        # Do not export signed media URLs or request headers from yt-dlp's raw info.
        clean = summarize(info)
        clean.pop("webpage_url", None)
        clean.pop("thumbnail", None)
        json_file = stage / (safe_name(info.get("title") or "download") + ".info.json")
        json_file.write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")
    info["_playlist_title"] = payload.get("playlist_title", "")
    if payload.get("playlist_title"):
        info["playlist"] = payload["playlist_title"]
    files = sorted(
        p
        for p in stage.iterdir()
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp"))
    )
    if not files:
        raise ValueError("no_output")
    folder = destination / organization_folder(info, options)
    prefix = f"{int(payload['playlist_index']):03d} - " if payload.get("playlist_index") else ""
    published = []
    # Source staging remains intact on errors. Publication never replaces a file.
    if options.output_mode in {"normal", "both"}:
        for source in files:
            target = folder / (prefix + safe_name(source.stem, 110) + source.suffix)
            published.append(str(publish(source, target)))
    if options.output_mode in {"zip", "both"}:
        emit({"status": "archiving", "progress": 0})
        result = create_zip(
            files,
            folder / (prefix + safe_name(info.get("title", "download")) + ".zip"),
            options.compression,
            progress=emit,
        )
        published.append(str(result))
    shutil.rmtree(stage)
    # Sensitive URL query values are never put in progress or diagnostics.
    return {"files": published, "title": info.get("title", ""), "progress": 100}


def error_code(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return "operation_failed"
    text = str(error).lower()
    for marker, code in (
        ("private", "private_media"),
        ("sign in", "private_media"),
        ("unsupported url", "unsupported_url"),
        ("not available", "unavailable"),
        ("removed", "unavailable"),
        ("http error", "network_error"),
        ("timed out", "network_error"),
        ("requested format", "format_unavailable"),
    ):
        if marker in text:
            return code
    if isinstance(error, ValueError) and str(error) in {
        "lite_no_common",
        "format_unavailable",
        "invalid_options",
        "invalid_url",
        "invalid_time",
        "dependency_missing",
        "dependency_invalid",
        "conversion_failed",
        "media_invalid",
        "incompatible_container",
        "no_output",
        "unavailable",
        "zip_integrity",
        "invalid_files",
    }:
        return str(error)
    return "operation_failed"
